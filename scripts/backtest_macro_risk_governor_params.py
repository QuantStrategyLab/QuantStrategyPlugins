"""Macro risk governor parameter sensitivity backtest.

Validates the 30+ indicator scoring system against historical QQQ data
to check whether the score thresholds (3/5/7) and the new delever vs
crisis scalar defaults (0.5 vs 0.0) are well-calibrated.

Tests two key questions:
1. Do the score thresholds meaningfully separate market stress regimes?
2. Does the delever (0.5) vs crisis (0.0) distinction improve outcomes?

Usage
-----
    cd QuantStrategyPlugins
    PYTHONPATH=src python scripts/backtest_macro_risk_governor_params.py
"""

from __future__ import annotations

import argparse
import math
import sys
from typing import Any

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


def load_data() -> dict[str, pd.Series]:
    """Download QQQ, VIX, HYG, IEF, and yield curve data."""
    try:
        import yfinance as yf
    except ImportError:
        print("yfinance required: pip install yfinance", file=sys.stderr)
        sys.exit(1)

    symbols = {
        "qqq": "QQQ",
        "vix": "^VIX",
        "hyg": "HYG",
        "ief": "IEF",
        "tlt": "TLT",
    }

    data: dict[str, pd.Series] = {}
    for key, symbol in symbols.items():
        raw = yf.download(symbol, start="2010-01-01", end="2026-06-28",
                          auto_adjust=True, progress=False, threads=False)
        close = raw["Close"].copy()
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        data[key] = close.astype(float).dropna()

    return data


# ---------------------------------------------------------------------------
# Indicator computation (simplified subset of macro_risk_governor logic)
# ---------------------------------------------------------------------------


def _sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=window).mean()


def _dd_252(close: pd.Series) -> pd.Series:
    high = close.rolling(252, min_periods=63).max()
    return close / high - 1.0


def _realized_vol(close: pd.Series, window: int = 21) -> pd.Series:
    ret = close.pct_change()
    return ret.rolling(window).std() * math.sqrt(252)


def compute_indicators(data: dict[str, pd.Series]) -> pd.DataFrame:
    """Compute key macro indicators from price data."""
    qqq = data["qqq"]
    vix = data["vix"]
    hyg = data["hyg"]
    ief = data["ief"]

    idx = qqq.index.intersection(vix.index).sort_values()
    df = pd.DataFrame(index=idx)

    df["qqq_close"] = qqq.reindex(idx)
    df["vix"] = vix.reindex(idx)
    df["qqq_dd_252"] = _dd_252(df["qqq_close"])
    df["qqq_vol_21"] = _realized_vol(df["qqq_close"], 21)
    df["qqq_sma200"] = _sma(df["qqq_close"], 200)
    df["qqq_below_sma200"] = df["qqq_close"] < df["qqq_sma200"]

    # Credit spread proxy: HYG/IEF ratio
    hyg_idx = hyg.reindex(idx)
    ief_idx = ief.reindex(idx)
    df["credit_ratio"] = hyg_idx / ief_idx
    df["credit_dd_63"] = _dd_252(df["credit_ratio"].ffill())  # 63d proxy

    # VIX regime
    df["vix_28"] = (df["vix"] >= 28).astype(int)
    df["vix_35"] = (df["vix"] >= 35).astype(int)
    df["vix_50"] = (df["vix"] >= 50).astype(int)

    # Composite macro score (simplified from the 30+ indicators)
    df["score"] = 0.0
    # VIX (weight 2.0 in original)
    df["score"] += np.where(df["vix"] >= 35, 2.0, np.where(df["vix"] >= 28, 1.0, 0.0))
    # Credit stress (weight 2.0)
    df["score"] += np.where(df["credit_dd_63"] <= -0.05, 2.0,
                            np.where(df["credit_dd_63"] <= -0.025, 1.0, 0.0))
    # QQ drawdown (weight 2.0)
    df["score"] += np.where(df["qqq_dd_252"] <= -0.20, 2.0,
                            np.where(df["qqq_dd_252"] <= -0.10, 1.0, 0.0))
    # Vol spike (weight 1.0)
    df["score"] += np.where(df["qqq_vol_21"] >= 0.50, 1.0,
                            np.where(df["qqq_vol_21"] >= 0.35, 0.5, 0.0))
    # Below SMA200 (weight 1.0)
    df["score"] += np.where(df["qqq_below_sma200"], 1.0, 0.0)

    # Route classification
    conditions = [
        df["score"] >= 7.0,  # crisis
        df["score"] >= 5.0,  # delever
        df["score"] >= 3.0,  # watch
    ]
    choices = ["crisis", "delever", "watch"]
    df["regime"] = np.select(conditions, choices, default="no_action")

    return df.dropna()


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------


