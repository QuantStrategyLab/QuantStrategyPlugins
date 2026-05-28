from __future__ import annotations

import json

import pandas as pd

from quant_strategy_plugins.macro_risk_governor_plugin import (
    ROUTE_CRISIS,
    ROUTE_DELEVER,
    ROUTE_NO_ACTION,
    ROUTE_WATCH,
    build_macro_risk_governor_signal,
    write_macro_risk_governor_outputs,
)


def _macro_prices(*, stress: bool = False) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=260)
    rows: list[dict[str, object]] = []
    qqq = pd.Series([100.0 + idx * 0.10 for idx in range(len(dates))], index=dates)
    vix = pd.Series(15.0, index=dates)
    hyg = pd.Series(100.0, index=dates)
    ief = pd.Series(100.0, index=dates)
    if stress:
        qqq.iloc[230:] = pd.Series(
            [125.0 - idx * (45.0 / 29.0) for idx in range(30)],
            index=dates[230:],
        )
        vix.iloc[-6:] = [24.0, 27.0, 31.0, 34.0, 38.0, 41.0]
        hyg.iloc[-22:] = pd.Series(
            [100.0 - idx * (9.0 / 21.0) for idx in range(22)],
            index=dates[-22:],
        )
        ief.iloc[-22:] = pd.Series(
            [100.0 + idx * (3.0 / 21.0) for idx in range(22)],
            index=dates[-22:],
        )
    prices = {
        "QQQ": qqq,
        "TQQQ": qqq * 3.0,
        "VIX": vix,
        "HYG": hyg,
        "IEF": ief,
    }
    for symbol, series in prices.items():
        for as_of, close in series.items():
            rows.append({"symbol": symbol, "as_of": as_of, "close": close, "volume": 1_000_000})
    return pd.DataFrame(rows)


def test_macro_risk_governor_stays_no_action_in_quiet_market() -> None:
    payload = build_macro_risk_governor_signal(_macro_prices(), as_of="2025-12-31")

    assert payload["canonical_route"] == ROUTE_NO_ACTION
    assert payload["suggested_action"] == "no_action"
    assert payload["would_trade_if_enabled"] is False
    assert payload["leverage_scalar"] == 1.0
    assert payload["risk_asset_scalar"] == 1.0


def test_macro_risk_governor_routes_stress_to_delever_when_below_crisis_threshold() -> None:
    payload = build_macro_risk_governor_signal(
        _macro_prices(stress=True),
        as_of="2025-12-31",
        crisis_score_threshold=99.0,
    )

    assert payload["canonical_route"] == ROUTE_DELEVER
    assert payload["suggested_action"] == "delever"
    assert payload["would_trade_if_enabled"] is True
    assert payload["leverage_scalar"] == 0.0
    assert payload["risk_asset_scalar"] == 1.0
    assert "vix_crisis_level" in payload["reason_codes"]
    assert payload["checks"]["pentagon_pizza_watch"]["actionable"] is False


def test_macro_risk_governor_routes_severe_stress_to_crisis() -> None:
    payload = build_macro_risk_governor_signal(_macro_prices(stress=True), as_of="2025-12-31")

    assert payload["canonical_route"] == ROUTE_CRISIS
    assert payload["suggested_action"] == "defend"
    assert payload["would_trade_if_enabled"] is True
    assert payload["leverage_scalar"] == 0.0
    assert payload["risk_asset_scalar"] == 0.0


def test_macro_risk_governor_keeps_pizza_index_watch_only() -> None:
    external_context = pd.DataFrame(
        [
            {
                "as_of": "2025-12-31",
                "pentagon_pizza_index": 3.0,
            }
        ]
    )

    payload = build_macro_risk_governor_signal(
        _macro_prices(),
        external_context=external_context,
        as_of="2025-12-31",
        watch_score_threshold=1.0,
    )

    assert payload["canonical_route"] == ROUTE_WATCH
    assert payload["suggested_action"] == "watch_only"
    assert payload["would_trade_if_enabled"] is False
    assert payload["actionable_score"] == 0.0
    assert payload["checks"]["pentagon_pizza_watch"]["active"] is True
    assert payload["checks"]["pentagon_pizza_watch"]["actionable"] is False


def test_macro_risk_governor_writes_json_csv_and_evidence(tmp_path) -> None:
    payload = build_macro_risk_governor_signal(_macro_prices(stress=True), as_of="2025-12-31")

    paths = write_macro_risk_governor_outputs(payload, tmp_path)

    assert paths["latest_signal"].exists()
    assert paths["signal_json"].exists()
    assert paths["signal_csv"].exists()
    assert paths["evidence_csv"].exists()
    latest = json.loads(paths["latest_signal"].read_text(encoding="utf-8"))
    assert latest["schema_version"] == "macro_risk_governor.v1"
