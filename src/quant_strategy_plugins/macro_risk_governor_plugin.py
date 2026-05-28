from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from .artifacts import write_json
from .plugin_signal_utils import flatten_for_csv, json_scalar, normalize_close, resolve_signal_date
from .russell_1000_multi_factor_defensive_snapshot import read_table
from .yfinance_prices import download_price_history

SCHEMA_VERSION = "macro_risk_governor.v1"
SHADOW_MODE = "shadow"
MACRO_RISK_GOVERNOR_PROFILE = "macro_risk_governor"
DEFAULT_BENCHMARK_SYMBOL = "QQQ"
DEFAULT_ATTACK_SYMBOL = "TQQQ"
DEFAULT_VIX_SYMBOLS = ("VIX", "^VIX", "VIXCLS")
DEFAULT_CREDIT_PAIRS = (("HYG", "IEF"), ("LQD", "IEF"))
DEFAULT_OUTPUT_DIR = "data/output/macro_risk_governor"
DEFAULT_MAX_PRICE_AGE_DAYS = 4
DEFAULT_MAX_EXTERNAL_CONTEXT_AGE_DAYS = 10

ROUTE_NO_ACTION = "no_action"
ROUTE_WATCH = "watch"
ROUTE_DELEVER = "delever"
ROUTE_CRISIS = "crisis"

ACTION_NO_ACTION = "no_action"
ACTION_WATCH_ONLY = "watch_only"
ACTION_DELEVER = "delever"
ACTION_DEFEND = "defend"
ACTION_BLOCKED = "blocked"


def _as_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not pd.notna(result):
        return None
    return result


def _ratio_at(series: pd.Series, date: pd.Timestamp, lookback: int) -> float | None:
    values = pd.to_numeric(series, errors="coerce").sort_index()
    if date not in values.index:
        values = values.reindex(values.index.union(pd.DatetimeIndex([date]))).sort_index().ffill()
    current = _as_float(values.loc[date]) if date in values.index else None
    shifted = values.shift(int(lookback))
    previous = _as_float(shifted.loc[date]) if date in shifted.index else None
    if current is None or previous is None or previous <= 0.0:
        return None
    return current / previous - 1.0


def _rolling_drawdown_at(series: pd.Series, date: pd.Timestamp, lookback: int) -> float | None:
    values = pd.to_numeric(series, errors="coerce").sort_index()
    high = values.rolling(int(lookback), min_periods=max(20, min(int(lookback), 63))).max()
    if date not in values.index:
        values = values.reindex(values.index.union(pd.DatetimeIndex([date]))).sort_index().ffill()
        high = high.reindex(high.index.union(pd.DatetimeIndex([date]))).sort_index().ffill()
    current = _as_float(values.loc[date]) if date in values.index else None
    peak = _as_float(high.loc[date]) if date in high.index else None
    if current is None or peak is None or peak <= 0.0:
        return None
    return current / peak - 1.0


def _realized_volatility_at(series: pd.Series, date: pd.Timestamp, window: int) -> float | None:
    returns = pd.to_numeric(series, errors="coerce").pct_change(fill_method=None)
    volatility = returns.rolling(int(window), min_periods=int(window)).std()
    if date not in volatility.index:
        volatility = volatility.reindex(volatility.index.union(pd.DatetimeIndex([date]))).sort_index().ffill()
    value = _as_float(volatility.loc[date]) if date in volatility.index else None
    return None if value is None else float(value * (252 ** 0.5))


def _latest_external_row(external_context: pd.DataFrame | None, signal_date: pd.Timestamp) -> tuple[pd.Series, pd.Timestamp | None]:
    if external_context is None or external_context.empty or "as_of" not in external_context.columns:
        return pd.Series(dtype=object), None
    frame = pd.DataFrame(external_context).copy()
    frame["as_of"] = pd.to_datetime(frame["as_of"], errors="coerce").dt.tz_localize(None).dt.normalize()
    frame = frame.dropna(subset=["as_of"]).sort_values("as_of")
    frame = frame.loc[frame["as_of"] <= signal_date]
    if frame.empty:
        return pd.Series(dtype=object), None
    row = frame.iloc[-1]
    return row, pd.Timestamp(row["as_of"]).normalize()


