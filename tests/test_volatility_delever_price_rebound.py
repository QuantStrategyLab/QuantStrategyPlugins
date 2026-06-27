from __future__ import annotations

import pandas as pd

from quant_strategy_plugins.volatility_delever_price_rebound import build_volatility_delever_price_rebound_context


def _soxl_rebound_prices() -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=230)
    trend = [100.0 + offset * 0.18 for offset in range(220)]
    last = trend[-1]
    tail = [
        last,
        last * 0.96,
        last * 1.01,
        last * 0.97,
        last * 1.02,
        last * 0.98,
        last * 1.03,
        last * 0.99,
        last * 1.04,
        last * 1.08,
    ]
    soxx = pd.Series(trend + tail, index=dates)
    prices = {
        "SOXX": soxx,
        "SOXL": soxx * 3.0,
        "SPY": pd.Series([100.0 + offset * 0.06 for offset in range(len(dates))], index=dates),
        "XLF": pd.Series([100.0 + offset * 0.05 for offset in range(len(dates))], index=dates),
        "HYG": pd.Series(100.0, index=dates),
        "IEF": pd.Series(100.0, index=dates),
        "VIX": pd.Series(18.0, index=dates),
    }
    rows: list[dict[str, object]] = []
    for symbol, series in prices.items():
        for as_of, close in series.items():
            rows.append({"symbol": symbol, "as_of": as_of, "close": close, "volume": 1_000_000})
    return pd.DataFrame(rows)


def test_price_rebound_context_defaults_disabled_for_non_soxl_strategy() -> None:
    context = build_volatility_delever_price_rebound_context(
        _soxl_rebound_prices(),
        {"strategy": "tqqq_growth_income", "benchmark_symbol": "SOXX"},
    )

    assert context == {}


def test_price_rebound_context_defaults_enabled_for_tecl_strategy() -> None:
    prices = _soxl_rebound_prices()
    prices = prices.assign(
        symbol=prices["symbol"].map(lambda value: {"SOXX": "XLK", "SOXL": "TECL"}.get(value, value))
    )
    context = build_volatility_delever_price_rebound_context(
        prices,
        {
            "strategy": "tecl_xlk_trend_income",
            "as_of": pd.Timestamp(prices["as_of"].max()).date().isoformat(),
            "vix_symbols": ["VIX"],
            "credit_pairs": ["HYG:IEF"],
            "financial_symbols": ["XLF"],
        },
    )

    assert context.get("enabled") is True
    assert context.get("benchmark_symbol") == "XLK"


def test_price_rebound_context_confirms_soxl_constructive_rebound() -> None:
    prices = _soxl_rebound_prices()
    context = build_volatility_delever_price_rebound_context(
        prices,
        {
            "strategy": "soxl_soxx_trend_income",
            "as_of": pd.Timestamp(prices["as_of"].max()).date().isoformat(),
            "benchmark_symbol": "SOXX",
            "attack_symbol": "SOXL",
            "vix_symbols": ["VIX"],
            "credit_pairs": ["HYG:IEF"],
            "financial_symbols": ["XLF"],
        },
    )

    assert context["schema_version"] == "volatility_delever_price_rebound_context.v1"
    assert context["confirmed"] is True
    assert context["reason_codes"] == ("price_rebound_confirm",)
    assert context["trend_ok"] is True
    assert context["slope_ok"] is True
    assert context["volatility_triggered"] is True
    assert context["hard_filter"] is False
    assert context["soft_filter"] is False


def test_price_rebound_context_can_be_explicitly_disabled_for_soxl() -> None:
    context = build_volatility_delever_price_rebound_context(
        _soxl_rebound_prices(),
        {
            "strategy": "soxl_soxx_trend_income",
            "benchmark_symbol": "SOXX",
            "volatility_delever_price_rebound_enabled": False,
        },
    )

    assert context == {}
