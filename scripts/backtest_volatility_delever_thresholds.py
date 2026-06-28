"""Volatility delever threshold validation backtest.

Tests the hard/soft filter thresholds against historical SOXX data to
check whether:
1. The delever triggers (drawdown=-0.18, vol_ratio=1.65, VIX=35) catch real
   drawdowns before they deepen.
2. The rebound confirmation logic avoids whipsaw re-entries.
3. Different threshold combinations produce better risk-adjusted returns.

Usage
-----
    cd QuantStrategyPlugins
    PYTHONPATH=src python scripts/backtest_volatility_delever_thresholds.py
"""

from __future__ import annotations

import argparse
import math
import sys
from typing import Any

import numpy as np
import pandas as pd

# Default thresholds (matching volatility_delever_price_rebound.py)
DEFAULT_TREND_MA = 140
DEFAULT_DRAWDOWN_LIMIT = -0.18
DEFAULT_VOL_RATIO_THRESHOLD = 1.65
DEFAULT_VIX_CRISIS = 35
DEFAULT_VIX_STRESSED = 28


def load_data() -> dict[str, pd.Series]:
    try:
        import yfinance as yf
    except ImportError:
        print("yfinance required", file=sys.stderr)
        sys.exit(1)

    data: dict[str, pd.Series] = {}
    for key, sym in [("soxx", "SOXX"), ("soxl", "SOXL"), ("vix", "^VIX")]:
        raw = yf.download(sym, start="2015-01-01", end="2026-06-28",
                          auto_adjust=True, progress=False, threads=False)
        close = raw["Close"].copy()
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        data[key] = close.astype(float).dropna()
    return data


def _sma(s: pd.Series, w: int) -> pd.Series:
    return s.rolling(w, min_periods=w).mean()


def compute_signals(data: dict[str, pd.Series],
                    trend_ma: int = DEFAULT_TREND_MA,
                    dd_limit: float = DEFAULT_DRAWDOWN_LIMIT,
                    vol_ratio: float = DEFAULT_VOL_RATIO_THRESHOLD,
                    vix_crisis: float = DEFAULT_VIX_CRISIS,
                    vix_stressed: float = DEFAULT_VIX_STRESSED,
                    ) -> pd.DataFrame:
    soxx = data["soxx"]
    vix = data["vix"]

    idx = soxx.index.intersection(vix.index).sort_values()
    df = pd.DataFrame(index=idx)
    df["soxx"] = soxx.reindex(idx)
    df["vix"] = vix.reindex(idx)

    # Trend
    df["trend_ma"] = _sma(df["soxx"], trend_ma)
    df["trend_ok"] = df["soxx"] >= df["trend_ma"]

    # Drawdown from 252-day high
    high252 = df["soxx"].rolling(252, min_periods=63).max()
    df["dd_252"] = df["soxx"] / high252 - 1.0

    # Realized vol ratio: 21d / 252d
    ret = df["soxx"].pct_change()
    vol21 = ret.rolling(21).std() * math.sqrt(252)
    vol252 = ret.rolling(252, min_periods=63).std() * math.sqrt(252)
    df["vol_ratio"] = vol21 / vol252.replace(0, np.nan)

    # Hard filters
    df["hard_trend"] = ~df["trend_ok"]
    df["hard_dd"] = df["dd_252"] <= dd_limit
    df["hard_vix"] = df["vix"] >= vix_crisis
    df["hard_any"] = df["hard_trend"] | df["hard_dd"] | df["hard_vix"]

    # Soft filters
    df["soft_dd"] = df["dd_252"] <= dd_limit / 1.5
    df["soft_vix"] = df["vix"] >= vix_stressed
    df["soft_vol"] = df["vol_ratio"] >= vol_ratio
    df["soft_any"] = df["soft_dd"] | df["soft_vix"] | df["soft_vol"]

    # Delever trigger: hard OR (soft AND trend_ok)
    df["delever"] = df["hard_any"] | (df["soft_any"] & ~df["hard_any"])

    # Rebound: trend recovered + soft conditions cleared
    df["rebound"] = df["trend_ok"] & ~df["soft_dd"] & ~df["soft_vix"] & ~df["soft_vol"]

    return df.dropna()


