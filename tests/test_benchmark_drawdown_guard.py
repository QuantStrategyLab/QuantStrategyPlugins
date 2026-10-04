from __future__ import annotations

import pandas as pd
import pytest

from quant_strategy_plugins.benchmark_drawdown_guard import (
    ROUTE_BLOCKED,
    ROUTE_NO_ACTION,
    ROUTE_RISK_OFF,
    ROUTE_RISK_REDUCED,
    build_benchmark_drawdown_guard_signal,
)
from quant_strategy_plugins.strategy_plugin_runner import _build_market_regime_control_payload


def _prices(closes: list[float]) -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-02", periods=len(closes))
    return pd.DataFrame(
        {
            "symbol": "QQQ",
            "as_of": dates,
            "close": closes,
        }
    )


def _guard(prices: pd.DataFrame, **overrides: object) -> dict[str, object]:
    config: dict[str, object] = {
        "benchmark_symbol": "QQQ",
        "as_of": "2026-02-12",
        "drawdown_lookback_sessions": 20,
        "soft_drawdown_threshold": -0.05,
        "hard_drawdown_threshold": -0.10,
        "soft_risk_asset_scalar": 0.50,
        "hard_risk_asset_scalar": 0.0,
        "max_price_age_days": 3,
    }
    config.update(overrides)
    return build_benchmark_drawdown_guard_signal(prices, **config)  # type: ignore[arg-type]


def _mixed_prices(benchmark: list[object], *, input_shape: str) -> pd.DataFrame:
    wide = pd.DataFrame(
        {"QQQ": benchmark, "SPY": [200.0] * len(benchmark)},
        index=pd.date_range("2026-01-02", periods=len(benchmark), name="as_of"),
    )
    if input_shape == "long":
        return wide.reset_index().melt(id_vars="as_of", var_name="symbol", value_name="close")
    return wide


def _assert_research_only(payload: dict[str, object]) -> None:
    assert payload["execution_controls"] == {
        "broker_order_allowed": False,
        "live_allocation_mutation_allowed": False,
        "strategy_opt_in_required": True,
    }


@pytest.mark.parametrize("input_shape", ["long", "wide"])
def test_guard_does_not_use_fresh_unrelated_prices_for_benchmark_freshness(input_shape: str) -> None:
    payload = _guard(
        _mixed_prices([110.0, 100.0, None, None], input_shape=input_shape),
        as_of="2026-01-05",
        drawdown_lookback_sessions=2,
        max_price_age_days=0,
    )

    assert payload["canonical_route"] == ROUTE_BLOCKED
    assert payload["as_of"] == "2026-01-03"
    assert payload["reason_codes"] == ["benchmark_stale"]
    assert payload["kill_switch_active"] is True
    assert payload["would_trade_if_enabled"] is False
    _assert_research_only(payload)


@pytest.mark.parametrize("input_shape", ["long", "wide"])
@pytest.mark.parametrize("as_of", ["2026-01-05", None])
@pytest.mark.parametrize(
    ("closes", "max_age", "expected_as_of", "expected_age", "expected_route"),
    [
        ([110.0, 110.0, 110.0, 110.0], 0, "2026-01-05", 0, ROUTE_NO_ACTION),
        ([110.0, 110.0, 110.0, None], 2, "2026-01-04", 1, ROUTE_NO_ACTION),
        ([110.0, 100.0, None, None], 2, "2026-01-03", 2, ROUTE_RISK_REDUCED),
        ([110.0, 100.0, "invalid", "invalid"], 2, "2026-01-03", 2, ROUTE_RISK_REDUCED),
    ],
)
def test_guard_reports_actual_benchmark_observation_and_inclusive_age_boundary(
    input_shape: str,
    as_of: str | None,
    closes: list[object],
    max_age: int,
    expected_as_of: str,
    expected_age: int,
    expected_route: str,
) -> None:
    payload = _guard(
        _mixed_prices(closes, input_shape=input_shape),
        as_of=as_of,
        drawdown_lookback_sessions=2,
        max_price_age_days=max_age,
    )

    assert payload["canonical_route"] == expected_route
    assert payload["as_of"] == expected_as_of
    assert payload["data_quality"] == {"status": "READY", "price_age_days": expected_age, "lookback_sessions": 2}
    _assert_research_only(payload)


