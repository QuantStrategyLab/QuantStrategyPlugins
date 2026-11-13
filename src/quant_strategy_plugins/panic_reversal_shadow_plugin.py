from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from .artifacts import write_json
from .plugin_signal_utils import flatten_for_csv, json_scalar, normalize_close, resolve_signal_date
from .russell_1000_multi_factor_defensive_snapshot import read_table
from .taco_panic_rebound_overlay_compare import (
    DEFAULT_ATTACK_SYMBOL,
    DEFAULT_BENCHMARK_SYMBOL,
    DEFAULT_PRICE_CRISIS_GUARD_DRAWDOWN,
    DEFAULT_PRICE_CRISIS_GUARD_MA_DAYS,
    DEFAULT_PRICE_CRISIS_GUARD_MA_SLOPE_DAYS,
    build_price_crisis_guard_signal,
)
from .yfinance_prices import download_price_history

SCHEMA_VERSION = "panic_reversal_shadow.v1"
SHADOW_MODE = "shadow"
PANIC_REVERSAL_PROFILE = "panic_reversal_shadow"
ROUTE_PANIC_REVERSAL = "panic_reversal"
ROUTE_WATCH = "watch"
ROUTE_NO_ACTION = "no_action"
ACTION_NOTIFY_MANUAL_REVIEW = "notify_manual_review"
ACTION_WATCH_ONLY = "watch_only"
ACTION_NO_ACTION = "no_action"

DEFAULT_OUTPUT_DIR = "data/output/panic_reversal_shadow"
DEFAULT_START_DATE = "2010-01-01"
DEFAULT_MAX_PRICE_AGE_DAYS = 4
DEFAULT_MAX_VOL_AGE_DAYS = 4
DEFAULT_VIX_SYMBOLS = ("VIX", "^VIX", "VIXCLS")
DEFAULT_VIX3M_SYMBOLS = ("VIX3M", "^VIX3M", "VXV", "^VXV", "VXVCLS")
DEFAULT_VIX_HIGH_LOOKBACK_DAYS = 5
DEFAULT_MIN_VIX_HIGH = 50.0
DEFAULT_MIN_VIX_PULLBACK_FROM_HIGH = 0.10
DEFAULT_REQUIRE_VIX_TERM_STRUCTURE = True
DEFAULT_MIN_VIX_VIX3M_RATIO = 1.0
DEFAULT_PRICE_CONFIRMATION_LOOKBACK_DAYS = 5
DEFAULT_MIN_BENCHMARK_REBOUND_FROM_LOW = 0.015
DEFAULT_MIN_ATTACK_REBOUND_FROM_LOW = 0.04
DEFAULT_MIN_BENCHMARK_3D_RETURN = 0.0
DEFAULT_EVENT_STUDY_HORIZONS = (21, 42, 63)


