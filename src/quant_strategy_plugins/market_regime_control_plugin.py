from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .artifacts import write_json
from .plugin_signal_utils import flatten_for_csv, json_scalar

SCHEMA_VERSION = "market_regime_control.v1"
SHADOW_MODE = "shadow"
MARKET_REGIME_CONTROL_PROFILE = "market_regime_control"

COMPONENT_CRISIS = "crisis"
COMPONENT_MACRO = "macro"
COMPONENT_TACO = "taco"
COMPONENT_PANIC_REVERSAL = "panic_reversal"

ROUTE_NO_ACTION = "no_action"
ROUTE_WATCH = "watch"
ROUTE_OPPORTUNITY_WATCH = "opportunity_watch"
ROUTE_RISK_REDUCED = "risk_reduced"
ROUTE_RISK_OFF = "risk_off"
ROUTE_BLOCKED = "blocked"

ACTION_NO_ACTION = "no_action"
ACTION_WATCH_ONLY = "watch_only"
ACTION_NOTIFY_MANUAL_REVIEW = "notify_manual_review"
ACTION_DELEVER = "delever"
ACTION_DEFEND = "defend"
ACTION_BLOCKED = "blocked"

CRISIS_ACTIVE_ROUTES = frozenset({"true_crisis"})
CRISIS_WATCH_ROUTES = frozenset({"valuation_fragility", "systemic_stress_watch", "rate_bear", "policy_shock_watch"})
MACRO_ACTIVE_ROUTES = frozenset({"delever", "crisis"})
MACRO_WATCH_ROUTES = frozenset({"watch"})
TACO_ACTIVE_ROUTES = frozenset({"taco_rebound", "taco_fake_crisis"})
PANIC_REVERSAL_ACTIVE_ROUTES = frozenset({"panic_reversal"})


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off", ""}:
        return False
    return bool(default)