@pytest.mark.parametrize("input_shape", ["long", "wide"])
def test_guard_ignores_future_benchmark_observations_when_cutoff_price_is_missing(input_shape: str) -> None:
    payload = _guard(
        _mixed_prices([110.0, 100.0, None, 1.0], input_shape=input_shape),
        as_of="2026-01-04",
        drawdown_lookback_sessions=2,
        max_price_age_days=1,
    )

    assert payload["canonical_route"] == ROUTE_RISK_REDUCED
    assert payload["as_of"] == "2026-01-03"
    assert payload["data_quality"]["price_age_days"] == 1  # type: ignore[index]
    assert payload["metrics"]["rolling_drawdown"] == pytest.approx(100.0 / 110.0 - 1.0)  # type: ignore[index]
    _assert_research_only(payload)


@pytest.mark.parametrize("input_shape", ["long", "wide"])
@pytest.mark.parametrize(
    ("closes", "as_of", "expected_as_of", "long_reason"),
    [
        ([None, None, None, None], "2026-01-05", "2026-01-05", "benchmark_missing"),
        ([None, None, 110.0, 100.0], "2026-01-03", "2026-01-03", "benchmark_history_incomplete"),
        ([110.0, 100.0, 110.0, 100.0], "2026-01-01", "2026-01-01", "benchmark_history_unavailable"),
    ],
)
def test_guard_preserves_fail_closed_reasons_when_no_benchmark_observation_is_available(
    input_shape: str, closes: list[object], as_of: str, expected_as_of: str, long_reason: str
) -> None:
    payload = _guard(
        _mixed_prices(closes, input_shape=input_shape),
        as_of=as_of,
        drawdown_lookback_sessions=2,
        max_price_age_days=0,
    )
    expected_reason = (
        "benchmark_history_incomplete" if input_shape == "wide" and long_reason == "benchmark_missing" else long_reason
    )

    assert payload["canonical_route"] == ROUTE_BLOCKED
    assert payload["as_of"] == expected_as_of
    assert payload["reason_codes"] == [expected_reason]
    assert payload["data_quality"]["status"] == "PARKED"  # type: ignore[index]
    assert payload["would_trade_if_enabled"] is False
    _assert_research_only(payload)


@pytest.mark.parametrize("input_shape", ["long", "wide"])
@pytest.mark.parametrize("invalid_price", [float("inf"), float("-inf"), 0.0, -0.0, -1.0])
@pytest.mark.parametrize("position", [0, 1, 2])
def test_guard_parks_nonfinite_or_nonpositive_prices_anywhere_in_consumed_lookback(
    input_shape: str, invalid_price: float, position: int
) -> None:
    closes: list[object] = [110.0, 110.0, 100.0]
    closes[position] = invalid_price
    payload = _guard(
        _mixed_prices(closes, input_shape=input_shape),
        as_of="2026-01-04",
        drawdown_lookback_sessions=3,
        max_price_age_days=0,
    )

    assert payload["canonical_route"] == ROUTE_BLOCKED
    assert payload["as_of"] == "2026-01-04"
    assert payload["reason_codes"] == ["benchmark_price_invalid"]
    assert payload["data_quality"]["status"] == "PARKED"  # type: ignore[index]
    assert payload["kill_switch_active"] is True
    assert payload["risk_asset_scalar"] == 0.0
    assert payload["would_trade_if_enabled"] is False
    _assert_research_only(payload)