def _external_float(row: pd.Series, *names: str) -> float | None:
    if row.empty:
        return None
    normalized = {str(key).strip().lower(): key for key in row.index}
    for name in names:
        key = normalized.get(str(name).strip().lower())
        if key is not None:
            value = _as_float(row.get(key))
            if value is not None:
                return value
    return None


def _external_delta(
    external_context: pd.DataFrame | None,
    signal_date: pd.Timestamp,
    names: Sequence[str],
    lookback: int,
) -> float | None:
    if external_context is None or external_context.empty or "as_of" not in external_context.columns:
        return None
    frame = pd.DataFrame(external_context).copy()
    frame["as_of"] = pd.to_datetime(frame["as_of"], errors="coerce").dt.tz_localize(None).dt.normalize()
    frame = frame.dropna(subset=["as_of"]).sort_values("as_of").set_index("as_of")
    if frame.empty:
        return None
    normalized = {str(column).strip().lower(): column for column in frame.columns}
    column = None
    for name in names:
        column = normalized.get(str(name).strip().lower())
        if column is not None:
            break
    if column is None:
        return None
    values = pd.to_numeric(frame[column], errors="coerce")
    values = values.reindex(values.index.union(pd.DatetimeIndex([signal_date]))).sort_index().ffill()
    if signal_date not in values.index:
        return None
    current = _as_float(values.loc[signal_date])
    previous = _as_float(values.shift(int(lookback)).loc[signal_date])
    if current is None or previous is None:
        return None
    return current - previous


def _first_available_symbol(close: pd.DataFrame, symbols: Sequence[str]) -> str | None:
    for symbol in symbols:
        normalized = str(symbol).strip().upper()
        if normalized in close.columns:
            return normalized
    return None


def _pair_relative_return(
    close: pd.DataFrame,
    numerator: str,
    denominator: str,
    signal_date: pd.Timestamp,
    lookback: int,
) -> float | None:
    numerator = str(numerator).strip().upper()
    denominator = str(denominator).strip().upper()
    if numerator not in close.columns or denominator not in close.columns:
        return None
    ratio = pd.to_numeric(close[numerator], errors="coerce") / pd.to_numeric(close[denominator], errors="coerce")
    return _ratio_at(ratio, signal_date, lookback)


def _add_check(
    checks: dict[str, dict[str, Any]],
    name: str,
    active: bool,
    *,
    weight: float,
    value: float | None,
    threshold: float | None,
    actionable: bool = True,
) -> None:
    checks[name] = {
        "active": bool(active),
        "weight": float(weight),
        "value": value,
        "threshold": threshold,
        "actionable": bool(actionable),
    }


def _score_checks(checks: Mapping[str, Mapping[str, Any]], *, actionable_only: bool) -> float:
    score = 0.0
    for check in checks.values():
        if actionable_only and not bool(check.get("actionable", True)):
            continue
        if bool(check.get("active", False)):
            score += float(check.get("weight", 0.0) or 0.0)
    return float(score)


