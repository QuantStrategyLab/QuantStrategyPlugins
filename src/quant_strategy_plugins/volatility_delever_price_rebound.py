from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import pandas as pd

from .plugin_signal_utils import normalize_close, resolve_signal_date


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raw_values = value.split(",")
    else:
        raw_values = list(value)
    return tuple(str(item).strip() for item in raw_values if str(item).strip())


def _as_credit_pairs(value: Any) -> tuple[tuple[str, str], ...]:
    pairs: list[tuple[str, str]] = []
    for item in _as_str_tuple(value):
        parts = [part.strip().upper() for part in item.replace("/", ":").split(":")]
        if len(parts) != 2 or not all(parts):
            raise ValueError(f"credit pair must use NUMERATOR:DENOMINATOR syntax: {item!r}")
        pair = (parts[0], parts[1])
        if pair not in pairs:
            pairs.append(pair)
    return tuple(pairs)


def _as_float_or_none(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _first_existing_series(close: pd.DataFrame, symbols: Sequence[str]) -> tuple[pd.Series | None, str | None]:
    for symbol in symbols:
        normalized = str(symbol or "").strip().upper()
        if normalized and normalized in close.columns:
            return pd.to_numeric(close[normalized], errors="coerce"), normalized
    return None, None


def _relative_return_at(
    close: pd.DataFrame,
    *,
    numerator: str,
    denominator: str,
    signal_date: pd.Timestamp,
    lookback_days: int,
) -> float | None:
    numerator = str(numerator or "").strip().upper()
    denominator = str(denominator or "").strip().upper()
    if numerator not in close.columns or denominator not in close.columns or signal_date not in close.index:
        return None
    index = pd.DatetimeIndex(close.index)
    signal_pos = int(index.get_loc(signal_date))
    lookback_pos = signal_pos - int(lookback_days)
    if lookback_pos < 0:
        return None
    current_denominator = float(close[denominator].iloc[signal_pos])
    previous_denominator = float(close[denominator].iloc[lookback_pos])
    if current_denominator <= 0.0 or previous_denominator <= 0.0:
        return None
    current = float(close[numerator].iloc[signal_pos]) / current_denominator
    previous = float(close[numerator].iloc[lookback_pos]) / previous_denominator
    return current / previous - 1.0 if previous > 0.0 else None


def _rolling_drawdown_at(series: pd.Series, signal_date: pd.Timestamp, lookback_days: int) -> float | None:
    if signal_date not in series.index:
        return None
    index = pd.DatetimeIndex(series.index)
    signal_pos = int(index.get_loc(signal_date))
    window = pd.to_numeric(series.iloc[max(0, signal_pos - int(lookback_days) + 1) : signal_pos + 1], errors="coerce")
    peak = float(window.max()) if window.notna().any() else float("nan")
    current = float(window.iloc[-1]) if window.notna().any() else float("nan")
    if not math.isfinite(peak) or peak <= 0.0 or not math.isfinite(current):
        return None
    return current / peak - 1.0


def _realized_vol_ratio_at(
    series: pd.Series,
    *,
    signal_date: pd.Timestamp,
    window_days: int,
    percentile: float,
    lookback_days: int,
    min_periods: int,
    floor: float,
    cap: float,
    fallback: float,
) -> tuple[float | None, float | None, float | None]:
    returns = pd.to_numeric(series, errors="coerce").pct_change()
    realized_vol = returns.rolling(int(window_days), min_periods=int(window_days)).std(ddof=0) * math.sqrt(252)
    if signal_date not in realized_vol.index:
        return None, None, None
    current = _as_float_or_none(realized_vol.loc[signal_date])
    if current is None:
        return None, None, None
    sample = realized_vol.loc[:signal_date].dropna().tail(int(lookback_days))
    if len(sample) < int(min_periods):
        threshold = float(fallback)
    else:
        threshold = float(sample.quantile(float(percentile)))
    threshold = max(float(floor), min(float(cap), threshold))
    return current, threshold, current / threshold if threshold > 0.0 else None


def build_volatility_delever_price_rebound_context(
    price_history: pd.DataFrame,
    plugin_config: Mapping[str, Any],
) -> dict[str, Any]:
    """Build deterministic levered volatility-delever rebound context.

    The context is intentionally limited to backtestable hard data. It feeds
    retention profiles only; market-regime route authority stays with the
    existing crisis and macro components.
    """

    strategy = str(plugin_config.get("strategy") or "").strip().lower()
    default_enabled = strategy in {"soxl_soxx_trend_income", "tecl_xlk_trend_income"}
    if not _as_bool(plugin_config.get("volatility_delever_price_rebound_enabled"), default=default_enabled):
        return {}

    close = normalize_close(price_history)
    as_of = str(plugin_config.get("as_of", "") or "").strip() or None
    benchmark_symbol = str(plugin_config.get("benchmark_symbol") or "").strip().upper()
    if not benchmark_symbol:
        benchmark_symbol = "XLK" if strategy == "tecl_xlk_trend_income" else "SOXX"
    if benchmark_symbol not in close.columns:
        _, signal_date = resolve_signal_date(close, as_of)
        return {
            "enabled": True,
            "confirmed": False,
            "as_of": signal_date.date().isoformat(),
            "reason_codes": ("missing_benchmark",),
            "benchmark_symbol": benchmark_symbol,
        }
    close = close.loc[pd.to_numeric(close[benchmark_symbol], errors="coerce").notna()].copy()
    _, signal_date = resolve_signal_date(close, as_of)
    signal_iso = signal_date.date().isoformat()

    benchmark = pd.to_numeric(close[benchmark_symbol], errors="coerce")
    if signal_date not in benchmark.index:
        return {
            "enabled": True,
            "confirmed": False,
            "as_of": signal_iso,
            "reason_codes": ("missing_signal_date",),
            "benchmark_symbol": benchmark_symbol,
        }

    trend_ma_days = int(plugin_config.get("volatility_delever_price_trend_ma_days", 140) or 140)
    slope_ma_days = int(plugin_config.get("volatility_delever_price_slope_ma_days", 20) or 20)
    rebound_lookback_days = int(plugin_config.get("volatility_delever_price_rebound_lookback_days", 3) or 3)
    drawdown_limit = float(plugin_config.get("volatility_delever_price_drawdown_limit", -0.18) or -0.18)
    drawdown_lookback_days = int(plugin_config.get("volatility_delever_price_drawdown_lookback_days", 252) or 252)
    vix_soft_level = float(plugin_config.get("volatility_delever_price_vix_soft_level", 28.0) or 28.0)
    vix_hard_level = float(plugin_config.get("volatility_delever_price_vix_hard_level", 35.0) or 35.0)
    credit_soft_threshold = float(
        plugin_config.get("volatility_delever_price_credit_soft_threshold", -0.025) or -0.025
    )
    credit_hard_threshold = float(
        plugin_config.get("volatility_delever_price_credit_hard_threshold", -0.05) or -0.05
    )
    financial_hard_threshold = float(
        plugin_config.get("volatility_delever_price_financial_hard_threshold", -0.10) or -0.10
    )
    vol_ratio_soft_level = float(plugin_config.get("volatility_delever_price_vol_ratio_soft_level", 1.65) or 1.65)

    signal_pos = int(pd.DatetimeIndex(benchmark.index).get_loc(signal_date))
    trend_ma = benchmark.rolling(trend_ma_days, min_periods=min(trend_ma_days, 120)).mean()
    slope_ma = benchmark.rolling(slope_ma_days, min_periods=slope_ma_days).mean()
    benchmark_close = _as_float_or_none(benchmark.loc[signal_date])
    trend_ma_value = _as_float_or_none(trend_ma.loc[signal_date])
    slope_ma_value = _as_float_or_none(slope_ma.loc[signal_date])
    previous_slope_ma_value = _as_float_or_none(slope_ma.iloc[signal_pos - 1]) if signal_pos > 0 else None
    trend_ok = bool(
        benchmark_close is not None and trend_ma_value is not None and benchmark_close > trend_ma_value
    )
    slope_ok = bool(
        slope_ma_value is not None
        and previous_slope_ma_value is not None
        and slope_ma_value > previous_slope_ma_value
    )

    rebound_1d = False
    if signal_pos >= 1:
        previous_close = _as_float_or_none(benchmark.iloc[signal_pos - 1])
        rebound_1d = bool(benchmark_close is not None and previous_close is not None and benchmark_close > previous_close)
    rebound_nd = False
    if signal_pos >= rebound_lookback_days:
        previous_close = _as_float_or_none(benchmark.iloc[signal_pos - rebound_lookback_days])
        rebound_nd = bool(benchmark_close is not None and previous_close is not None and benchmark_close > previous_close)

    drawdown = _rolling_drawdown_at(benchmark, signal_date, drawdown_lookback_days)
    vix_series, vix_symbol = _first_existing_series(close, _as_str_tuple(plugin_config.get("vix_symbols")) or ("^VIX",))
    vix = (
        _as_float_or_none(vix_series.loc[signal_date])
        if vix_series is not None and signal_date in vix_series.index
        else None
    )
    credit_pairs = _as_credit_pairs(plugin_config.get("credit_pairs", ("HYG:IEF",)))
    credit = (
        _relative_return_at(
            close,
            numerator=credit_pairs[0][0],
            denominator=credit_pairs[0][1],
            signal_date=signal_date,
            lookback_days=21,
        )
        if credit_pairs
        else None
    )
    financial_symbols = _as_str_tuple(plugin_config.get("financial_symbols")) or ("XLF",)
    financial = _relative_return_at(
        close,
        numerator=financial_symbols[0],
        denominator="SPY",
        signal_date=signal_date,
        lookback_days=63,
    )
    current_vol, vol_threshold, vol_ratio = _realized_vol_ratio_at(
        benchmark,
        signal_date=signal_date,
        window_days=int(plugin_config.get("volatility_delever_price_realized_vol_window", 10) or 10),
        percentile=float(plugin_config.get("volatility_delever_price_dynamic_percentile", 0.95) or 0.95),
        lookback_days=int(plugin_config.get("volatility_delever_price_dynamic_lookback", 252) or 252),
        min_periods=int(plugin_config.get("volatility_delever_price_dynamic_min_periods", 126) or 126),
        floor=float(plugin_config.get("volatility_delever_price_dynamic_floor", 0.50) or 0.50),
        cap=float(plugin_config.get("volatility_delever_price_dynamic_cap", 0.75) or 0.75),
        fallback=float(plugin_config.get("volatility_delever_price_dynamic_fallback", 0.55) or 0.55),
    )
    volatility_triggered = bool(
        current_vol is not None and vol_threshold is not None and current_vol >= vol_threshold
    )

    hard = bool(
        (not trend_ok)
        or (drawdown is not None and drawdown <= drawdown_limit)
        or (vix is not None and vix >= vix_hard_level)
        or (credit is not None and credit <= credit_hard_threshold)
        or (financial is not None and financial <= financial_hard_threshold)
    )
    soft = bool(
        (drawdown is not None and drawdown <= drawdown_limit / 1.5)
        or (vix is not None and vix >= vix_soft_level)
        or (credit is not None and credit <= credit_soft_threshold)
        or (vol_ratio is not None and vol_ratio >= vol_ratio_soft_level)
    )
    constructive = bool(trend_ok and slope_ok and not soft)
    rebound_confirm = bool(
        trend_ok
        and (rebound_1d or rebound_nd)
        and (vix is None or vix < vix_hard_level)
        and (credit is None or credit > credit_hard_threshold)
    )
    confirmed = bool(volatility_triggered and constructive and rebound_confirm and not hard)
    reason_codes: list[str] = []
    if confirmed:
        reason_codes.append("price_rebound_confirm")
    else:
        if hard:
            reason_codes.append("hard_filter")
        if soft:
            reason_codes.append("soft_filter")
        if not constructive:
            reason_codes.append("constructive_filter")
        if not rebound_confirm:
            reason_codes.append("rebound_not_confirmed")
        if not volatility_triggered:
            reason_codes.append("volatility_trigger_not_confirmed")
    return {
        "schema_version": "volatility_delever_price_rebound_context.v1",
        "enabled": True,
        "confirmed": confirmed,
        "as_of": signal_iso,
        "benchmark_symbol": benchmark_symbol,
        "vix_symbol": vix_symbol,
        "reason_codes": tuple(dict.fromkeys(reason_codes)),
        "trend_ok": trend_ok,
        "slope_ok": slope_ok,
        "constructive": constructive,
        "hard_filter": hard,
        "soft_filter": soft,
        "volatility_triggered": volatility_triggered,
        "rebound_1d": rebound_1d,
        "rebound_nd": rebound_nd,
        "metrics": {
            "benchmark_close": benchmark_close,
            "trend_ma": trend_ma_value,
            "slope_ma": slope_ma_value,
            "drawdown": drawdown,
            "vix": vix,
            "credit_relative_21d": credit,
            "financial_relative_63d": financial,
            "realized_vol": current_vol,
            "realized_vol_threshold": vol_threshold,
            "realized_vol_ratio": vol_ratio,
        },
    }


__all__ = ["build_volatility_delever_price_rebound_context"]