def run_backtest(
    df: pd.DataFrame,
    delever_scalar: float = 0.50,
    crisis_scalar: float = 0.0,
    top_n: int = 5,
) -> dict[str, Any]:
    """Simulate TQQQ exposure scaling based on macro regime signals.

    When regime is "crisis" → exposure = crisis_scalar
    When regime is "delever" → exposure = delever_scalar
    When regime is "watch" → exposure = 0.85 (slight reduction)
    When regime is "no_action" → exposure = 1.0
    """
    # Simulate TQQQ (3x QQQ daily return)
    qqq_ret = df["qqq_close"].pct_change()
    tqqq_ret = qqq_ret * 3.0

    # Exposures based on regime (lagged by 1 day to avoid look-ahead)
    exposure = pd.Series(1.0, index=df.index)
    prev_regime = df["regime"].shift(1).fillna("no_action")
    exposure[prev_regime == "crisis"] = crisis_scalar
    exposure[prev_regime == "delever"] = delever_scalar
    exposure[prev_regime == "watch"] = 0.85

    # Portfolio returns
    portfolio_ret = tqqq_ret * exposure
    portfolio_equity = (1.0 + portfolio_ret).cumprod()

    # Benchmark: buy-and-hold TQQQ
    benchmark_equity = (1.0 + tqqq_ret).cumprod()

    # Metrics
    periods = {
        "Full Period": (df.index[0], df.index[-1]),
        "COVID (2020)": (pd.Timestamp("2020-01-01"), pd.Timestamp("2020-12-31")),
        "Bear (2022)": (pd.Timestamp("2022-01-01"), pd.Timestamp("2022-12-31")),
        "Bull (2023-2024)": (pd.Timestamp("2023-01-01"), pd.Timestamp("2024-12-31")),
    }

    results: dict[str, dict[str, float]] = {}
    for period_name, (start, end) in periods.items():
        sub_port = portfolio_equity.loc[start:end]
        sub_bench = benchmark_equity.loc[start:end]
        if len(sub_port) < 2:
            continue
        results[period_name] = {
            "portfolio_cagr": _cagr(sub_port),
            "benchmark_cagr": _cagr(sub_bench),
            "portfolio_mdd": _max_dd(sub_port),
            "benchmark_mdd": _max_dd(sub_bench),
            "excess_return": _cagr(sub_port) - _cagr(sub_bench),
        }

    # Regime distribution
    regime_counts = df["regime"].value_counts().to_dict()
    total = len(df)

    return {
        "period_metrics": results,
        "regime_distribution": {k: v / total for k, v in regime_counts.items()},
        "avg_exposure": float(exposure.mean()),
        "delever_scalar": delever_scalar,
        "crisis_scalar": crisis_scalar,
    }


def _cagr(eq: pd.Series) -> float:
    nonzero = eq[eq > 0]
    if len(nonzero) < 2:
        return 0.0
    total_ret = nonzero.iloc[-1] / nonzero.iloc[0] - 1.0
    years = len(nonzero) / 252
    return (1.0 + total_ret) ** (1.0 / years) - 1.0 if years > 0 else 0.0


