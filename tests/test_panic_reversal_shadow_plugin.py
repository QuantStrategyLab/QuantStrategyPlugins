from __future__ import annotations

import json

import pandas as pd

from quant_strategy_plugins.panic_reversal_shadow_plugin import (
    ACTION_NOTIFY_MANUAL_REVIEW,
    ROUTE_PANIC_REVERSAL,
    build_panic_reversal_shadow_signal,
    run_panic_reversal_event_study,
    write_panic_reversal_shadow_outputs,
)


def _panic_reversal_prices(*, confirmed: bool = True) -> pd.DataFrame:
    dates = pd.bdate_range("2025-04-01", periods=12)
    qqq_path = [100.0, 96.0, 92.0, 88.0, 84.0, 82.0, 84.0, 87.0, 90.0, 92.0, 94.0, 96.0]
    if confirmed:
        tqqq_path = [100.0, 88.0, 78.0, 70.0, 64.0, 60.0, 66.0, 74.0, 82.0, 88.0, 94.0, 100.0]
    else:
        tqqq_path = [100.0, 88.0, 78.0, 70.0, 64.0, 60.0, 61.0, 62.0, 62.0, 63.0, 64.0, 65.0]
    vix_path = [20.0, 32.0, 45.0, 54.0, 60.0, 58.0, 55.0, 48.0, 45.0, 42.0, 39.0, 35.0]
    vix3m_path = [22.0, 28.0, 38.0, 45.0, 48.0, 47.0, 45.0, 41.0, 39.0, 37.0, 35.0, 33.0]
    rows: list[dict[str, object]] = []
    for idx, as_of in enumerate(dates):
        rows.append({"symbol": "QQQ", "as_of": as_of, "close": qqq_path[idx], "volume": 1_000_000})
        rows.append({"symbol": "TQQQ", "as_of": as_of, "close": tqqq_path[idx], "volume": 1_000_000})
        rows.append({"symbol": "VIX", "as_of": as_of, "close": vix_path[idx], "volume": 0})
        rows.append({"symbol": "VIX3M", "as_of": as_of, "close": vix3m_path[idx], "volume": 0})
    return pd.DataFrame(rows)


def test_panic_reversal_shadow_routes_confirmed_vix_reversal_to_manual_review() -> None:
    payload = build_panic_reversal_shadow_signal(
        _panic_reversal_prices(),
        as_of="2025-04-10",
        start_date="2025-04-01",
    )

    assert payload["canonical_route"] == ROUTE_PANIC_REVERSAL
    assert payload["suggested_action"] == ACTION_NOTIFY_MANUAL_REVIEW
    assert payload["manual_review_required"] is True
    assert payload["panic_reversal_context_active"] is True
    assert payload["would_trade_if_enabled"] is False
    assert "panic_reversal" in payload["reason_codes"]
    assert payload["reversal_confirmation"]["confirmed"] is True
    assert payload["panic_reversal_quality"]["checks"]["vix_reversed_from_high"] is True
    assert payload["panic_reversal_quality"]["checks"]["benchmark_rebound_from_low"] is True
    assert payload["panic_reversal_quality"]["checks"]["attack_rebound_from_low"] is True
    assert payload["execution_controls"]["broker_order_allowed"] is False
    assert payload["execution_controls"]["live_allocation_mutation_allowed"] is False
    assert payload["execution_controls"]["allocation_recommendation_allowed"] is False


def test_panic_reversal_shadow_waits_for_attack_price_confirmation() -> None:
    payload = build_panic_reversal_shadow_signal(
        _panic_reversal_prices(confirmed=False),
        as_of="2025-04-10",
        start_date="2025-04-01",
    )

    assert payload["canonical_route"] == "watch"
    assert payload["suggested_action"] == "watch_only"
    assert payload["manual_review_required"] is False
    assert payload["panic_reversal_context_active"] is False
    assert payload["would_trade_if_enabled"] is False
    assert payload["reversal_confirmation"]["confirmed"] is False
    assert payload["panic_reversal_quality"]["checks"]["attack_rebound_from_low"] is False
    assert "attack rebound from recent low below threshold" in payload["suppression_reason"]


def test_panic_reversal_shadow_writes_artifacts(tmp_path) -> None:
    payload = build_panic_reversal_shadow_signal(
        _panic_reversal_prices(),
        as_of="2025-04-10",
        start_date="2025-04-01",
    )

    paths = write_panic_reversal_shadow_outputs(payload, tmp_path)

    assert paths["latest_signal"].exists()
    assert paths["signal_json"].exists()
    assert paths["signal_csv"].exists()
    assert paths["evidence_csv"].exists()
    latest = json.loads(paths["latest_signal"].read_text(encoding="utf-8"))
    assert latest["canonical_route"] == ROUTE_PANIC_REVERSAL
    assert latest["execution_controls"]["broker_order_allowed"] is False


def test_panic_reversal_event_study_reports_signal_windows() -> None:
    result = run_panic_reversal_event_study(
        _panic_reversal_prices(),
        start_date="2025-04-01",
        horizons=(1, 3),
        entry_lag_trading_days=0,
        min_gap_trading_days=5,
    )

    assert not result["signals"].empty
    assert set(result["event_windows"]["symbol"]) == {"QQQ", "TQQQ"}
    assert set(result["summary"]["horizon_days"]) == {1, 3}