def _as_str_tuple(raw: str | Sequence[str] | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    values = raw.split(",") if isinstance(raw, str) else list(raw)
    return tuple(str(value).strip().upper() for value in values if str(value).strip())


def _normalize_external_context(external_context: pd.DataFrame | None) -> pd.DataFrame:
    if external_context is None:
        return pd.DataFrame()
    frame = pd.DataFrame(external_context).copy()
    if frame.empty:
        return pd.DataFrame()
    if "as_of" in frame.columns:
        frame["as_of"] = pd.to_datetime(frame["as_of"], errors="coerce").dt.tz_localize(None).dt.normalize()
        frame = frame.dropna(subset=["as_of"]).drop_duplicates("as_of", keep="last").set_index("as_of")
    else:
        frame.index = pd.to_datetime(frame.index, errors="coerce").tz_localize(None).normalize()
        frame = frame.loc[frame.index.notna()]
    frame.columns = frame.columns.astype(str).str.lower().str.strip()
    return frame.sort_index()


def _metric_series(
    close: pd.DataFrame,
    external_context: pd.DataFrame,
    *,
    price_symbols: Sequence[str],
    external_columns: Sequence[str],
) -> tuple[pd.Series, str]:
    for symbol in _as_str_tuple(price_symbols):
        if symbol in close.columns:
            values = pd.to_numeric(close[symbol], errors="coerce").dropna()
            values.name = symbol
            return values, f"price:{symbol}"
    for column in tuple(str(item).strip().lower() for item in external_columns if str(item).strip()):
        if column in external_context.columns:
            values = pd.to_numeric(external_context[column], errors="coerce").dropna()
            values.name = column
            return values, f"external_context:{column}"
    return pd.Series(dtype=float), ""


def _value_on_or_before(series: pd.Series, date: pd.Timestamp) -> tuple[float | None, pd.Timestamp | None, int | None]:
    clean = pd.to_numeric(series, errors="coerce").dropna().sort_index()
    clean.index = pd.to_datetime(clean.index, errors="coerce").tz_localize(None).normalize()
    clean = clean.loc[clean.index.notna()]
    candidates = clean.loc[clean.index <= date]
    if candidates.empty:
        return None, None, None
    value_date = pd.Timestamp(candidates.index[-1]).normalize()
    return float(candidates.iloc[-1]), value_date, int((date - value_date).days)


def _last_observations(series: pd.Series, date: pd.Timestamp, count: int) -> pd.Series:
    clean = pd.to_numeric(series, errors="coerce").dropna().sort_index()
    clean.index = pd.to_datetime(clean.index, errors="coerce").tz_localize(None).normalize()
    clean = clean.loc[clean.index.notna()]
    return clean.loc[clean.index <= date].tail(max(1, int(count)))


def _recent_price_confirmation(
    close: pd.DataFrame,
    *,
    signal_date: pd.Timestamp,
    benchmark_symbol: str,
    attack_symbol: str,
    lookback_days: int,
) -> dict[str, float | int | str | None]:
    index = pd.DatetimeIndex(close.index).sort_values()
    if signal_date not in index:
        return {"reason": "signal date missing from price index"}
    signal_pos = int(index.get_loc(signal_date))
    lookback_start = max(0, signal_pos - max(1, int(lookback_days)) + 1)
    window_index = index[lookback_start : signal_pos + 1]
    benchmark = pd.to_numeric(close[benchmark_symbol].reindex(window_index), errors="coerce")
    attack = pd.to_numeric(close[attack_symbol].reindex(window_index), errors="coerce")

    benchmark_close = float(benchmark.iloc[-1]) if benchmark.notna().any() else float("nan")
    attack_close = float(attack.iloc[-1]) if attack.notna().any() else float("nan")
    benchmark_low = float(benchmark.min()) if benchmark.notna().any() else float("nan")
    attack_low = float(attack.min()) if attack.notna().any() else float("nan")
    benchmark_rebound = benchmark_close / benchmark_low - 1.0 if benchmark_low > 0 else float("nan")
    attack_rebound = attack_close / attack_low - 1.0 if attack_low > 0 else float("nan")
    if signal_pos >= 3:
        benchmark_3d_base = float(close[benchmark_symbol].iloc[signal_pos - 3])
        benchmark_3d_return = benchmark_close / benchmark_3d_base - 1.0 if benchmark_3d_base > 0 else float("nan")
    else:
        benchmark_3d_return = float("nan")
    return {
        "lookback_days": int(lookback_days),
        "benchmark_symbol": benchmark_symbol,
        "attack_symbol": attack_symbol,
        "benchmark_rebound_from_recent_low": benchmark_rebound,
        "attack_rebound_from_recent_low": attack_rebound,
        "benchmark_3d_return": benchmark_3d_return,
        "benchmark_recent_low": benchmark_low,
        "attack_recent_low": attack_low,
    }


def _score_checks(checks: Mapping[str, bool]) -> float:
    if not checks:
        return 0.0
    return round(sum(1.0 for value in checks.values() if bool(value)) / float(len(checks)), 4)


def _reason_text_for_failed_checks(checks: Mapping[str, bool], labels: Mapping[str, str]) -> str:
    failed = [labels.get(key, key) for key, value in checks.items() if not bool(value)]
    return "; ".join(failed)


def build_panic_reversal_shadow_signal(
    price_history,
    *,
    external_context: pd.DataFrame | None = None,
    as_of: str | None = None,
    start_date: str = DEFAULT_START_DATE,
    end_date: str | None = None,
    benchmark_symbol: str = DEFAULT_BENCHMARK_SYMBOL,
    attack_symbol: str = DEFAULT_ATTACK_SYMBOL,
    vix_symbols: Sequence[str] = DEFAULT_VIX_SYMBOLS,
    vix3m_symbols: Sequence[str] = DEFAULT_VIX3M_SYMBOLS,
    max_price_age_days: int = DEFAULT_MAX_PRICE_AGE_DAYS,
    max_vol_age_days: int = DEFAULT_MAX_VOL_AGE_DAYS,
    vix_high_lookback_days: int = DEFAULT_VIX_HIGH_LOOKBACK_DAYS,
    min_vix_high: float = DEFAULT_MIN_VIX_HIGH,
    min_vix_pullback_from_high: float = DEFAULT_MIN_VIX_PULLBACK_FROM_HIGH,
    require_vix_term_structure: bool = DEFAULT_REQUIRE_VIX_TERM_STRUCTURE,
    min_vix_vix3m_ratio: float = DEFAULT_MIN_VIX_VIX3M_RATIO,
    confirmation_lookback_days: int = DEFAULT_PRICE_CONFIRMATION_LOOKBACK_DAYS,
    min_benchmark_rebound_from_low: float = DEFAULT_MIN_BENCHMARK_REBOUND_FROM_LOW,
    min_attack_rebound_from_low: float = DEFAULT_MIN_ATTACK_REBOUND_FROM_LOW,
    min_benchmark_3d_return: float = DEFAULT_MIN_BENCHMARK_3D_RETURN,
    suppress_when_price_crisis_guard_active: bool = True,
    crisis_guard_drawdown: float = DEFAULT_PRICE_CRISIS_GUARD_DRAWDOWN,
    crisis_guard_ma_days: int = DEFAULT_PRICE_CRISIS_GUARD_MA_DAYS,
    crisis_guard_ma_slope_days: int = DEFAULT_PRICE_CRISIS_GUARD_MA_SLOPE_DAYS,
) -> dict[str, Any]:
    close = normalize_close(price_history)
    if end_date is not None:
        close = close.loc[close.index <= pd.Timestamp(end_date).tz_localize(None).normalize()].copy()
    if start_date is not None:
        close = close.loc[close.index >= pd.Timestamp(start_date).tz_localize(None).normalize()].copy()
    requested_date, signal_date = resolve_signal_date(close, as_of)
    signal_iso = signal_date.date().isoformat()
    latest_price_date = pd.Timestamp(close.index.max()).normalize()
    price_age_days = int((requested_date - signal_date).days)

    benchmark_symbol = str(benchmark_symbol).strip().upper()
    attack_symbol = str(attack_symbol).strip().upper()
    ext = _normalize_external_context(external_context)
    vix, vix_source = _metric_series(close, ext, price_symbols=vix_symbols, external_columns=("vix", "vixcls"))
    vix3m, vix3m_source = _metric_series(
        close,
        ext,
        price_symbols=vix3m_symbols,
        external_columns=("vix3m", "vxv", "vxvcls"),
    )

    kill_reasons: list[str] = []
    if benchmark_symbol not in close.columns:
        kill_reasons.append(f"missing benchmark price data: {benchmark_symbol}")
    if attack_symbol not in close.columns:
        kill_reasons.append(f"missing attack price data: {attack_symbol}")
    if price_age_days > int(max_price_age_days):
        kill_reasons.append(
            f"price data stale: signal_as_of={signal_iso}, requested_as_of={requested_date.date().isoformat()}"
        )

    vix_value, vix_date, vix_age_days = _value_on_or_before(vix, signal_date)
    vix3m_value, vix3m_date, vix3m_age_days = _value_on_or_before(vix3m, signal_date)
    if vix_value is None:
        kill_reasons.append("missing VIX data")
    elif vix_age_days is not None and vix_age_days > int(max_vol_age_days):
        kill_reasons.append(f"VIX data stale: vix_as_of={vix_date.date().isoformat() if vix_date is not None else ''}")
    if bool(require_vix_term_structure):
        if vix3m_value is None:
            kill_reasons.append("missing VIX3M data")
        elif vix3m_age_days is not None and vix3m_age_days > int(max_vol_age_days):
            kill_reasons.append(
                f"VIX3M data stale: vix3m_as_of={vix3m_date.date().isoformat() if vix3m_date is not None else ''}"
            )

    vix_window = _last_observations(vix, signal_date, int(vix_high_lookback_days))
    vix_previous = float(vix_window.iloc[-2]) if len(vix_window) >= 2 else float("nan")
    vix_high = float(vix_window.max()) if not vix_window.empty else float("nan")
    vix_pullback_from_high = 1.0 - float(vix_value) / vix_high if vix_value is not None and vix_high > 0 else float("nan")
    vix_vix3m_ratio = (
        float(vix_value) / float(vix3m_value)
        if vix_value is not None and vix3m_value is not None and float(vix3m_value) > 0
        else float("nan")
    )
    price_confirmation = (
        _recent_price_confirmation(
            close,
            signal_date=signal_date,
            benchmark_symbol=benchmark_symbol,
            attack_symbol=attack_symbol,
            lookback_days=int(confirmation_lookback_days),
        )
        if benchmark_symbol in close.columns and attack_symbol in close.columns
        else {}
    )
    crisis_guard_active = False
    if not kill_reasons and bool(suppress_when_price_crisis_guard_active):
        crisis_guard = build_price_crisis_guard_signal(
            close,
            start_date=start_date,
            end_date=signal_iso,
            benchmark_symbol=benchmark_symbol,
            drawdown_threshold=float(crisis_guard_drawdown),
            ma_days=int(crisis_guard_ma_days),
            ma_slope_days=int(crisis_guard_ma_slope_days),
        )
        crisis_guard_active = bool(
            crisis_guard.reindex(crisis_guard.index.union(pd.DatetimeIndex([signal_date]))).sort_index().ffill().loc[signal_date]
        )

    checks = {
        "price_data_usable": not bool(kill_reasons),
        "vix_data_usable": vix_value is not None and (vix_age_days is None or vix_age_days <= int(max_vol_age_days)),
        "vix_high_panic_level": pd.notna(vix_high) and vix_high >= float(min_vix_high),
        "vix_reversed_from_high": pd.notna(vix_pullback_from_high)
        and vix_pullback_from_high >= float(min_vix_pullback_from_high),
        "vix_falling": vix_value is not None and pd.notna(vix_previous) and float(vix_value) < float(vix_previous),
        "vix_term_structure_confirmed": (not bool(require_vix_term_structure))
        or (pd.notna(vix_vix3m_ratio) and vix_vix3m_ratio >= float(min_vix_vix3m_ratio)),
        "benchmark_3d_return_positive": pd.notna(price_confirmation.get("benchmark_3d_return"))
        and float(price_confirmation["benchmark_3d_return"]) > float(min_benchmark_3d_return),
        "benchmark_rebound_from_low": pd.notna(price_confirmation.get("benchmark_rebound_from_recent_low"))
        and float(price_confirmation["benchmark_rebound_from_recent_low"]) >= float(min_benchmark_rebound_from_low),
        "attack_rebound_from_low": pd.notna(price_confirmation.get("attack_rebound_from_recent_low"))
        and float(price_confirmation["attack_rebound_from_recent_low"]) >= float(min_attack_rebound_from_low),
        "price_crisis_guard_clear": not bool(crisis_guard_active),
    }
    hard_check_labels = {
        "price_data_usable": "required price/volatility data unavailable or stale",
        "vix_data_usable": "VIX data unavailable or stale",
        "vix_high_panic_level": "VIX has not reached panic threshold",
        "vix_reversed_from_high": "VIX pullback from panic high below threshold",
        "vix_falling": "VIX has not fallen versus previous observation",
        "vix_term_structure_confirmed": "VIX/VIX3M term structure confirmation missing",
        "benchmark_3d_return_positive": "benchmark 3d return below threshold",
        "benchmark_rebound_from_low": "benchmark rebound from recent low below threshold",
        "attack_rebound_from_low": "attack rebound from recent low below threshold",
        "price_crisis_guard_clear": "price crisis guard active",
    }
    confirmed = all(bool(value) for value in checks.values())
    vix_reversal_watch = bool(checks["vix_high_panic_level"] and checks["vix_reversed_from_high"])
    canonical_route = ROUTE_PANIC_REVERSAL if confirmed else ROUTE_NO_ACTION
    suggested_action = ACTION_NOTIFY_MANUAL_REVIEW if confirmed else ACTION_NO_ACTION
    manual_review_required = bool(confirmed)
    notification_reason = ""
    suppression_reason = ""
    if confirmed:
        notification_reason = "panic volatility reversal with price confirmation"
    elif kill_reasons or crisis_guard_active or vix_reversal_watch:
        canonical_route = ROUTE_WATCH
        suggested_action = ACTION_WATCH_ONLY
        suppression_reason = "; ".join(kill_reasons) or _reason_text_for_failed_checks(checks, hard_check_labels)

    reason_codes: list[str] = []
    if confirmed:
        reason_codes.extend(("panic_reversal", "vix_panic_reversal", "price_rebound_confirmation"))
    elif canonical_route == ROUTE_WATCH:
        reason_codes.append("panic_reversal_watch")
        if crisis_guard_active:
            reason_codes.append("price_crisis_guard_active")

    payload = {
        "as_of": signal_iso,
        "mode": SHADOW_MODE,
        "schema_version": SCHEMA_VERSION,
        "profile": PANIC_REVERSAL_PROFILE,
        "canonical_route": canonical_route,
        "suggested_action": suggested_action,
        "manual_review_required": manual_review_required,
        "notification_reason": notification_reason,
        "suppression_reason": suppression_reason,
        "panic_reversal_context_active": bool(confirmed),
        "would_trade_if_enabled": False,
        "reason_codes": tuple(dict.fromkeys(reason_codes)),
        "reversal_confirmation": {
            "confirmed": bool(confirmed),
            "reason": "" if confirmed else suppression_reason,
            "checks": checks,
            "thresholds": {
                "vix_high_lookback_days": int(vix_high_lookback_days),
                "min_vix_high": float(min_vix_high),
                "min_vix_pullback_from_high": float(min_vix_pullback_from_high),
                "require_vix_term_structure": bool(require_vix_term_structure),
                "min_vix_vix3m_ratio": float(min_vix_vix3m_ratio),
                "confirmation_lookback_days": int(confirmation_lookback_days),
                "min_benchmark_rebound_from_low": float(min_benchmark_rebound_from_low),
                "min_attack_rebound_from_low": float(min_attack_rebound_from_low),
                "min_benchmark_3d_return": float(min_benchmark_3d_return),
            },
        },
        "panic_reversal_quality": {
            "schema_version": "panic_reversal_quality.v1",
            "quality_score": _score_checks(checks),
            "checks": checks,
            "warnings": list(kill_reasons)
            + ([] if confirmed else [value for value in _reason_text_for_failed_checks(checks, hard_check_labels).split("; ") if value]),
            "promotion_status": "shadow_only_insufficient_sample",
        },
        "metrics": {
            "vix": vix_value,
            "vix_source": vix_source,
            "vix_previous": vix_previous,
            "vix_lookback_high": vix_high,
            "vix_pullback_from_high": vix_pullback_from_high,
            "vix3m": vix3m_value,
            "vix3m_source": vix3m_source,
            "vix_vix3m_ratio": vix_vix3m_ratio,
            **price_confirmation,
        },
        "price_crisis_guard_active": crisis_guard_active,
        "data_freshness": {
            "requested_as_of": requested_date.date().isoformat(),
            "signal_as_of": signal_iso,
            "prices_as_of": latest_price_date.date().isoformat(),
            "price_age_days": price_age_days,
            "max_price_age_days": int(max_price_age_days),
            "vix_as_of": vix_date.date().isoformat() if vix_date is not None else None,
            "vix_age_days": vix_age_days,
            "vix3m_as_of": vix3m_date.date().isoformat() if vix3m_date is not None else None,
            "vix3m_age_days": vix3m_age_days,
            "max_vol_age_days": int(max_vol_age_days),
        },
        "notification": {
            "allowed": True,
            "profile": "manual_review_only" if confirmed else "shadow_only",
            "should_notify": bool(confirmed or canonical_route == ROUTE_WATCH),
            "route": canonical_route,
            "suggested_action": suggested_action,
            "reason_codes": tuple(dict.fromkeys(reason_codes)),
        },
        "execution_controls": {
            "capital_impact": "none",
            "broker_order_allowed": False,
            "live_allocation_mutation_allowed": False,
            "log_namespace": PANIC_REVERSAL_PROFILE,
            "notification_profile": "manual_review_only" if confirmed else "shadow_only",
            "intended_strategy_role": "panic_reversal_notification",
            "selection_allowed": False,
            "position_sizing_allowed": False,
            "allocation_recommendation_allowed": False,
            "strategy_runtime_metadata_allowed": True,
            "position_control_shadow_only": True,
        },
        "audit_summary": {
            "route_source": PANIC_REVERSAL_PROFILE,
            "final_route": canonical_route,
            "suggested_action": suggested_action,
            "reason_codes": tuple(dict.fromkeys(reason_codes)),
            "note": "Research-only volatility panic reversal evidence; it cannot increase live allocation.",
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return json_scalar(payload)


def _bounded_ffill_to_index(series: pd.Series, index: pd.DatetimeIndex, *, max_age_days: int) -> pd.Series:
    clean = pd.to_numeric(series, errors="coerce").dropna().sort_index()
    clean.index = pd.to_datetime(clean.index, errors="coerce").tz_localize(None).normalize()
    clean = clean.loc[clean.index.notna()]
    aligned = clean.reindex(index).ffill()
    valid_dates = pd.Series(clean.index, index=clean.index).reindex(index).ffill()
    ages = (pd.Series(index, index=index) - valid_dates).dt.days
    return aligned.where(ages <= int(max_age_days))


def scan_panic_reversal_signals(
    price_history,
    *,
    external_context: pd.DataFrame | None = None,
    start_date: str = DEFAULT_START_DATE,
    end_date: str | None = None,
    benchmark_symbol: str = DEFAULT_BENCHMARK_SYMBOL,
    attack_symbol: str = DEFAULT_ATTACK_SYMBOL,
    vix_symbols: Sequence[str] = DEFAULT_VIX_SYMBOLS,
    vix3m_symbols: Sequence[str] = DEFAULT_VIX3M_SYMBOLS,
    max_vol_age_days: int = DEFAULT_MAX_VOL_AGE_DAYS,
    vix_high_lookback_days: int = DEFAULT_VIX_HIGH_LOOKBACK_DAYS,
    min_vix_high: float = DEFAULT_MIN_VIX_HIGH,
    min_vix_pullback_from_high: float = DEFAULT_MIN_VIX_PULLBACK_FROM_HIGH,
    require_vix_term_structure: bool = DEFAULT_REQUIRE_VIX_TERM_STRUCTURE,
    min_vix_vix3m_ratio: float = DEFAULT_MIN_VIX_VIX3M_RATIO,
    confirmation_lookback_days: int = DEFAULT_PRICE_CONFIRMATION_LOOKBACK_DAYS,
    min_benchmark_rebound_from_low: float = DEFAULT_MIN_BENCHMARK_REBOUND_FROM_LOW,
    min_attack_rebound_from_low: float = DEFAULT_MIN_ATTACK_REBOUND_FROM_LOW,
    min_benchmark_3d_return: float = DEFAULT_MIN_BENCHMARK_3D_RETURN,
    suppress_when_price_crisis_guard_active: bool = True,
    crisis_guard_drawdown: float = DEFAULT_PRICE_CRISIS_GUARD_DRAWDOWN,
    min_gap_trading_days: int = 21,
) -> pd.DataFrame:
    close = normalize_close(price_history)
    if start_date is not None:
        close = close.loc[close.index >= pd.Timestamp(start_date).normalize()].copy()
    if end_date is not None:
        close = close.loc[close.index <= pd.Timestamp(end_date).normalize()].copy()
    benchmark_symbol = str(benchmark_symbol).strip().upper()
    attack_symbol = str(attack_symbol).strip().upper()
    if benchmark_symbol not in close.columns:
        raise ValueError(f"benchmark symbol {benchmark_symbol!r} missing from price history")
    if attack_symbol not in close.columns:
        raise ValueError(f"attack symbol {attack_symbol!r} missing from price history")

    ext = _normalize_external_context(external_context)
    raw_vix, vix_source = _metric_series(close, ext, price_symbols=vix_symbols, external_columns=("vix", "vixcls"))
    raw_vix3m, vix3m_source = _metric_series(
        close,
        ext,
        price_symbols=vix3m_symbols,
        external_columns=("vix3m", "vxv", "vxvcls"),
    )
    if raw_vix.empty:
        raise ValueError("VIX data is required for panic reversal scan")
    index = pd.DatetimeIndex(close.index).sort_values()
    vix = _bounded_ffill_to_index(raw_vix, index, max_age_days=int(max_vol_age_days))
    vix3m = (
        _bounded_ffill_to_index(raw_vix3m, index, max_age_days=int(max_vol_age_days))
        if not raw_vix3m.empty
        else pd.Series(float("nan"), index=index)
    )
    benchmark = pd.to_numeric(close[benchmark_symbol], errors="coerce")
    attack = pd.to_numeric(close[attack_symbol], errors="coerce")
    vix_high = vix.rolling(int(vix_high_lookback_days), min_periods=int(vix_high_lookback_days)).max()
    vix_pullback = 1.0 - vix / vix_high
    vix_ratio = vix / vix3m.where(vix3m > 0)
    benchmark_rebound = benchmark / benchmark.rolling(int(confirmation_lookback_days), min_periods=1).min() - 1.0
    attack_rebound = attack / attack.rolling(int(confirmation_lookback_days), min_periods=1).min() - 1.0
    crisis_guard = (
        build_price_crisis_guard_signal(
            close,
            start_date=start_date,
            end_date=end_date,
            benchmark_symbol=benchmark_symbol,
            drawdown_threshold=float(crisis_guard_drawdown),
        ).reindex(index).ffill().fillna(False)
        if bool(suppress_when_price_crisis_guard_active)
        else pd.Series(False, index=index)
    )
    vix_term_structure_ok = (
        vix_ratio.ge(float(min_vix_vix3m_ratio))
        if bool(require_vix_term_structure)
        else pd.Series(True, index=index)
    )
    signal = (
        vix_high.ge(float(min_vix_high))
        & vix_pullback.ge(float(min_vix_pullback_from_high))
        & vix.lt(vix.shift(1))
        & vix_term_structure_ok
        & benchmark.pct_change(3).gt(float(min_benchmark_3d_return))
        & benchmark_rebound.ge(float(min_benchmark_rebound_from_low))
        & attack_rebound.ge(float(min_attack_rebound_from_low))
        & ~crisis_guard.astype(bool)
    ).fillna(False)

    rows: list[dict[str, object]] = []
    last_signal_pos = -10_000
    for pos, date in enumerate(index):
        if not bool(signal.loc[date]):
            continue
        if pos - last_signal_pos < int(min_gap_trading_days):
            continue
        rows.append(
            {
                "signal_date": date.date().isoformat(),
                "benchmark_symbol": benchmark_symbol,
                "attack_symbol": attack_symbol,
                "vix": float(vix.loc[date]),
                "vix_source": vix_source,
                "vix3m": float(vix3m.loc[date]) if pd.notna(vix3m.loc[date]) else float("nan"),
                "vix3m_source": vix3m_source,
                "vix_lookback_high": float(vix_high.loc[date]),
                "vix_pullback_from_high": float(vix_pullback.loc[date]),
                "vix_vix3m_ratio": float(vix_ratio.loc[date]) if pd.notna(vix_ratio.loc[date]) else float("nan"),
                "benchmark_3d_return": float(benchmark.pct_change(3).loc[date]),
                "benchmark_rebound_from_recent_low": float(benchmark_rebound.loc[date]),
                "attack_rebound_from_recent_low": float(attack_rebound.loc[date]),
                "price_crisis_guard_active": bool(crisis_guard.loc[date]),
            }
        )
        last_signal_pos = pos
    return pd.DataFrame(rows)


def run_panic_reversal_event_study(
    price_history,
    *,
    external_context: pd.DataFrame | None = None,
    start_date: str = DEFAULT_START_DATE,
    end_date: str | None = None,
    benchmark_symbol: str = DEFAULT_BENCHMARK_SYMBOL,
    attack_symbol: str = DEFAULT_ATTACK_SYMBOL,
    horizons: Sequence[int] = DEFAULT_EVENT_STUDY_HORIZONS,
    entry_lag_trading_days: int = 1,
    min_gap_trading_days: int = 21,
    **scan_kwargs: Any,
) -> dict[str, pd.DataFrame]:
    close = normalize_close(price_history)
    if start_date is not None:
        close = close.loc[close.index >= pd.Timestamp(start_date).normalize()].copy()
    if end_date is not None:
        close = close.loc[close.index <= pd.Timestamp(end_date).normalize()].copy()
    index = pd.DatetimeIndex(close.index).sort_values()
    signals = scan_panic_reversal_signals(
        close,
        external_context=external_context,
        start_date=start_date,
        end_date=end_date,
        benchmark_symbol=benchmark_symbol,
        attack_symbol=attack_symbol,
        min_gap_trading_days=min_gap_trading_days,
        **scan_kwargs,
    )
    rows: list[dict[str, object]] = []
    benchmark_symbol = str(benchmark_symbol).strip().upper()
    attack_symbol = str(attack_symbol).strip().upper()
    for signal in signals.itertuples(index=False):
        signal_date = pd.Timestamp(signal.signal_date).normalize()
        if signal_date not in index:
            continue
        signal_pos = int(index.get_loc(signal_date))
        entry_pos = signal_pos + max(0, int(entry_lag_trading_days))
        if entry_pos >= len(index):
            continue
        entry_date = pd.Timestamp(index[entry_pos]).normalize()
        for horizon in tuple(int(value) for value in horizons):
            exit_pos = min(len(index) - 1, entry_pos + max(0, horizon))
            exit_date = pd.Timestamp(index[exit_pos]).normalize()
            for symbol in (benchmark_symbol, attack_symbol):
                entry_close = float(close.at[entry_date, symbol])
                exit_close = float(close.at[exit_date, symbol])
                if not pd.notna(entry_close) or not pd.notna(exit_close) or entry_close <= 0:
                    continue
                path = pd.to_numeric(close[symbol].loc[(close.index >= entry_date) & (close.index <= exit_date)], errors="coerce")
                drawdown = path / path.cummax() - 1.0
                rows.append(
                    {
                        "signal_date": signal.signal_date,
                        "entry_date": entry_date.date().isoformat(),
                        "exit_date": exit_date.date().isoformat(),
                        "symbol": symbol,
                        "horizon_days": horizon,
                        "entry_close": entry_close,
                        "exit_close": exit_close,
                        "return": exit_close / entry_close - 1.0 if entry_close > 0 else float("nan"),
                        "max_drawdown_after_entry": float(drawdown.min()) if not drawdown.empty else float("nan"),
                    }
                )
    event_windows = pd.DataFrame(rows)
    if event_windows.empty:
        summary = pd.DataFrame(
            columns=["symbol", "horizon_days", "trades", "avg_return", "median_return", "win_rate", "avg_max_drawdown"]
        )
    else:
        summary = (
            event_windows.groupby(["symbol", "horizon_days"], as_index=False)
            .agg(
                trades=("return", "count"),
                avg_return=("return", "mean"),
                median_return=("return", "median"),
                win_rate=("return", lambda values: float((pd.Series(values) > 0.0).mean())),
                avg_max_drawdown=("max_drawdown_after_entry", "mean"),
            )
            .sort_values(["symbol", "horizon_days"])
            .reset_index(drop=True)
        )
    return {"signals": signals, "event_windows": event_windows, "summary": summary}


def write_panic_reversal_shadow_outputs(payload: Mapping[str, Any], output_dir: str | Path) -> dict[str, Path]:
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
        "manual_review_required": payload.get("manual_review_required"),
        "notification_reason": payload.get("notification_reason"),
        "suppression_reason": payload.get("suppression_reason"),
        **flatten_for_csv(payload.get("reversal_confirmation", {})),
        **flatten_for_csv(payload.get("panic_reversal_quality", {})),
        **flatten_for_csv(payload.get("metrics", {})),
        **flatten_for_csv(payload.get("data_freshness", {})),
    }
    pd.DataFrame([evidence_payload]).to_csv(evidence_csv_path, index=False)
    return {
        "latest_signal": latest_path,
        "signal_json": dated_json_path,
        "signal_csv": dated_csv_path,
        "evidence_csv": evidence_csv_path,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the research-only panic reversal shadow signal.")
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--prices", help="Existing long price-history CSV with symbol/as_of/close columns")
    input_group.add_argument("--download", action="store_true", help="Download adjusted price history through yfinance")
    parser.add_argument("--external-context", default=None, help="Optional external_context CSV with vix/vix3m columns")
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--price-start", default=DEFAULT_START_DATE)
    parser.add_argument("--price-end", default=None)
    parser.add_argument("--download-proxy", default=None, help="Optional yfinance proxy URL; YFINANCE_PROXY also works")
    parser.add_argument("--start", dest="start_date", default=DEFAULT_START_DATE)
    parser.add_argument("--end", dest="end_date", default=None)
    parser.add_argument("--benchmark-symbol", default=DEFAULT_BENCHMARK_SYMBOL)
    parser.add_argument("--attack-symbol", default=DEFAULT_ATTACK_SYMBOL)
    parser.add_argument("--vix-symbols", default=",".join(DEFAULT_VIX_SYMBOLS))
    parser.add_argument("--vix3m-symbols", default=",".join(DEFAULT_VIX3M_SYMBOLS))
    parser.add_argument("--min-vix-high", type=float, default=DEFAULT_MIN_VIX_HIGH)
    parser.add_argument("--min-vix-pullback-from-high", type=float, default=DEFAULT_MIN_VIX_PULLBACK_FROM_HIGH)
    parser.add_argument("--min-vix-vix3m-ratio", type=float, default=DEFAULT_MIN_VIX_VIX3M_RATIO)
    parser.add_argument("--disable-vix-term-structure", action="store_true")
    parser.add_argument("--min-benchmark-rebound-from-low", type=float, default=DEFAULT_MIN_BENCHMARK_REBOUND_FROM_LOW)
    parser.add_argument("--min-attack-rebound-from-low", type=float, default=DEFAULT_MIN_ATTACK_REBOUND_FROM_LOW)
    parser.add_argument("--min-benchmark-3d-return", type=float, default=DEFAULT_MIN_BENCHMARK_3D_RETURN)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.download:
        symbols = [args.benchmark_symbol, args.attack_symbol, *_as_str_tuple(args.vix_symbols), *_as_str_tuple(args.vix3m_symbols)]
        symbols = list(dict.fromkeys(symbol for symbol in symbols if symbol and not symbol.startswith("^")))
        input_dir = Path(args.output_dir) / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        prices_path = input_dir / "panic_reversal_shadow_price_history.csv"
        prices = download_price_history(symbols, start=args.price_start, end=args.price_end, proxy=args.download_proxy)
        prices.to_csv(prices_path, index=False)
        price_history = prices
    else:
        price_history = read_table(args.prices)
    external_context = read_table(args.external_context) if args.external_context else None
    payload = build_panic_reversal_shadow_signal(
        price_history,
        external_context=external_context,
        as_of=args.as_of,
        start_date=args.start_date,
        end_date=args.end_date,
        benchmark_symbol=args.benchmark_symbol,
        attack_symbol=args.attack_symbol,
        vix_symbols=_as_str_tuple(args.vix_symbols),
        vix3m_symbols=_as_str_tuple(args.vix3m_symbols),
        min_vix_high=float(args.min_vix_high),
        min_vix_pullback_from_high=float(args.min_vix_pullback_from_high),
        require_vix_term_structure=not bool(args.disable_vix_term_structure),
        min_vix_vix3m_ratio=float(args.min_vix_vix3m_ratio),
        min_benchmark_rebound_from_low=float(args.min_benchmark_rebound_from_low),
        min_attack_rebound_from_low=float(args.min_attack_rebound_from_low),
        min_benchmark_3d_return=float(args.min_benchmark_3d_return),
    )
    paths = write_panic_reversal_shadow_outputs(payload, args.output_dir)
    print(
        "wrote panic reversal shadow signal "
        f"as_of={payload['as_of']} route={payload['canonical_route']} "
        f"action={payload['suggested_action']} latest={paths['latest_signal']}"
    )
    return 0


__all__ = [
    "ACTION_NOTIFY_MANUAL_REVIEW",
    "PANIC_REVERSAL_PROFILE",
    "ROUTE_PANIC_REVERSAL",
    "SCHEMA_VERSION",
    "build_panic_reversal_shadow_signal",
    "main",
    "run_panic_reversal_event_study",
    "scan_panic_reversal_signals",
    "write_panic_reversal_shadow_outputs",
]