def _build_data_quality(
    *,
    kill_reasons: Sequence[str],
    benchmark_price_available: bool,
    price_age_days: int,
    max_price_age_days: int,
    vix_available: bool,
    credit_context_available: bool,
    external_as_of: pd.Timestamp | None,
    external_age_days: int | None,
    max_external_context_age_days: int,
) -> dict[str, Any]:
    external_context_fresh = external_as_of is None or (
        external_age_days is not None and external_age_days <= int(max_external_context_age_days)
    )
    checks = {
        "benchmark_price_available": bool(benchmark_price_available),
        "price_data_fresh": int(price_age_days) <= int(max_price_age_days),
        "vix_available": bool(vix_available),
        "credit_context_available": bool(credit_context_available),
        "external_context_fresh_if_present": bool(external_context_fresh),
        "kill_switch_clear": not bool(kill_reasons),
    }
    warnings = list(kill_reasons)
    if not vix_available:
        warnings.append("vix price or external context unavailable")
    if not credit_context_available:
        warnings.append("credit pair context unavailable")
    if not external_context_fresh:
        warnings.append("external context stale")
    score = sum(1.0 for value in checks.values() if value) / float(len(checks))
    if kill_reasons:
        score = min(score, 0.5)
    return {
        "schema_version": "deterministic_data_quality.v1",
        "quality_score": round(float(score), 4),
        "checks": checks,
        "warnings": warnings,
    }