@pytest.mark.parametrize("input_shape", ["long", "wide"])
@pytest.mark.parametrize("invalid_price", [float("inf"), float("-inf"), 0.0, -0.0, -1.0])
@pytest.mark.parametrize("position", ["before_lookback", "after_cutoff"])
def test_guard_does_not_consume_invalid_prices_outside_lookback_or_requested_cutoff(
    input_shape: str, invalid_price: float, position: str
) -> None:
    closes = [invalid_price, 110.0, 100.0] if position == "before_lookback" else [110.0, 100.0, invalid_price]
    as_of = "2026-01-04" if position == "before_lookback" else "2026-01-03"
    payload = _guard(
        _mixed_prices(closes, input_shape=input_shape),
        as_of=as_of,
        drawdown_lookback_sessions=2,
        max_price_age_days=0,
    )

    assert payload["canonical_route"] == ROUTE_RISK_REDUCED
    assert payload["as_of"] == as_of
    assert payload["data_quality"]["status"] == "READY"  # type: ignore[index]
    assert payload["metrics"]["rolling_drawdown"] == pytest.approx(100.0 / 110.0 - 1.0)  # type: ignore[index]
    _assert_research_only(payload)


def test_guard_preserves_risk_when_benchmark_drawdown_is_below_soft_threshold() -> None:
    payload = _guard(_prices([100.0 + index for index in range(30)]))

    assert payload["canonical_route"] == ROUTE_NO_ACTION
    assert payload["risk_asset_scalar"] == 1.0
    assert payload["execution_controls"]["broker_order_allowed"] is False  # type: ignore[index]


def test_guard_reduces_all_risk_assets_on_soft_benchmark_drawdown() -> None:
    payload = _guard(_prices([100.0 + index for index in range(20)] + [116.0] * 5 + [113.0] * 5))

    assert payload["canonical_route"] == ROUTE_RISK_REDUCED
    assert payload["risk_asset_scalar"] == 0.50
    assert payload["reason_codes"] == ["benchmark_drawdown_soft"]


def test_guard_moves_to_defense_on_hard_benchmark_drawdown() -> None:
    payload = _guard(_prices([100.0 + index for index in range(20)] + [100.0] * 10))

    assert payload["canonical_route"] == ROUTE_RISK_OFF
    assert payload["risk_asset_scalar"] == 0.0
    assert payload["reason_codes"] == ["benchmark_drawdown_hard"]


@pytest.mark.parametrize(
    ("prices", "overrides", "reason"),
    [
        (pd.DataFrame(), {}, "benchmark_history_unavailable"),
        (_prices([100.0] * 10), {"as_of": "2026-01-15"}, "benchmark_history_incomplete"),
        (_prices([100.0] * 30), {"benchmark_symbol": "SOXX"}, "benchmark_missing"),
        (_prices([100.0] * 30), {"as_of": "2026-03-01", "max_price_age_days": 1}, "benchmark_stale"),
    ],
)
def test_guard_fails_closed_on_unusable_benchmark_input(
    prices: pd.DataFrame, overrides: dict[str, object], reason: str
) -> None:
    payload = _guard(prices, **overrides)

    assert payload["canonical_route"] == ROUTE_BLOCKED
    assert payload["kill_switch_active"] is True
    assert payload["reason_codes"] == [reason]


def test_guard_rejects_implicit_or_incoherent_policy() -> None:
    with pytest.raises(ValueError, match="hard_drawdown_threshold"):
        _guard(_prices([100.0] * 30), hard_drawdown_threshold=-0.04)
    with pytest.raises(ValueError, match="hard_risk_asset_scalar"):
        _guard(_prices([100.0] * 30), hard_risk_asset_scalar=0.75)