def run_backtest(df: pd.DataFrame, retention_ratio: float = 0.50) -> dict[str, Any]:
    """Simulate SOXL exposure with delever/rebound logic."""
    soxx_ret = df["soxx"].pct_change()
    soxl_ret = soxx_ret * 3.0  # 3x leveraged

    # Exposure: 1.0 normally, retention_ratio when delevered
    exposure = pd.Series(1.0, index=df.index)
    prev_delever = df["delever"].shift(1).fillna(False)
    prev_rebound = df["rebound"].shift(1).fillna(False)

    in_delever = False
    for i in range(1, len(df)):
        if prev_delever.iloc[i]:
            in_delever = True
        if in_delever and prev_rebound.iloc[i]:
            in_delever = False
        exposure.iloc[i] = retention_ratio if in_delever else 1.0

    port_ret = soxl_ret * exposure
    port_eq = (1.0 + port_ret).cumprod()
    bench_eq = (1.0 + soxl_ret).cumprod()

    # Count delever episodes
    delever_episodes = 0
    in_ep = False
    for i in range(len(df)):
        if df["delever"].iloc[i] and not in_ep:
            delever_episodes += 1
            in_ep = True
        if df["rebound"].iloc[i] and in_ep:
            in_ep = False

    periods = {
        "Full": (df.index[0], df.index[-1]),
        "COVID (2020)": (pd.Timestamp("2020-01-01"), pd.Timestamp("2020-12-31")),
        "Bear (2022)": (pd.Timestamp("2022-01-01"), pd.Timestamp("2022-12-31")),
        "Bull (2023-2024)": (pd.Timestamp("2023-01-01"), pd.Timestamp("2024-12-31")),
    }

    results: dict[str, dict] = {}
    for name, (s, e) in periods.items():
        sp = port_eq.loc[s:e]
        sb = bench_eq.loc[s:e]
        if len(sp) < 2:
            continue
        results[name] = {
            "port_cagr": _cagr(sp), "bench_cagr": _cagr(sb),
            "port_mdd": _max_dd(sp), "bench_mdd": _max_dd(sb),
        }

    return {
        "periods": results,
        "delever_episodes": delever_episodes,
        "avg_exposure": float(exposure.mean()),
        "delever_pct": float(df["delever"].mean()),
        "retention": retention_ratio,
    }


def _cagr(eq):
    nz = eq[eq > 0]
    if len(nz) < 2: return 0.0
    tr = nz.iloc[-1] / nz.iloc[0] - 1.0
    y = len(nz) / 252
    return (1 + tr) ** (1 / y) - 1 if y > 0 else 0.0


def _max_dd(eq):
    if len(eq) < 2: return 0.0
    return float(((eq - eq.expanding().max()) / eq.expanding().max()).min())


def sweep_thresholds(df: pd.DataFrame) -> list[dict]:
    results = []
    for dd in [-0.22, -0.18, -0.14, -0.10]:
        for vol_r in [1.85, 1.65, 1.45, 1.25]:
            for retention in [0.60, 0.50, 0.40, 0.25]:
                signals = compute_signals(
                    data, dd_limit=dd, vol_ratio=vol_r,
                )
                r = run_backtest(signals, retention_ratio=retention)
                full = r["periods"].get("Full", {})
                results.append({
                    "dd_limit": dd, "vol_ratio": vol_r, "retention": retention,
                    "port_cagr": full.get("port_cagr", 0),
                    "port_mdd": full.get("port_mdd", 0),
                    "bench_mdd": full.get("bench_mdd", 0),
                    "episodes": r["delever_episodes"],
                    "delever_pct": r["delever_pct"],
                })
    return results


def print_report(base: dict, sweep: list[dict]) -> None:
    print()
    print("=" * 80)
    print("  VOLATILITY DELEVER THRESHOLD BACKTEST (2015-2026)")
    print("=" * 80)
    print(f"  Defaults: dd_limit=-0.18, vol_ratio=1.65, retention=0.50")
    print(f"  Delever episodes: {base['delever_episodes']}, "
          f"delever % of days: {base['delever_pct']:.1%}")
    print()

    print("  Base Scenario Period Metrics:")
    print(f"  {'Period':<20s} {'Port CAGR':>10s} {'Bench CAGR':>10s} {'Port MDD':>8s} {'Bench MDD':>8s}")
    print("  " + "-" * 56)
    for name, m in base["periods"].items():
        print(f"  {name:<20s} {m['port_cagr']:>9.1%} {m['bench_cagr']:>9.1%} "
              f"{m['port_mdd']:>7.1%} {m['bench_mdd']:>7.1%}")
    print()

    # Top 5 by Calmar
    print("  Top 5 Parameter Combinations (by Calmar):")
    sorted_r = sorted(sweep, key=lambda x: x["port_cagr"] / max(abs(x["port_mdd"]), 0.01), reverse=True)
    print(f"  {'DD':>8s} {'VolR':>8s} {'Ret':>8s} {'CAGR':>8s} {'MDD':>8s} {'Episodes':>9s}")
    print("  " + "-" * 49)
    for r in sorted_r[:5]:
        print(f"  {r['dd_limit']:>7.0%} {r['vol_ratio']:>7.2f} {r['retention']:>7.0%} "
              f"{r['port_cagr']:>7.1%} {r['port_mdd']:>7.1%} {r['episodes']:>8}")
    print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    global data
    print("Loading...", file=sys.stderr)
    data = load_data()

    print("Computing signals...", file=sys.stderr)
    df = compute_signals(data)
    base = run_backtest(df)

    print("Sweeping parameters...", file=sys.stderr)
    sweep = sweep_thresholds(df)

    if args.json:
        import json
        json.dump({"base": base["periods"], "sweep": sweep}, sys.stdout, indent=2, default=str)
    else:
        print_report(base, sweep)


if __name__ == "__main__":
    main()