def build_macro_risk_governor_signal(
    price_history,
    *,
    external_context: pd.DataFrame | None = None,
    as_of: str | None = None,
    benchmark_symbol: str = DEFAULT_BENCHMARK_SYMBOL,
    attack_symbol: str = DEFAULT_ATTACK_SYMBOL,
    vix_symbols: Sequence[str] = DEFAULT_VIX_SYMBOLS,
    credit_pairs: Sequence[tuple[str, str]] = DEFAULT_CREDIT_PAIRS,
    max_price_age_days: int = DEFAULT_MAX_PRICE_AGE_DAYS,
    max_external_context_age_days: int = DEFAULT_MAX_EXTERNAL_CONTEXT_AGE_DAYS,
    ma_days: int = 200,
    benchmark_drawdown_watch: float = -0.10,
    benchmark_drawdown_crisis: float = -0.18,
    realized_vol_window: int = 10,
    realized_vol_threshold: float = 0.30,
    realized_vol_requires_confirmation: bool = True,
    vix_watch_level: float = 28.0,
    vix_crisis_level: float = 35.0,
    vix_spike_lookback_days: int = 5,
    vix_spike_threshold: float = 0.25,
    credit_relative_lookback_days: int = 21,
    credit_relative_threshold: float = -0.04,
    hy_oas_watch_level: float = 5.0,
    hy_oas_delta_lookback_days: int = 63,
    hy_oas_delta_threshold: float = 1.0,
    financial_stress_watch_level: float = 1.0,
    pizza_index_watch_level: float = 2.0,
    fear_greed_extreme_fear_level: float = 25.0,
    put_call_watch_level: float = 1.20,
    safe_haven_demand_watch_level: float = 1.0,
    watch_score_threshold: float = 3.0,
    delever_score_threshold: float = 5.0,
    crisis_score_threshold: float = 7.0,
    delever_leverage_scalar: float = 0.0,
    delever_risk_asset_scalar: float = 0.0,
    crisis_leverage_scalar: float = 0.0,
    crisis_risk_asset_scalar: float = 0.0,
) -> dict[str, Any]:
    close = normalize_close(price_history)
    benchmark_symbol = str(benchmark_symbol or DEFAULT_BENCHMARK_SYMBOL).strip().upper()
    attack_symbol = str(attack_symbol or DEFAULT_ATTACK_SYMBOL).strip().upper()
    requested_date, signal_date = resolve_signal_date(close, as_of)
    signal_iso = signal_date.date().isoformat()
    latest_price_date = pd.Timestamp(close.index.max()).normalize()
    price_age_days = int((requested_date - signal_date).days)

    external_row, external_as_of = _latest_external_row(external_context, signal_date)
    external_age_days = int((signal_date - external_as_of).days) if external_as_of is not None else None

    kill_reasons: list[str] = []
    if benchmark_symbol not in close.columns:
        kill_reasons.append(f"missing benchmark price data: {benchmark_symbol}")
    if price_age_days > int(max_price_age_days):
        kill_reasons.append(
            f"price data stale: signal_as_of={signal_iso}, requested_as_of={requested_date.date().isoformat()}"
        )
    if external_age_days is not None and external_age_days > int(max_external_context_age_days):
        kill_reasons.append(f"external context stale: external_context_as_of={external_as_of.date().isoformat()}")

    checks: dict[str, dict[str, Any]] = {}
    evidence: dict[str, Any] = {
        "benchmark_symbol": benchmark_symbol,
        "attack_symbol": attack_symbol,
        "vix_symbol": None,
        "credit_pairs": [f"{numerator}:{denominator}" for numerator, denominator in credit_pairs],
        "metrics": {},
    }

    if benchmark_symbol in close.columns:
        benchmark = pd.to_numeric(close[benchmark_symbol], errors="coerce")
        benchmark_price = _as_float(benchmark.loc[signal_date])
        benchmark_ma = _as_float(benchmark.rolling(int(ma_days), min_periods=min(int(ma_days), 120)).mean().loc[signal_date])
        drawdown_63d = _rolling_drawdown_at(benchmark, signal_date, 63)
        drawdown_252d = _rolling_drawdown_at(benchmark, signal_date, 252)
        realized_vol = _realized_volatility_at(benchmark, signal_date, realized_vol_window)
        below_ma = benchmark_price is not None and benchmark_ma is not None and benchmark_price < benchmark_ma
        _add_check(checks, "benchmark_below_ma", below_ma, weight=2.0, value=benchmark_price, threshold=benchmark_ma)
        _add_check(
            checks,
            "benchmark_drawdown_watch",
            drawdown_63d is not None and drawdown_63d <= float(benchmark_drawdown_watch),
            weight=1.0,
            value=drawdown_63d,
            threshold=float(benchmark_drawdown_watch),
        )
        _add_check(
            checks,
            "benchmark_drawdown_crisis",
            drawdown_252d is not None and drawdown_252d <= float(benchmark_drawdown_crisis),
            weight=2.0,
            value=drawdown_252d,
            threshold=float(benchmark_drawdown_crisis),
        )
        _add_check(
            checks,
            "benchmark_realized_volatility_high",
            realized_vol is not None and realized_vol >= float(realized_vol_threshold),
            weight=1.0,
            value=realized_vol,
            threshold=float(realized_vol_threshold),
        )
        evidence["metrics"].update(
            {
                "benchmark_price": benchmark_price,
                "benchmark_ma": benchmark_ma,
                "benchmark_drawdown_63d": drawdown_63d,
                "benchmark_drawdown_252d": drawdown_252d,
                "benchmark_realized_volatility": realized_vol,
            }
        )

    vix_symbol = _first_available_symbol(close, vix_symbols)
    vix_level = None
    vix_spike = None
    if vix_symbol is not None:
        vix = pd.to_numeric(close[vix_symbol], errors="coerce")
        vix_level = _as_float(vix.loc[signal_date])
        vix_spike = _ratio_at(vix, signal_date, int(vix_spike_lookback_days))
        evidence["vix_symbol"] = vix_symbol
    else:
        vix_level = _external_float(external_row, "vix", "vixcls", "vix_level")
        vix_spike = _external_float(external_row, "vix_5d_change", "vix_spike_5d")
        if vix_level is not None:
            evidence["vix_symbol"] = "external_context"
    _add_check(
        checks,
        "vix_watch_level",
        vix_level is not None and vix_level >= float(vix_watch_level),
        weight=1.0,
        value=vix_level,
        threshold=float(vix_watch_level),
    )
    _add_check(
        checks,
        "vix_crisis_level",
        vix_level is not None and vix_level >= float(vix_crisis_level),
        weight=1.0,
        value=vix_level,
        threshold=float(vix_crisis_level),
    )
    _add_check(
        checks,
        "vix_spike",
        vix_spike is not None and vix_spike >= float(vix_spike_threshold),
        weight=1.0,
        value=vix_spike,
        threshold=float(vix_spike_threshold),
    )
    evidence["metrics"].update({"vix_level": vix_level, "vix_spike": vix_spike})

    credit_returns: dict[str, float | None] = {}
    credit_context_available = False
    credit_pair_stress = False
    for numerator, denominator in credit_pairs:
        value = _pair_relative_return(close, numerator, denominator, signal_date, int(credit_relative_lookback_days))
        key = f"{str(numerator).strip().upper()}:{str(denominator).strip().upper()}"
        credit_returns[key] = value
        if value is not None:
            credit_context_available = True
            credit_pair_stress = credit_pair_stress or value <= float(credit_relative_threshold)
    _add_check(
        checks,
        "credit_pair_stress",
        credit_pair_stress,
        weight=2.0,
        value=min((value for value in credit_returns.values() if value is not None), default=None),
        threshold=float(credit_relative_threshold),
    )
    evidence["metrics"]["credit_pair_relative_returns"] = credit_returns

    hy_oas = _external_float(external_row, "hy_oas", "high_yield_oas", "bamlh0a0hym2")
    hy_oas_delta = _external_float(external_row, "hy_oas_delta_63d", "high_yield_oas_delta_63d")
    if hy_oas_delta is None:
        hy_oas_delta = _external_delta(
            external_context,
            signal_date,
            ("hy_oas", "high_yield_oas", "bamlh0a0hym2"),
            int(hy_oas_delta_lookback_days),
        )
    _add_check(
        checks,
        "hy_oas_watch_level",
        hy_oas is not None and hy_oas >= float(hy_oas_watch_level),
        weight=2.0,
        value=hy_oas,
        threshold=float(hy_oas_watch_level),
    )
    _add_check(
        checks,
        "hy_oas_widening",
        hy_oas_delta is not None and hy_oas_delta >= float(hy_oas_delta_threshold),
        weight=1.0,
        value=hy_oas_delta,
        threshold=float(hy_oas_delta_threshold),
    )
    financial_stress = _external_float(external_row, "stlfsi", "stlfsi4", "nfci", "anfci", "financial_stress")
    _add_check(
        checks,
        "financial_stress_index_high",
        financial_stress is not None and financial_stress >= float(financial_stress_watch_level),
        weight=2.0,
        value=financial_stress,
        threshold=float(financial_stress_watch_level),
    )
    pizza_index = _external_float(
        external_row,
        "pentagon_pizza_index",
        "pizza_index",
        "pizza_activity_index",
        "osint_pizza_index",
    )
    _add_check(
        checks,
        "pentagon_pizza_watch",
        pizza_index is not None and pizza_index >= float(pizza_index_watch_level),
        weight=1.0,
        value=pizza_index,
        threshold=float(pizza_index_watch_level),
        actionable=False,
    )
    fear_greed_index = _external_float(
        external_row,
        "fear_greed_index",
        "fear_and_greed_index",
        "cnn_fear_greed_index",
        "cnn_fear_and_greed_index",
    )
    _add_check(
        checks,
        "fear_greed_extreme_fear_watch",
        fear_greed_index is not None and fear_greed_index <= float(fear_greed_extreme_fear_level),
        weight=1.0,
        value=fear_greed_index,
        threshold=float(fear_greed_extreme_fear_level),
        actionable=False,
    )
    put_call_ratio = _external_float(
        external_row,
        "put_call_ratio",
        "equity_put_call_ratio",
        "cboe_put_call_ratio",
        "put_call",
    )
    _add_check(
        checks,
        "put_call_stress_watch",
        put_call_ratio is not None and put_call_ratio >= float(put_call_watch_level),
        weight=1.0,
        value=put_call_ratio,
        threshold=float(put_call_watch_level),
        actionable=False,
    )
    safe_haven_demand = _external_float(
        external_row,
        "safe_haven_demand",
        "safe_haven_demand_index",
        "safe_haven_demand_zscore",
    )
    _add_check(
        checks,
        "safe_haven_demand_watch",
        safe_haven_demand is not None and safe_haven_demand >= float(safe_haven_demand_watch_level),
        weight=1.0,
        value=safe_haven_demand,
        threshold=float(safe_haven_demand_watch_level),
        actionable=False,
    )
    realized_vol_confirmed_for_action = None
    realized_vol_check = checks.get("benchmark_realized_volatility_high")
    if realized_vol_check is not None:
        volatility_active = bool(realized_vol_check.get("active", False))
        if volatility_active:
            confirmation_checks = (
                "vix_watch_level",
                "vix_crisis_level",
                "vix_spike",
                "credit_pair_stress",
                "hy_oas_watch_level",
                "hy_oas_widening",
                "financial_stress_index_high",
            )
            realized_vol_confirmed_for_action = any(
                bool(checks.get(name, {}).get("active", False)) for name in confirmation_checks
            )
            if bool(realized_vol_requires_confirmation) and not realized_vol_confirmed_for_action:
                realized_vol_check["actionable"] = False
                realized_vol_check["suppression_reason"] = "missing_volatility_stress_confirmation"
        realized_vol_check["confirmation_required"] = bool(realized_vol_requires_confirmation)
        realized_vol_check["confirmed_for_action"] = realized_vol_confirmed_for_action
    evidence["metrics"].update(
        {
            "hy_oas": hy_oas,
            "hy_oas_delta_63d": hy_oas_delta,
            "financial_stress": financial_stress,
            "pentagon_pizza_index": pizza_index,
            "fear_greed_index": fear_greed_index,
            "put_call_ratio": put_call_ratio,
            "safe_haven_demand": safe_haven_demand,
            "benchmark_realized_volatility_requires_confirmation": bool(realized_vol_requires_confirmation),
            "benchmark_realized_volatility_confirmed_for_action": realized_vol_confirmed_for_action,
        }
    )

    actionable_score = _score_checks(checks, actionable_only=True)
    total_score = _score_checks(checks, actionable_only=False)
    reason_codes = tuple(name for name, check in checks.items() if bool(check.get("active", False)))

    canonical_route = ROUTE_NO_ACTION
    suggested_action = ACTION_NO_ACTION
    leverage_scalar = 1.0
    risk_asset_scalar = 1.0
    would_trade_if_enabled = False
    if actionable_score >= float(crisis_score_threshold):
        canonical_route = ROUTE_CRISIS
        suggested_action = ACTION_DEFEND
        leverage_scalar = float(crisis_leverage_scalar)
        risk_asset_scalar = float(crisis_risk_asset_scalar)
        would_trade_if_enabled = True
    elif actionable_score >= float(delever_score_threshold):
        canonical_route = ROUTE_DELEVER
        suggested_action = ACTION_DELEVER
        leverage_scalar = float(delever_leverage_scalar)
        risk_asset_scalar = float(delever_risk_asset_scalar)
        would_trade_if_enabled = True
    elif total_score >= float(watch_score_threshold):
        canonical_route = ROUTE_WATCH
        suggested_action = ACTION_WATCH_ONLY

    kill_switch_active = bool(kill_reasons)
    if kill_switch_active:
        canonical_route = ROUTE_NO_ACTION
        suggested_action = ACTION_BLOCKED
        leverage_scalar = 1.0
        risk_asset_scalar = 1.0
        would_trade_if_enabled = False

    data_freshness = {
        "requested_as_of": requested_date.date().isoformat(),
        "signal_as_of": signal_iso,
        "prices_as_of": latest_price_date.date().isoformat(),
        "price_age_days": price_age_days,
        "max_price_age_days": int(max_price_age_days),
        "external_context_as_of": external_as_of.date().isoformat() if external_as_of is not None else None,
        "external_context_age_days": external_age_days,
        "max_external_context_age_days": int(max_external_context_age_days),
    }
    data_quality = _build_data_quality(
        kill_reasons=kill_reasons,
        benchmark_price_available=benchmark_symbol in close.columns,
        price_age_days=price_age_days,
        max_price_age_days=int(max_price_age_days),
        vix_available=vix_level is not None,
        credit_context_available=credit_context_available,
        external_as_of=external_as_of,
        external_age_days=external_age_days,
        max_external_context_age_days=int(max_external_context_age_days),
    )
    payload = {
        "as_of": signal_iso,
        "mode": SHADOW_MODE,
        "schema_version": SCHEMA_VERSION,
        "profile": MACRO_RISK_GOVERNOR_PROFILE,
        "canonical_route": canonical_route,
        "suggested_action": suggested_action,
        "leverage_scalar": max(0.0, min(1.0, float(leverage_scalar))),
        "risk_asset_scalar": max(0.0, min(1.0, float(risk_asset_scalar))),
        "would_trade_if_enabled": would_trade_if_enabled,
        "actionable_score": round(float(actionable_score), 4),
        "total_score": round(float(total_score), 4),
        "reason_codes": reason_codes,
        "checks": checks,
        "kill_switch_active": kill_switch_active,
        "kill_switch_reason": "; ".join(kill_reasons),
        "data_freshness": data_freshness,
        "data_quality": data_quality,
        "evidence": evidence,
        "audit_summary": {
            "route_source": "deterministic_macro_risk_governor",
            "final_route": canonical_route,
            "actionable_score": round(float(actionable_score), 4),
            "total_score": round(float(total_score), 4),
            "reason_codes": reason_codes,
            "note": "OSINT-only fields are watch evidence and do not contribute to actionable_score.",
        },
        "execution_controls": {
            "capital_impact": "strategy_opt_in",
            "broker_order_allowed": False,
            "live_allocation_mutation_allowed": False,
            "log_namespace": MACRO_RISK_GOVERNOR_PROFILE,
            "notification_profile": "shadow_only",
            "intended_strategy_role": "macro_deleveraging_governor",
            "defensive_destination": "unlevered_or_cash_like",
            "strategy_runtime_metadata_allowed": True,
            "ai_audit_shadow_only": False,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return json_scalar(payload)


def write_macro_risk_governor_outputs(payload: Mapping[str, Any], output_dir: str | Path) -> dict[str, Path]:
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
        "leverage_scalar": payload.get("leverage_scalar"),
        "risk_asset_scalar": payload.get("risk_asset_scalar"),
        "actionable_score": payload.get("actionable_score"),
        "total_score": payload.get("total_score"),
        **flatten_for_csv(payload.get("data_freshness", {})),
        **flatten_for_csv(payload.get("data_quality", {})),
        **flatten_for_csv(payload.get("evidence", {})),
        **flatten_for_csv(payload.get("audit_summary", {})),
    }
    pd.DataFrame([evidence_payload]).to_csv(evidence_csv_path, index=False)
    return {
        "latest_signal": latest_path,
        "signal_json": dated_json_path,
        "signal_csv": dated_csv_path,
        "evidence_csv": evidence_csv_path,
    }


def _parse_str_tuple(value: str | Sequence[str]) -> tuple[str, ...]:
    values = value.split(",") if isinstance(value, str) else list(value)
    return tuple(dict.fromkeys(str(item).strip().upper() for item in values if str(item).strip()))


def _parse_credit_pairs(value: str | Sequence[str]) -> tuple[tuple[str, str], ...]:
    pairs: list[tuple[str, str]] = []
    for item in _parse_str_tuple(value):
        parts = [part.strip().upper() for part in item.replace("/", ":").split(":")]
        if len(parts) != 2 or not all(parts):
            raise ValueError(f"credit pair must use NUMERATOR:DENOMINATOR syntax: {item!r}")
        pair = (parts[0], parts[1])
        if pair not in pairs:
            pairs.append(pair)
    return tuple(pairs)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build deterministic macro risk governor shadow signal.")
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--prices", help="Existing long price-history CSV with symbol/as_of/close columns")
    input_group.add_argument("--download", action="store_true", help="Download adjusted price history through yfinance")
    parser.add_argument("--external-context", default=None)
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--price-start", default="2010-01-01")
    parser.add_argument("--price-end", default=None)
    parser.add_argument("--download-proxy", default=None)
    parser.add_argument("--benchmark-symbol", default=DEFAULT_BENCHMARK_SYMBOL)
    parser.add_argument("--attack-symbol", default=DEFAULT_ATTACK_SYMBOL)
    parser.add_argument("--vix-symbols", default=",".join(DEFAULT_VIX_SYMBOLS))
    parser.add_argument(
        "--credit-pairs",
        default=",".join(f"{numerator}:{denominator}" for numerator, denominator in DEFAULT_CREDIT_PAIRS),
    )
    parser.add_argument("--max-price-age-days", type=int, default=DEFAULT_MAX_PRICE_AGE_DAYS)
    parser.add_argument("--max-external-context-age-days", type=int, default=DEFAULT_MAX_EXTERNAL_CONTEXT_AGE_DAYS)
    parser.add_argument("--realized-vol-threshold", type=float, default=0.30)
    parser.add_argument(
        "--realized-vol-requires-confirmation",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Require VIX, credit, or financial-stress confirmation before realized volatility contributes to actionable score.",
    )
    parser.add_argument("--watch-score-threshold", type=float, default=3.0)
    parser.add_argument("--delever-score-threshold", type=float, default=5.0)
    parser.add_argument("--crisis-score-threshold", type=float, default=7.0)
    parser.add_argument("--delever-leverage-scalar", type=float, default=0.0)
    parser.add_argument("--delever-risk-asset-scalar", type=float, default=0.0)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    vix_symbols = _parse_str_tuple(args.vix_symbols)
    credit_pairs = _parse_credit_pairs(args.credit_pairs)
    if args.download:
        symbols = [args.benchmark_symbol, args.attack_symbol, *vix_symbols]
        for numerator, denominator in credit_pairs:
            symbols.extend([numerator, denominator])
        symbols = list(dict.fromkeys(str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()))
        price_history = download_price_history(
            symbols,
            start=args.price_start,
            end=args.price_end,
            proxy=args.download_proxy,
        )
    else:
        price_history = read_table(args.prices)
    external_context = read_table(args.external_context) if args.external_context else None
    payload = build_macro_risk_governor_signal(
        price_history,
        external_context=external_context,
        as_of=args.as_of,
        benchmark_symbol=args.benchmark_symbol,
        attack_symbol=args.attack_symbol,
        vix_symbols=vix_symbols,
        credit_pairs=credit_pairs,
        max_price_age_days=args.max_price_age_days,
        max_external_context_age_days=args.max_external_context_age_days,
        realized_vol_threshold=args.realized_vol_threshold,
        realized_vol_requires_confirmation=args.realized_vol_requires_confirmation,
        watch_score_threshold=args.watch_score_threshold,
        delever_score_threshold=args.delever_score_threshold,
        crisis_score_threshold=args.crisis_score_threshold,
        delever_leverage_scalar=args.delever_leverage_scalar,
        delever_risk_asset_scalar=args.delever_risk_asset_scalar,
    )
    paths = write_macro_risk_governor_outputs(payload, args.output_dir)
    print(f"wrote macro risk governor signal -> {paths['latest_signal']}")
    print(
        f"route={payload['canonical_route']} action={payload['suggested_action']} "
        f"score={payload['actionable_score']}/{payload['total_score']}"
    )
    return 0


__all__ = [
    "MACRO_RISK_GOVERNOR_PROFILE",
    "ROUTE_CRISIS",
    "ROUTE_DELEVER",
    "ROUTE_NO_ACTION",
    "ROUTE_WATCH",
    "SCHEMA_VERSION",
    "SHADOW_MODE",
    "build_macro_risk_governor_signal",
    "main",
    "write_macro_risk_governor_outputs",
]