def test_unified_market_regime_requires_an_explicit_policy_to_mount_the_guard() -> None:
    config = {
        "crisis_enabled": False,
        "macro_enabled": False,
        "taco_enabled": False,
        "panic_reversal_enabled": False,
        "benchmark_drawdown_guard_enabled": True,
        "benchmark_guard_benchmark_symbol": "QQQ",
        "benchmark_guard_drawdown_lookback_sessions": 20,
        "benchmark_guard_soft_drawdown_threshold": -0.05,
        "benchmark_guard_hard_drawdown_threshold": -0.10,
        "benchmark_guard_soft_risk_asset_scalar": 0.50,
        "benchmark_guard_hard_risk_asset_scalar": 0.0,
        "benchmark_guard_max_price_age_days": 3,
        "as_of": "2026-02-12",
    }

    payload = _build_market_regime_control_payload(
        _prices([100.0 + index for index in range(20)] + [116.0] * 5 + [113.0] * 5), config
    )

    assert payload["canonical_route"] == ROUTE_RISK_REDUCED
    assert payload["position_control"]["risk_asset_scalar"] == 0.5
    with pytest.raises(ValueError, match="explicit frozen policy"):
        _build_market_regime_control_payload(_prices([100.0] * 30), {"benchmark_drawdown_guard_enabled": True})


def test_unified_market_regime_preserves_fail_closed_scalars_when_guard_data_is_unavailable() -> None:
    config = {
        "crisis_enabled": False,
        "macro_enabled": False,
        "taco_enabled": False,
        "panic_reversal_enabled": False,
        "benchmark_drawdown_guard_enabled": True,
        "benchmark_guard_benchmark_symbol": "QQQ",
        "benchmark_guard_drawdown_lookback_sessions": 20,
        "benchmark_guard_soft_drawdown_threshold": -0.05,
        "benchmark_guard_hard_drawdown_threshold": -0.10,
        "benchmark_guard_soft_risk_asset_scalar": 0.50,
        "benchmark_guard_hard_risk_asset_scalar": 0.0,
        "benchmark_guard_max_price_age_days": 3,
        "as_of": "2026-02-12",
    }

    payload = _build_market_regime_control_payload(pd.DataFrame(), config)

    assert payload["canonical_route"] == ROUTE_BLOCKED
    assert payload["position_control"]["risk_budget_scalar"] == 0.0
    assert payload["position_control"]["leverage_scalar"] == 0.0
    assert payload["position_control"]["risk_asset_scalar"] == 0.0
    assert payload["position_control"]["crisis_defense_required"] is True
    assert payload["execution_controls"]["broker_order_allowed"] is False


def test_unified_market_regime_parks_stale_benchmark_despite_fresh_unrelated_prices() -> None:
    config = {
        "crisis_enabled": False,
        "macro_enabled": False,
        "taco_enabled": False,
        "panic_reversal_enabled": False,
        "benchmark_drawdown_guard_enabled": True,
        "benchmark_guard_benchmark_symbol": "QQQ",
        "benchmark_guard_drawdown_lookback_sessions": 2,
        "benchmark_guard_soft_drawdown_threshold": -0.05,
        "benchmark_guard_hard_drawdown_threshold": -0.10,
        "benchmark_guard_soft_risk_asset_scalar": 0.50,
        "benchmark_guard_hard_risk_asset_scalar": 0.0,
        "benchmark_guard_max_price_age_days": 0,
        "as_of": "2026-01-05",
    }

    payload = _build_market_regime_control_payload(
        _mixed_prices([110.0, 100.0, None, None], input_shape="long"), config
    )

    assert payload["canonical_route"] == ROUTE_BLOCKED
    assert payload["position_control"]["risk_budget_scalar"] == 0.0
    assert payload["position_control"]["leverage_scalar"] == 0.0
    assert payload["position_control"]["risk_asset_scalar"] == 0.0
    assert payload["component_signals"]["benchmark_guard"]["as_of"] == "2026-01-03"
    assert payload["component_signals"]["benchmark_guard"]["reason_codes"] == ["benchmark_stale"]
    assert payload["execution_controls"]["broker_order_allowed"] is False