def _max_dd(eq: pd.Series) -> float:
    if len(eq) < 2:
        return 0.0
    peak = eq.expanding().max()
    return float(((eq - peak) / peak).min())


# ---------------------------------------------------------------------------
# Parameter sweep
# ---------------------------------------------------------------------------


def sweep_parameters(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Test different delever/crisis scalar combinations."""
    results = []
    for delever in [0.75, 0.50, 0.35, 0.25, 0.0]:
        for crisis in [0.25, 0.0]:
            r = run_backtest(df, delever_scalar=delever, crisis_scalar=crisis)
            full = r["period_metrics"].get("Full Period", {})
            results.append({
                "delever": delever,
                "crisis": crisis,
                "portfolio_cagr": full.get("portfolio_cagr", 0),
                "benchmark_cagr": full.get("benchmark_cagr", 0),
                "portfolio_mdd": full.get("portfolio_mdd", 0),
                "benchmark_mdd": full.get("benchmark_mdd", 0),
                "avg_exposure": r["avg_exposure"],
            })
    return results


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def print_report(df: pd.DataFrame, base_result: dict, sweep: list[dict]) -> None:
    print()
    print("=" * 80)
    print("  MACRO RISK GOVERNOR PARAMETER SENSITIVITY BACKTEST (2010-2026)")
    print("=" * 80)
    print()

    # Regime distribution
    print("  Regime Distribution (score >= 3 watch, >= 5 delever, >= 7 crisis):")
    for regime, pct in base_result["regime_distribution"].items():
        bar = "█" * max(1, int(pct * 50))
        print(f"    {regime:<12s}: {pct:>6.1%} {bar}")
    print()

    # Period metrics
    print("  Base Scenario (delever=0.50, crisis=0.00):")
    print(f"  {'Period':<20s} {'Portfolio':>10s} {'Benchmark':>10s} {'MDD(P)':>8s} {'MDD(B)':>8s}")
    print("  " + "-" * 56)
    for period, m in base_result["period_metrics"].items():
        print(f"  {period:<20s} {m['portfolio_cagr']:>9.1%} {m['benchmark_cagr']:>9.1%} "
              f"{m['portfolio_mdd']:>7.1%} {m['benchmark_mdd']:>7.1%}")
    print()

    # Parameter sweep
    print("  Parameter Sweep (Full Period):")
    print(f"  {'Delever':>8s} {'Crisis':>8s} {'CAGR':>8s} {'MDD':>8s} {'AvgExp':>8s}")
    print("  " + "-" * 40)
    for r in sorted(sweep, key=lambda x: (-x["portfolio_cagr"], x["portfolio_mdd"])):
        print(f"  {r['delever']:>7.0%} {r['crisis']:>8.0%} "
              f"{r['portfolio_cagr']:>7.1%} {r['portfolio_mdd']:>7.1%} "
              f"{r['avg_exposure']:>7.1%}")

    # Best
    best = max(sweep, key=lambda x: x["portfolio_cagr"] / max(abs(x["portfolio_mdd"]), 0.01))
    print(f"\n  Best by risk-adjusted return: delever={best['delever']:.0%}, "
          f"crisis={best['crisis']:.0%} (CAGR={best['portfolio_cagr']:.1%}, MDD={best['portfolio_mdd']:.1%})")
    print()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    print("Loading data...", file=sys.stderr)
    data = load_data()
    print(f"  QQQ: {len(data['qqq'])} days", file=sys.stderr)

    print("Computing indicators...", file=sys.stderr)
    df = compute_indicators(data)
    print(f"  Valid rows: {len(df)}", file=sys.stderr)

    print("Running backtest...", file=sys.stderr)
    base = run_backtest(df)
    sweep = sweep_parameters(df)

    if args.json:
        import json
        output = {"base": base["period_metrics"], "sweep": sweep}
        json.dump(output, sys.stdout, indent=2, default=str)
    else:
        print_report(df, base, sweep)


if __name__ == "__main__":
    main()
