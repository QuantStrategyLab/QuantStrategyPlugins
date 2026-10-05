"""Pure, standard-library, unvalidated semiconductor observation reference.

No defaults, market downloads, I/O, clock reads, runtime integration, or orders.
Qualification checks caller declarations and consistency, not provider truth.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .plugin_signal_envelope_v2 import build_signal_envelope, canonical_json_bytes

INPUT_VERSION = "qsl.semiconductor-regime-input.research.v1"
CONFIG_VERSION = "qsl.semiconductor-regime-config.research.v1"
OBSERVATION_VERSION = "qsl.semiconductor-regime-observation.research.v1"
FEATURE_VERSION = "qsl.trailing-semiconductor-features.research.v1"
PLUGIN_ID = "semiconductor_regime_observer_research"
REPOSITORY = "QuantStrategyLab/QuantStrategyPlugins"
ENTRYPOINT = "quant_strategy_plugins.semiconductor_regime_observer_research:build_semiconductor_regime_signal_v2"

_CONFIG_KEYS = {
    "schema_version", "sma_window_sessions", "sma_slope_lag_sessions", "path_window_returns",
    "short_vol_window_returns", "long_vol_window_returns", "drawdown_window_sessions",
    "annualization_sessions", "ttl_seconds", "classification",
}
_INPUT_KEYS = {
    "schema_version", "symbol", "series_role", "as_of", "available_at", "decision_at",
    "calendar", "adjustment", "components", "bars",
}
_FEATURE_KEYS = (
    "close_to_sma_ratio", "sma_slope_per_session", "path_efficiency",
    "short_realized_volatility_annualized", "long_realized_volatility_annualized",
    "volatility_ratio", "trailing_drawdown_ratio",
)
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class ContractError(ValueError):
    """Invalid research configuration or envelope binding, without input echo."""


def _canonical(value: Any) -> bytes:
    return canonical_json_bytes(value)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _exact(value: Any, keys: set[str]) -> bool:
    return isinstance(value, Mapping) and set(value) == keys


def _date(value: Any) -> str | None:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        return None
    try:
        return value if date.fromisoformat(value).isoformat() == value else None
    except ValueError:
        return None


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str) or "T" not in value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def _stamp(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value is not None else None


def _version(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and "latest" not in value.casefold()


def _finite(value: Any, *, positive=False) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value) and (not positive or value > 0)
    except OverflowError:
        return False


def _validate_config(value: Any) -> dict:
    if not _exact(value, _CONFIG_KEYS) or value["schema_version"] != CONFIG_VERSION:
        raise ContractError("CONFIG_INVALID")
    cfg = dict(value)
    for name in _CONFIG_KEYS - {"schema_version", "classification"}:
        if not isinstance(cfg[name], int) or isinstance(cfg[name], bool) or cfg[name] <= 0:
            raise ContractError("CONFIG_INVALID")
    if min(cfg["sma_window_sessions"], cfg["path_window_returns"], cfg["short_vol_window_returns"],
           cfg["long_vol_window_returns"], cfg["drawdown_window_sessions"]) < 2:
        raise ContractError("CONFIG_INVALID")
    if cfg["short_vol_window_returns"] > cfg["long_vol_window_returns"]:
        raise ContractError("CONFIG_INVALID")
    classifier = cfg["classification"]
    if classifier is not None:
        if not _exact(classifier, {"hypothesis_id", "status", "direction", "trendiness", "pressure"}):
            raise ContractError("CLASSIFICATION_CONFIG_INVALID")
        if not _version(classifier["hypothesis_id"]) or classifier["status"] != "UNVALIDATED_RESEARCH_HYPOTHESIS":
            raise ContractError("CLASSIFICATION_CONFIG_INVALID")
        fields = {
            "direction": {"price_distance_min", "sma_slope_min"},
            "trendiness": {"range_efficiency_max", "trend_efficiency_min"},
            "pressure": {"drawdown_normal_max", "drawdown_stress_min", "volatility_ratio_normal_max", "volatility_ratio_stress_min"},
        }
        for axis, keys in fields.items():
            if not _exact(classifier[axis], keys) or not all(_finite(v) for v in classifier[axis].values()):
                raise ContractError("CLASSIFICATION_CONFIG_INVALID")
        d, t, p = (classifier[k] for k in ("direction", "trendiness", "pressure"))
        if not (d["price_distance_min"] > 0 and d["sma_slope_min"] > 0
                and 0 <= t["range_efficiency_max"] < t["trend_efficiency_min"] <= 1
                and 0 <= p["drawdown_normal_max"] < p["drawdown_stress_min"] <= 1
                and 0 <= p["volatility_ratio_normal_max"] < p["volatility_ratio_stress_min"]):
            raise ContractError("CLASSIFICATION_CONFIG_INVALID")
    # Detached JSON-only config; no opaque values or undeclared knobs.
    return json.loads(_canonical(cfg))


def semiconductor_regime_observer_config_sha256(config: Mapping[str, Any]) -> str:
    return _digest(_validate_config(config))


def _safe_hash_value(value: Any) -> Any:
    """Invalid data gets stable error identity; it never becomes usable evidence."""
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, (int, float)):
        return value if _finite(value) else {"invalid_number": str(value)}
    if isinstance(value, Mapping):
        return {str(k): _safe_hash_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_hash_value(v) for v in value]
    return {"invalid_type": type(value).__name__}


def _slice_rows(rows: Any, cutoff: str | None, decision: datetime | None, *, bars: bool) -> tuple[list, list[str]]:
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        return [], ["BARS_INVALID" if bars else "CALENDAR_SESSIONS_INVALID"]
    selected, reasons = [], []
    for row in rows:
        if not isinstance(row, Mapping) or _date(row.get("date")) is None or cutoff is None:
            reasons.append("ROW_SELECTOR_INVALID")
            continue
        # Reject no payload fields before this causal date slice. Future payload
        # can be malformed, contain NaN, or unknown keys and remains invisible.
        if row["date"] > cutoff:
            continue
        if bars:
            published = _time(row.get("available_at"))
            if published is None or decision is None:
                reasons.append("ROW_SELECTOR_INVALID")
                continue
            # A hidden late revision's other columns are irrelevant too.
            if published > decision:
                continue
            adjusted = _time(row.get("adjustment_available_at"))
            if adjusted is None:
                reasons.append("ROW_SELECTOR_INVALID")
                continue
            if adjusted > decision:
                continue
        selected.append(dict(row))
    return selected, reasons


def _project(data: Any) -> tuple[dict, list[str]]:
    if not isinstance(data, Mapping):
        return {}, ["INPUT_FIELDS_INVALID"]
    projected = dict(data)
    cutoff, decision = _date(data.get("as_of")), _time(data.get("decision_at"))
    selected, reasons = _slice_rows(data.get("bars"), cutoff, decision, bars=True)
    projected["bars"] = selected
    calendar = data.get("calendar")
    if isinstance(calendar, Mapping):
        calendar = dict(calendar)
        sessions, errors = _slice_rows(calendar.get("sessions"), cutoff, decision, bars=False)
        reasons.extend(errors)
        calendar["sessions"] = sessions
        projected["calendar"] = calendar
    return projected, reasons


def _minimum(cfg: dict) -> int:
    return max(cfg["sma_window_sessions"] + cfg["sma_slope_lag_sessions"], cfg["path_window_returns"] + 1,
               cfg["short_vol_window_returns"] + 1, cfg["long_vol_window_returns"] + 1,
               cfg["drawdown_window_sessions"])


def _qualify(data: dict, cfg: dict, initial: list[str]) -> tuple[list[str], datetime | None]:
    reasons = list(initial)
    if not _exact(data, _INPUT_KEYS) or data.get("schema_version") != INPUT_VERSION:
        reasons.append("INPUT_FIELDS_INVALID")
    symbol, role = data.get("symbol"), data.get("series_role")
    if not ((symbol == "SOXX" and role == "SIGNAL_PROXY") or (symbol == "SOXL" and role == "EXECUTION_BENCHMARK")):
        reasons.append("SYMBOL_ROLE_UNSUPPORTED")
    cutoff = _date(data.get("as_of"))
    decision, available = _time(data.get("decision_at")), _time(data.get("available_at"))
    if cutoff is None or decision is None or available is None:
        reasons.append("OBSERVATION_TIMES_INVALID")
    if decision is not None and available is not None and available > decision:
        reasons.append("SNAPSHOT_UNAVAILABLE_AT_DECISION")
    calendar, adjustment, components = (data.get(k) for k in ("calendar", "adjustment", "components"))
    cal_keys = {"id", "version", "available_at", "sessions"}
    adj_keys = {"basis", "version", "available_at", "point_in_time_attested"}
    if not _exact(calendar, cal_keys):
        reasons.append("CALENDAR_DECLARATION_INVALID")
        calendar = calendar if isinstance(calendar, Mapping) else {}
    if not _version(calendar.get("id")) or not _version(calendar.get("version")):
        reasons.append("CALENDAR_ID_VERSION_REQUIRED")
    cal_avail = _time(calendar.get("available_at"))
    if cal_avail is None or decision is None or cal_avail > decision:
        reasons.append("CALENDAR_UNAVAILABLE_AT_DECISION")
    if not _exact(adjustment, adj_keys):
        reasons.append("ADJUSTMENT_DECLARATION_INVALID")
        adjustment = adjustment if isinstance(adjustment, Mapping) else {}
    if adjustment.get("basis") not in {"raw", "split_adjusted", "split_and_distribution_adjusted"}:
        reasons.append("ADJUSTMENT_BASIS_UNSUPPORTED")
    if not _version(adjustment.get("version")):
        reasons.append("ADJUSTMENT_VERSION_REQUIRED")
    if adjustment.get("point_in_time_attested") is not True:
        reasons.append("ADJUSTMENT_PIT_NOT_ATTESTED")
    adj_avail = _time(adjustment.get("available_at"))
    if adj_avail is None or decision is None or adj_avail > decision:
        reasons.append("ADJUSTMENT_UNAVAILABLE_AT_DECISION")
    if not _exact(components, {"prices", "calendar", "adjustment"}):
        reasons.append("COMPONENTS_INVALID")
        components = components if isinstance(components, Mapping) else {}
    declared_availabilities = [cal_avail, adj_avail]
    for name in ("prices", "calendar", "adjustment"):
        component = components.get(name)
        if not _exact(component, {"as_of", "available_at", "version"}):
            reasons.append("COMPONENTS_INVALID")
            continue
        if component["as_of"] != cutoff:
            reasons.append("COMPONENT_AS_OF_MISMATCH")
        if not _version(component["version"]):
            reasons.append("COMPONENT_VERSION_INVALID")
        comp_avail = _time(component["available_at"])
        declared_availabilities.append(comp_avail)
        if comp_avail is None or decision is None or comp_avail > decision:
            reasons.append("COMPONENT_UNAVAILABLE_AT_DECISION")
        if name != "prices":
            metadata = calendar if name == "calendar" else adjustment
            if component["version"] != metadata.get("version") or comp_avail != _time(metadata.get("available_at")):
                reasons.append("COMPONENT_VERSION_MISMATCH")
    sessions = calendar.get("sessions", [])
    sessions = sessions if isinstance(sessions, list) else []
    dates, closes = [], {}
    for session in sessions:
        if not _exact(session, {"date", "close_at", "complete"}):
            reasons.append("CALENDAR_SESSION_FIELDS_INVALID")
        session_date = _date(session.get("date"))
        if session_date is None:
            reasons.append("CALENDAR_DATE_INVALID")
            continue
        if dates and session_date <= dates[-1]:
            reasons.append("CALENDAR_DATES_NOT_STRICTLY_INCREASING")
        dates.append(session_date)
        close = _time(session.get("close_at"))
        closes[session_date] = close
        if close is None or close.date().isoformat() != session_date:
            reasons.append("SESSION_CLOSE_TIME_INVALID")
        if close is not None and (decision is None or close > decision):
            reasons.append("SESSION_NOT_CLOSED_AT_DECISION")
        if session.get("complete") is not True:
            reasons.append("SESSION_NOT_COMPLETE")
    if len(dates) < _minimum(cfg):
        reasons.append("INSUFFICIENT_CALENDAR_HISTORY")
    if not dates or dates[-1] != cutoff:
        reasons.append("CALENDAR_AS_OF_MISMATCH")
    bars, bar_dates = data.get("bars", []), []
    bars = bars if isinstance(bars, list) else []
    row_availabilities = []
    for bar in bars:
        if not _exact(bar, {"symbol", "date", "close", "closed", "available_at", "adjustment_available_at", "adjustment_version"}):
            reasons.append("BAR_FIELDS_INVALID")
        session_date = _date(bar.get("date"))
        if bar_dates and session_date <= bar_dates[-1]:
            reasons.append("BAR_DATES_NOT_STRICTLY_INCREASING")
        bar_dates.append(session_date)
        if bar.get("symbol") != symbol:
            reasons.append("BAR_SYMBOL_MISMATCH")
        if not _finite(bar.get("close"), positive=True):
            reasons.append("CLOSE_INVALID")
        if bar.get("closed") is not True:
            reasons.append("BAR_NOT_CLOSED")
        if bar.get("adjustment_version") != adjustment.get("version"):
            reasons.append("BAR_ADJUSTMENT_VERSION_MISMATCH")
        pub, adj = _time(bar.get("available_at")), _time(bar.get("adjustment_available_at"))
        row_availabilities.extend((pub, adj))
        close = closes.get(session_date)
        if session_date not in closes:
            reasons.append("BAR_NOT_IN_CALENDAR")
        if pub is not None and close is not None and pub < close:
            reasons.append("BAR_AVAILABLE_BEFORE_CLOSE")
        if pub is not None and adj is not None and pub < adj:
            reasons.append("BAR_AVAILABLE_BEFORE_ADJUSTMENT")
    needed_dates = dates[-_minimum(cfg):]
    if len(bars) < _minimum(cfg) or not set(needed_dates).issubset(bar_dates) or (bar_dates and bar_dates[-1] != cutoff):
        reasons.append("SESSION_COVERAGE_INCOMPLETE")
    if available is not None and any(item is not None and item > available for item in declared_availabilities + row_availabilities):
        reasons.append("SNAPSHOT_AVAILABILITY_PRECEDES_INPUT")
    prices_component = components.get("prices", {})
    prices_avail = _time(prices_component.get("available_at")) if isinstance(prices_component, Mapping) else None
    if prices_avail is not None and any(item is not None and item > prices_avail for item in row_availabilities):
        reasons.append("PRICE_COMPONENT_AVAILABILITY_PRECEDES_BARS")
    latest_close = closes.get(cutoff)
    try:
        valid_until = latest_close + timedelta(seconds=cfg["ttl_seconds"]) if latest_close is not None else None
    except OverflowError:
        valid_until = None
        reasons.append("TTL_INVALID_FOR_SESSION")
    if decision is not None and valid_until is not None and decision >= valid_until:
        reasons.append("OBSERVATION_EXPIRED")
    return sorted(set(reasons)), valid_until


def _features(bars: list, cfg: dict) -> dict:
    # Shared ratios/volatility/drawdown follow pinned QSP QQQ observer formulas.
    close = [float(row["close"]) for row in bars]
    m, lag = cfg["sma_window_sessions"], cfg["sma_slope_lag_sessions"]
    mean = math.fsum(close[-m:]) / m
    past_mean = math.fsum(close[-m-lag:-lag]) / m
    returns = [later / earlier - 1 for earlier, later in zip(close, close[1:])]

    def volatility(window):
        values = returns[-window:]
        average = math.fsum(values) / window
        variance = math.fsum((v - average) ** 2 for v in values) / window
        return math.sqrt(variance * cfg["annualization_sessions"])

    short, long = volatility(cfg["short_vol_window_returns"]), volatility(cfg["long_vol_window_returns"])
    path = close[-cfg["path_window_returns"]-1:]
    distance = math.fsum(abs(later - earlier) for earlier, later in zip(path, path[1:]))
    values = {
        "close_to_sma_ratio": close[-1] / mean - 1,
        "sma_slope_per_session": (mean / past_mean - 1) / lag,
        "path_efficiency": abs(path[-1] - path[0]) / distance if distance else None,
        "short_realized_volatility_annualized": short,
        "long_realized_volatility_annualized": long,
        "volatility_ratio": short / long if long else None,
        "trailing_drawdown_ratio": close[-1] / max(close[-cfg["drawdown_window_sessions"]:]) - 1,
    }
    if any(v is not None and not math.isfinite(v) for v in values.values()):
        raise ArithmeticError("FEATURE_NONFINITE")
    return {key: (None if value is None else (0.0 if round(value, 12) == 0 else round(value, 12))) for key, value in values.items()}


def _axis(state="unknown", reason="CLASSIFICATION_NOT_CONFIGURED") -> dict:
    return {"state": state, "reason_codes": [reason]}


def _classify(facts: dict, classifier: dict | None) -> dict:
    axes = {key: _axis() for key in ("direction", "trendiness", "pressure")}
    if classifier is None:
        return axes
    d, t, p = (classifier[k] for k in ("direction", "trendiness", "pressure"))
    price, slope = facts["close_to_sma_ratio"], facts["sma_slope_per_session"]
    if price >= d["price_distance_min"] and slope >= d["sma_slope_min"]:
        axes["direction"] = _axis("up", "DIRECTION_FEATURES_ALIGNED")
    elif price <= -d["price_distance_min"] and slope <= -d["sma_slope_min"]:
        axes["direction"] = _axis("down", "DIRECTION_FEATURES_ALIGNED")
    else:
        conflict = ((price >= d["price_distance_min"] and slope <= -d["sma_slope_min"])
                    or (price <= -d["price_distance_min"] and slope >= d["sma_slope_min"]))
        axes["direction"] = _axis(reason="DIRECTION_FEATURE_CONFLICT" if conflict else "DIRECTION_THRESHOLD_GAP")
    efficiency = facts["path_efficiency"]
    if efficiency is None:
        axes["trendiness"] = _axis(reason="ZERO_PATH_VARIATION")
    elif efficiency >= t["trend_efficiency_min"]:
        axes["trendiness"] = _axis("trend_like", "PATH_EFFICIENCY_ABOVE_RESEARCH_THRESHOLD")
    elif efficiency <= t["range_efficiency_max"]:
        axes["trendiness"] = _axis("range_like", "PATH_EFFICIENCY_BELOW_RESEARCH_THRESHOLD")
    else:
        axes["trendiness"] = _axis(reason="TRENDINESS_THRESHOLD_GAP")
    drawdown, ratio = -facts["trailing_drawdown_ratio"], facts["volatility_ratio"]
    if ratio is None:
        axes["pressure"] = _axis(reason="ZERO_LONG_VOLATILITY")
    elif drawdown >= p["drawdown_stress_min"] and ratio >= p["volatility_ratio_stress_min"]:
        axes["pressure"] = _axis("stressed", "PRESSURE_FEATURES_ALIGNED")
    elif drawdown <= p["drawdown_normal_max"] and ratio <= p["volatility_ratio_normal_max"]:
        axes["pressure"] = _axis("normal", "PRESSURE_FEATURES_ALIGNED")
    else:
        conflict = ((drawdown >= p["drawdown_stress_min"] and ratio <= p["volatility_ratio_normal_max"])
                    or (drawdown <= p["drawdown_normal_max"] and ratio >= p["volatility_ratio_stress_min"]))
        axes["pressure"] = _axis(reason="PRESSURE_FEATURE_CONFLICT" if conflict else "PRESSURE_THRESHOLD_GAP")
    return axes


def build_semiconductor_regime_observation(snapshot: Mapping[str, Any], config: Mapping[str, Any]) -> dict:
    """Describe one causal observation; missing/invalid input becomes unknown.

    Config is mandatory and has no numeric defaults. Thresholds may be None.
    Hidden rows never enter features, validation, counters, or input identity.
    """
    cfg = _validate_config(config)
    data, selectors = _project(snapshot)
    reasons, expiry = _qualify(data, cfg, selectors)
    facts = dict.fromkeys(_FEATURE_KEYS)
    if not reasons:
        try:
            facts = _features(data["bars"], cfg)
        except (ArithmeticError, ValueError):
            reasons = ["FEATURE_COMPUTATION_UNDEFINED"]
    axes = ({key: _axis(reason="INPUT_QUALIFICATION_FAILED") for key in ("direction", "trendiness", "pressure")}
            if reasons else _classify(facts, cfg["classification"]))
    decision, input_available = _time(data.get("decision_at")), _time(data.get("available_at"))
    available_candidates = [v for v in (decision, input_available) if v is not None]
    calendar, adjustment, components = (data.get(k) for k in ("calendar", "adjustment", "components"))
    calendar = calendar if isinstance(calendar, Mapping) else {}
    adjustment = adjustment if isinstance(adjustment, Mapping) else {}
    components = components if isinstance(components, Mapping) else {}
    prices = components.get("prices", {})
    prices = prices if isinstance(prices, Mapping) else {}

    def declared_text(value):
        return value if isinstance(value, str) else None

    return {
        "schema_version": OBSERVATION_VERSION,
        "research_status": "UNVALIDATED_RESEARCH",
        "symbol": data.get("symbol") if isinstance(data.get("symbol"), str) else None,
        "series_role": data.get("series_role") if isinstance(data.get("series_role"), str) else None,
        "as_of": _date(data.get("as_of")),
        "input_available_at": _stamp(input_available),
        # This reference is observed at decision_at. A real producer must set
        # that instant no earlier than its actual completed publication time.
        "available_at": _stamp(max(available_candidates)) if available_candidates else None,
        "decision_at": _stamp(decision),
        "valid_until": _stamp(expiry),
        "versions": {"feature": FEATURE_VERSION, "configuration_sha256": _digest(cfg)},
        "input_context": {
            "calendar_id": declared_text(calendar.get("id")),
            "calendar_version": declared_text(calendar.get("version")),
            "adjustment_basis": declared_text(adjustment.get("basis")),
            "adjustment_version": declared_text(adjustment.get("version")),
            "prices_producer_version": declared_text(prices.get("version")),
        },
        "input_sha256": _digest(_safe_hash_value(data)),
        "features": facts,
        "axes": axes,
        "quality": {
            "status": "unknown" if reasons else "qualified_by_declaration",
            "reason_codes": reasons,
            "minimum_required_sessions": _minimum(cfg),
            "observed_sessions": len(data.get("bars", [])),
            "assurance": "CALLER_DECLARATIONS_AND_CONSISTENCY_ONLY",
        },
    }


def semiconductor_regime_observation_usable_at(observation: Mapping[str, Any], at: str) -> bool:
    """Fresh evidence check only, never an instruction or trading permission."""
    if not isinstance(observation, Mapping) or not isinstance(observation.get("quality"), Mapping):
        return False
    when, decision, available, expiry = (_time(v) for v in (
        at, observation.get("decision_at"), observation.get("available_at"), observation.get("valid_until")))
    return bool(observation.get("schema_version") == OBSERVATION_VERSION
                and observation.get("quality", {}).get("status") == "qualified_by_declaration"
                and all(v is not None for v in (when, decision, available, expiry))
                and max(decision, available) <= when < expiry)


def build_semiconductor_regime_signal_v2(
    *,
    snapshot: Mapping[str, Any],
    config: Mapping[str, Any],
    producer: Mapping[str, Any],
    input_provenance: Mapping[str, Any],
) -> dict:
    """Build a research-only V2 observation with the existing pure helper.

    The P1 manifest must already describe this causal projection. This checks
    declared identity and consistency, never provider truth or P1 qualification.
    Nothing registers, enables, routes, publishes, or authorizes this signal.
    """
    cfg = _validate_config(config)
    observation = build_semiconductor_regime_observation(snapshot, cfg)
    if (not isinstance(producer, Mapping)
            or producer.get("repo") != REPOSITORY
            or producer.get("entrypoint") != ENTRYPOINT
            or producer.get("config_sha256") != _digest(cfg)
            or not _exact(input_provenance, {"p1_manifest_sha256", "input_root_sha256", "date_cutoff"})
            or not isinstance(input_provenance["p1_manifest_sha256"], str)
            or not _SHA256.fullmatch(input_provenance["p1_manifest_sha256"])
            or input_provenance["input_root_sha256"] != observation["input_sha256"]
            or input_provenance["date_cutoff"] != observation["as_of"]
            or observation["as_of"] is None):
        raise ContractError("QSP_BINDING_INVALID")
    return build_signal_envelope(
        plugin_id=PLUGIN_ID,
        producer=producer,
        input_provenance=input_provenance,
        payload=observation,
    )