def _as_float(value: Any, *, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = float(default)
    if not pd.notna(result):
        result = float(default)
    return float(result)


def _clamp_ratio(value: Any, *, default: float) -> float:
    return max(0.0, min(1.0, _as_float(value, default=default)))


def _optional_text(value: Any) -> str:
    return str(value or "").strip()


def _normalized_route(payload: Mapping[str, Any] | None) -> str:
    if not isinstance(payload, Mapping):
        return ""
    return _optional_text(payload.get("canonical_route") or payload.get("route")).lower()


def _normalized_action(payload: Mapping[str, Any] | None) -> str:
    if not isinstance(payload, Mapping):
        return ""
    return _optional_text(payload.get("suggested_action") or payload.get("action")).lower()


def _component_key(payload: Mapping[str, Any]) -> str | None:
    plugin = _optional_text(payload.get("plugin") or payload.get("profile")).lower()
    if "crisis_response" in plugin:
        return COMPONENT_CRISIS
    if "macro_risk_governor" in plugin:
        return COMPONENT_MACRO
    if "taco" in plugin:
        return COMPONENT_TACO
    if "panic_reversal" in plugin:
        return COMPONENT_PANIC_REVERSAL
    return None


def _normalize_component_signals(
    component_signals: Mapping[str, Mapping[str, Any]] | Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    if isinstance(component_signals, Mapping):
        normalized: dict[str, Mapping[str, Any]] = {}
        for key, payload in component_signals.items():
            if not isinstance(payload, Mapping):
                continue
            component = str(key or "").strip().lower()
            if component in {COMPONENT_CRISIS, COMPONENT_MACRO, COMPONENT_TACO, COMPONENT_PANIC_REVERSAL}:
                normalized[component] = payload
                continue
            inferred = _component_key(payload)
            if inferred:
                normalized[inferred] = payload
        return normalized

    normalized = {}
    for payload in component_signals:
        if not isinstance(payload, Mapping):
            continue
        component = _component_key(payload)
        if component:
            normalized[component] = payload
    return normalized


def _reason_codes(payload: Mapping[str, Any] | None) -> tuple[str, ...]:
    if not isinstance(payload, Mapping):
        return ()
    raw = payload.get("reason_codes")
    if isinstance(raw, str):
        return tuple(item.strip() for item in raw.split(",") if item.strip())
    if isinstance(raw, Sequence) and not isinstance(raw, (bytes, bytearray)):
        return tuple(str(item).strip() for item in raw if str(item).strip())
    route = _normalized_route(payload)
    if route and route != ROUTE_NO_ACTION:
        return (route,)
    return ()


def _blocked(payload: Mapping[str, Any] | None) -> bool:
    if not isinstance(payload, Mapping):
        return False
    return _as_bool(payload.get("kill_switch_active"), default=False) or _normalized_action(payload) == ACTION_BLOCKED


def _compact_signal(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {"available": False}
    compact = {
        "available": True,
        "profile": _optional_text(payload.get("plugin") or payload.get("profile")),
        "schema_version": _optional_text(payload.get("schema_version")),
        "as_of": _optional_text(payload.get("as_of")),
        "canonical_route": _normalized_route(payload),
        "suggested_action": _normalized_action(payload),
        "would_trade_if_enabled": _as_bool(payload.get("would_trade_if_enabled"), default=False),
        "kill_switch_active": _blocked(payload),
        "reason_codes": _reason_codes(payload),
    }
    for key in (
        "actionable_score",
        "total_score",
        "leverage_scalar",
        "risk_asset_scalar",
        "risk_multiplier_suggestion",
        "manual_review_required",
        "rebound_context_active",
        "event_context_active",
        "panic_reversal_context_active",
        "price_crisis_guard_active",
        "watch_label",
        "notification_reason",
        "suppression_reason",
    ):
        if key in payload:
            compact[key] = payload.get(key)
    for key in (
        "data_freshness",
        "data_quality",
        "event_quality",
        "panic_reversal_quality",
        "audit_summary",
        "metrics",
        "rebound_confirmation",
        "reversal_confirmation",
        "selected_event",
    ):
        value = payload.get(key)
        if isinstance(value, Mapping):
            compact[key] = dict(value)
    return json_scalar(compact)


def _signal_as_of(components: Mapping[str, Mapping[str, Any]], explicit_as_of: str | None) -> str:
    explicit = _optional_text(explicit_as_of)
    if explicit:
        return explicit
    dates = sorted(_optional_text(payload.get("as_of")) for payload in components.values() if _optional_text(payload.get("as_of")))
    return dates[-1] if dates else datetime.now(timezone.utc).date().isoformat()


def build_market_regime_control_signal(
    component_signals: Mapping[str, Mapping[str, Any]] | Sequence[Mapping[str, Any]],
    *,
    strategy_policy: str = "levered_growth_income_v1",
    taco_opportunity_size_scalar: float = 0.0,
    as_of: str | None = None,
) -> dict[str, Any]:
    components = _normalize_component_signals(component_signals)
    crisis = components.get(COMPONENT_CRISIS)
    macro = components.get(COMPONENT_MACRO)
    taco = components.get(COMPONENT_TACO)
    panic_reversal = components.get(COMPONENT_PANIC_REVERSAL)

    crisis_route = _normalized_route(crisis)
    macro_route = _normalized_route(macro)
    taco_route = _normalized_route(taco)
    panic_reversal_route = _normalized_route(panic_reversal)
    crisis_active = bool(crisis_route in CRISIS_ACTIVE_ROUTES and not _blocked(crisis))
    crisis_watch = bool(
        crisis_route in CRISIS_WATCH_ROUTES
        or (
            isinstance(crisis, Mapping)
            and _optional_text(crisis.get("watch_label"))
            and _normalized_action(crisis) == ACTION_WATCH_ONLY
        )
    )
    macro_active = bool(macro_route in MACRO_ACTIVE_ROUTES and not _blocked(macro))
    macro_watch = bool(macro_route in MACRO_WATCH_ROUTES and not _blocked(macro))
    taco_active = bool(
        taco_route in TACO_ACTIVE_ROUTES
        and not _blocked(taco)
        and (
            _as_bool(taco.get("manual_review_required") if isinstance(taco, Mapping) else None, default=False)
            or _as_bool(taco.get("rebound_context_active") if isinstance(taco, Mapping) else None, default=False)
            or taco_route == "taco_fake_crisis"
        )
    )
    taco_watch = bool(isinstance(taco, Mapping) and _normalized_action(taco) == ACTION_WATCH_ONLY and not _blocked(taco))
    panic_reversal_active = bool(
        panic_reversal_route in PANIC_REVERSAL_ACTIVE_ROUTES
        and not _blocked(panic_reversal)
        and (
            _as_bool(
                panic_reversal.get("manual_review_required") if isinstance(panic_reversal, Mapping) else None,
                default=False,
            )
            or _as_bool(
                panic_reversal.get("panic_reversal_context_active") if isinstance(panic_reversal, Mapping) else None,
                default=False,
            )
        )
    )
    panic_reversal_watch = bool(
        isinstance(panic_reversal, Mapping)
        and _normalized_action(panic_reversal) == ACTION_WATCH_ONLY
        and not _blocked(panic_reversal)
    )
    blocked = any(_blocked(payload) for payload in components.values())

    final_route = ROUTE_NO_ACTION
    suggested_action = ACTION_NO_ACTION
    route_source = "none"
    would_trade_if_enabled = False
    risk_budget_scalar = 1.0
    leverage_scalar = 1.0
    risk_asset_scalar = 1.0
    taco_allowed = False
    panic_reversal_allowed = False
    local_delever_veto_allowed = False
    crisis_defense_required = False
    blocked_actions: tuple[str, ...] = ()
    vetoes: list[str] = []
    reason_codes: list[str] = []

    if crisis_active:
        final_route = ROUTE_RISK_OFF
        suggested_action = ACTION_DEFEND
        route_source = COMPONENT_CRISIS
        would_trade_if_enabled = True
        risk_budget_scalar = 0.0
        leverage_scalar = 0.0
        risk_asset_scalar = 0.0
        crisis_defense_required = True
        blocked_actions = ("increase_leverage", "increase_risk", "taco_rebound_veto", "panic_reversal_veto")
        reason_codes.extend(f"crisis:{code}" for code in _reason_codes(crisis) or ("true_crisis",))
        if taco_active:
            vetoes.append("crisis_blocks_taco")
        if panic_reversal_active:
            vetoes.append("crisis_blocks_panic_reversal")
    elif macro_active and macro_route == "crisis":
        final_route = ROUTE_RISK_OFF
        suggested_action = ACTION_DEFEND
        route_source = COMPONENT_MACRO
        would_trade_if_enabled = True
        leverage_scalar = _clamp_ratio(macro.get("leverage_scalar") if isinstance(macro, Mapping) else None, default=0.0)
        risk_asset_scalar = _clamp_ratio(macro.get("risk_asset_scalar") if isinstance(macro, Mapping) else None, default=0.0)
        risk_budget_scalar = risk_asset_scalar
        blocked_actions = ("increase_leverage", "increase_risk", "taco_rebound_veto", "panic_reversal_veto")
        reason_codes.extend(f"macro:{code}" for code in _reason_codes(macro) or ("crisis",))
        if taco_active:
            vetoes.append("macro_crisis_blocks_taco")
        if panic_reversal_active:
            vetoes.append("macro_crisis_blocks_panic_reversal")
    elif macro_active:
        final_route = ROUTE_RISK_REDUCED
        suggested_action = ACTION_DELEVER
        route_source = COMPONENT_MACRO
        would_trade_if_enabled = True
        leverage_scalar = _clamp_ratio(macro.get("leverage_scalar") if isinstance(macro, Mapping) else None, default=0.0)
        risk_asset_scalar = _clamp_ratio(macro.get("risk_asset_scalar") if isinstance(macro, Mapping) else None, default=1.0)
        risk_budget_scalar = risk_asset_scalar
        blocked_actions = ("increase_leverage", "taco_rebound_veto", "panic_reversal_veto")
        reason_codes.extend(f"macro:{code}" for code in _reason_codes(macro) or ("delever",))
        if taco_active:
            vetoes.append("macro_delever_blocks_taco")
        if panic_reversal_active:
            vetoes.append("macro_delever_blocks_panic_reversal")
    elif blocked:
        final_route = ROUTE_BLOCKED
        suggested_action = ACTION_BLOCKED
        route_source = "data_quality"
        reason_codes.extend(f"{key}:blocked" for key, payload in components.items() if _blocked(payload))
    elif taco_active or panic_reversal_active:
        final_route = ROUTE_OPPORTUNITY_WATCH
        suggested_action = ACTION_NOTIFY_MANUAL_REVIEW
        route_source = COMPONENT_TACO if taco_active else COMPONENT_PANIC_REVERSAL
        taco_allowed = bool(taco_active)
        panic_reversal_allowed = bool(panic_reversal_active)
        local_delever_veto_allowed = True
        if taco_active:
            reason_codes.extend(f"taco:{code}" for code in _reason_codes(taco) or ("taco_rebound",))
        if panic_reversal_active:
            reason_codes.extend(
                f"panic_reversal:{code}" for code in _reason_codes(panic_reversal) or ("panic_reversal",)
            )
    elif macro_watch or crisis_watch or taco_watch or panic_reversal_watch:
        final_route = ROUTE_WATCH
        suggested_action = ACTION_WATCH_ONLY
        route_source = "watch"
        reason_codes.extend(f"macro:{code}" for code in _reason_codes(macro))
        reason_codes.extend(f"crisis:{code}" for code in _reason_codes(crisis))
        reason_codes.extend(f"taco:{code}" for code in _reason_codes(taco))
        reason_codes.extend(f"panic_reversal:{code}" for code in _reason_codes(panic_reversal))

    notification = {
        "allowed": True,
        "profile": "shadow_only" if suggested_action != ACTION_NOTIFY_MANUAL_REVIEW else "manual_review_only",
        "should_notify": final_route not in {ROUTE_NO_ACTION},
        "route": final_route,
        "suggested_action": suggested_action,
        "route_source": route_source,
        "reason_codes": tuple(dict.fromkeys(reason_codes)),
        "vetoes": tuple(vetoes),
    }
    position_control = {
        "allowed": True,
        "mode": SHADOW_MODE,
        "final_route": final_route,
        "suggested_action": suggested_action,
        "route_source": route_source,
        "risk_budget_scalar": _clamp_ratio(risk_budget_scalar, default=1.0),
        "leverage_scalar": _clamp_ratio(leverage_scalar, default=1.0),
        "risk_asset_scalar": _clamp_ratio(risk_asset_scalar, default=1.0),
        "taco_allowed": taco_allowed,
        "taco_size_scalar": _clamp_ratio(taco_opportunity_size_scalar, default=0.0) if taco_allowed else 0.0,
        "panic_reversal_allowed": panic_reversal_allowed,
        "panic_reversal_size_scalar": 0.0,
        "local_delever_veto_allowed": local_delever_veto_allowed,
        "crisis_defense_required": crisis_defense_required,
        "blocked_actions": blocked_actions,
        "defensive_destination_role": "cash_like" if final_route == ROUTE_RISK_OFF else "unlevered_or_cash_like",
        "reason_codes": tuple(dict.fromkeys(reason_codes)),
        "vetoes": tuple(vetoes),
    }
    signal_as_of = _signal_as_of(components, as_of)
    payload = {
        "as_of": signal_as_of,
        "mode": SHADOW_MODE,
        "schema_version": SCHEMA_VERSION,
        "profile": MARKET_REGIME_CONTROL_PROFILE,
        "canonical_route": final_route,
        "suggested_action": suggested_action,
        "would_trade_if_enabled": would_trade_if_enabled,
        "strategy_policy": str(strategy_policy or "levered_growth_income_v1").strip(),
        "arbiter": {
            "schema_version": "market_regime_arbiter.v1",
            "final_route": final_route,
            "suggested_action": suggested_action,
            "route_source": route_source,
            "vetoes": tuple(vetoes),
            "reason_codes": tuple(dict.fromkeys(reason_codes)),
        },
        "notification": notification,
        "position_control": position_control,
        "component_signals": {
            COMPONENT_CRISIS: _compact_signal(crisis),
            COMPONENT_MACRO: _compact_signal(macro),
            COMPONENT_TACO: _compact_signal(taco),
            COMPONENT_PANIC_REVERSAL: _compact_signal(panic_reversal),
        },
        "execution_controls": {
            "capital_impact": "strategy_opt_in",
            "broker_order_allowed": False,
            "live_allocation_mutation_allowed": False,
            "repository_broker_write_allowed": False,
            "repository_allocation_mutation_allowed": False,
            "log_namespace": MARKET_REGIME_CONTROL_PROFILE,
            "notification_profile": notification["profile"],
            "intended_strategy_role": "unified_market_regime_control",
            "strategy_runtime_metadata_allowed": True,
            "position_control_shadow_only": True,
            "ai_audit_shadow_only": False,
        },
        "audit_summary": {
            "route_source": route_source,
            "final_route": final_route,
            "suggested_action": suggested_action,
            "reason_codes": tuple(dict.fromkeys(reason_codes)),
            "vetoes": tuple(vetoes),
            "note": "Deterministic arbiter only; AI and OSINT-only evidence cannot directly increase position authority.",
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return json_scalar(payload)


def write_market_regime_control_outputs(payload: Mapping[str, Any], output_dir: str | Path) -> dict[str, Path]:
    output_root = Path(output_dir)
    signal_date = str(payload["as_of"])
    signal_dir = output_root / "signals"
    audit_dir = output_root / "audit"
    latest_path = output_root / "latest_signal.json"
    dated_json_path = signal_dir / f"{signal_date}.json"
    dated_csv_path = signal_dir / f"{signal_date}.csv"
    evidence_csv_path = audit_dir / f"{signal_date}_evidence.csv"

    write_json(latest_path, payload)
    write_json(dated_json_path, payload)
    signal_dir.mkdir(parents=True, exist_ok=True)
    audit_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([flatten_for_csv(payload)]).to_csv(dated_csv_path, index=False)
    evidence_payload = {
        "as_of": payload.get("as_of"),
        "canonical_route": payload.get("canonical_route"),
        "suggested_action": payload.get("suggested_action"),
        **flatten_for_csv(payload.get("arbiter", {})),
        **flatten_for_csv(payload.get("position_control", {})),
        **flatten_for_csv(payload.get("component_signals", {})),
    }
    pd.DataFrame([evidence_payload]).to_csv(evidence_csv_path, index=False)
    return {
        "latest_signal": latest_path,
        "signal_json": dated_json_path,
        "signal_csv": dated_csv_path,
        "evidence_csv": evidence_csv_path,
    }


__all__ = [
    "MARKET_REGIME_CONTROL_PROFILE",
    "SCHEMA_VERSION",
    "build_market_regime_control_signal",
    "write_market_regime_control_outputs",
]
