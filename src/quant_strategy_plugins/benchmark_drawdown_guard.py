"""Price-only, research-only benchmark drawdown guard.

The guard deliberately emits a signal instead of an allocation.  A strategy
must explicitly opt in through the existing unified market-regime control and
bind the exact guard configuration to its own research candidate before the
signal can affect a portfolio.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .plugin_signal_utils import json_scalar, normalize_close, resolve_signal_date

SCHEMA_VERSION = "benchmark_drawdown_guard.v1"
PROFILE = "benchmark_drawdown_guard"

ROUTE_NO_ACTION = "no_action"
ROUTE_RISK_REDUCED = "risk_reduced"
ROUTE_RISK_OFF = "risk_off"
ROUTE_BLOCKED = "blocked"

ACTION_NO_ACTION = "no_action"
ACTION_DELEVER = "delever"
ACTION_DEFEND = "defend"
ACTION_BLOCKED = "blocked"


def _ratio(value: object, *, name: str, lower: float = 0.0, upper: float = 1.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite ratio")
    result = float(value)
    if not pd.notna(result) or not lower <= result <= upper:
        raise ValueError(f"{name} must be a finite ratio")
    return result


def _positive_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 2:
        raise ValueError(f"{name} must be an integer greater than one")
    return value


def _nonnegative_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _threshold(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a drawdown threshold")
    result = float(value)
    if not pd.notna(result) or not -1.0 < result < 0.0:
        raise ValueError(f"{name} must be a drawdown threshold")
    return result


def _blocked(*, as_of: str, benchmark_symbol: str, reason_code: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "profile": PROFILE,
        "as_of": as_of,
        "benchmark_symbol": benchmark_symbol,
        "canonical_route": ROUTE_BLOCKED,
        "suggested_action": ACTION_BLOCKED,
        "would_trade_if_enabled": False,
        "kill_switch_active": True,
        "leverage_scalar": 0.0,
        "risk_asset_scalar": 0.0,
        "reason_codes": (reason_code,),
        "data_quality": {"status": "PARKED", "reason_codes": (reason_code,)},
        "execution_controls": {
            "broker_order_allowed": False,
            "live_allocation_mutation_allowed": False,
            "strategy_opt_in_required": True,
        },
    }


def build_benchmark_drawdown_guard_signal(
    price_history,
    *,
    benchmark_symbol: str,
    as_of: str | None,
    drawdown_lookback_sessions: int,
    soft_drawdown_threshold: float,
    hard_drawdown_threshold: float,
    soft_risk_asset_scalar: float,
    hard_risk_asset_scalar: float,
    max_price_age_days: int,
) -> dict[str, Any]:
    """Build one causal, configured benchmark guard signal.

    No threshold, scalar, benchmark, or freshness policy has a hidden default.
    This prevents a caller from accidentally treating a research helper as an
    unstated, live-capable stop-loss policy.
    """
    symbol = str(benchmark_symbol or "").strip().upper()
    if not symbol:
        raise ValueError("benchmark_symbol is required")
    lookback = _positive_int(drawdown_lookback_sessions, name="drawdown_lookback_sessions")
    max_age = _nonnegative_int(max_price_age_days, name="max_price_age_days")
    soft_threshold = _threshold(soft_drawdown_threshold, name="soft_drawdown_threshold")
    hard_threshold = _threshold(hard_drawdown_threshold, name="hard_drawdown_threshold")
    if hard_threshold >= soft_threshold:
        raise ValueError("hard_drawdown_threshold must be below soft_drawdown_threshold")
    soft_scalar = _ratio(soft_risk_asset_scalar, name="soft_risk_asset_scalar")
    hard_scalar = _ratio(hard_risk_asset_scalar, name="hard_risk_asset_scalar")
    if hard_scalar > soft_scalar:
        raise ValueError("hard_risk_asset_scalar must not exceed soft_risk_asset_scalar")

    # A missing or malformed price payload must park the guard rather than
    # leave the enclosing strategy with an implicit "no action" result.
    # This is deliberately narrower than ``Exception``: programming bugs
    # should still be visible to CI instead of being disguised as data gaps.
    fallback_as_of = str(as_of or "unavailable").strip() or "unavailable"
    try:
        close = normalize_close(price_history)
        requested_date, signal_date = resolve_signal_date(close, as_of)
    except (KeyError, RuntimeError, TypeError, ValueError):
        return json_scalar(
            _blocked(
                as_of=fallback_as_of,
                benchmark_symbol=symbol,
                reason_code="benchmark_history_unavailable",
            )
        )
    signal_as_of = signal_date.date().isoformat()
    if symbol not in close.columns:
        return json_scalar(_blocked(as_of=signal_as_of, benchmark_symbol=symbol, reason_code="benchmark_missing"))
    price_age_days = int((requested_date - signal_date).days)
    if price_age_days > max_age:
        return json_scalar(_blocked(as_of=signal_as_of, benchmark_symbol=symbol, reason_code="benchmark_stale"))
    benchmark = pd.to_numeric(close[symbol], errors="coerce").loc[:signal_date].dropna()
    if len(benchmark) < lookback:
        return json_scalar(_blocked(as_of=signal_as_of, benchmark_symbol=symbol, reason_code="benchmark_history_incomplete"))
    window = benchmark.tail(lookback)
    current = float(window.iloc[-1])
    peak = float(window.max())
    if current <= 0.0 or peak <= 0.0:
        return json_scalar(_blocked(as_of=signal_as_of, benchmark_symbol=symbol, reason_code="benchmark_price_invalid"))
    drawdown = current / peak - 1.0

    route = ROUTE_NO_ACTION
    action = ACTION_NO_ACTION
    risk_asset_scalar = 1.0
    reason_codes: tuple[str, ...] = ()
    if drawdown <= hard_threshold:
        route = ROUTE_RISK_OFF
        action = ACTION_DEFEND
        risk_asset_scalar = hard_scalar
        reason_codes = ("benchmark_drawdown_hard",)
    elif drawdown <= soft_threshold:
        route = ROUTE_RISK_REDUCED
        action = ACTION_DELEVER
        risk_asset_scalar = soft_scalar
        reason_codes = ("benchmark_drawdown_soft",)
    return json_scalar(
        {
            "schema_version": SCHEMA_VERSION,
            "profile": PROFILE,
            "as_of": signal_as_of,
            "benchmark_symbol": symbol,
            "canonical_route": route,
            "suggested_action": action,
            "would_trade_if_enabled": route != ROUTE_NO_ACTION,
            "kill_switch_active": False,
            "leverage_scalar": risk_asset_scalar,
            "risk_asset_scalar": risk_asset_scalar,
            "reason_codes": reason_codes,
            "data_quality": {
                "status": "READY",
                "price_age_days": price_age_days,
                "lookback_sessions": lookback,
            },
            "metrics": {
                "rolling_drawdown": drawdown,
                "soft_drawdown_threshold": soft_threshold,
                "hard_drawdown_threshold": hard_threshold,
            },
            "execution_controls": {
                "broker_order_allowed": False,
                "live_allocation_mutation_allowed": False,
                "strategy_opt_in_required": True,
            },
        }
    )


__all__ = [
    "ACTION_BLOCKED",
    "ACTION_DEFEND",
    "ACTION_DELEVER",
    "ACTION_NO_ACTION",
    "PROFILE",
    "ROUTE_BLOCKED",
    "ROUTE_NO_ACTION",
    "ROUTE_RISK_OFF",
    "ROUTE_RISK_REDUCED",
    "SCHEMA_VERSION",
    "build_benchmark_drawdown_guard_signal",
]
