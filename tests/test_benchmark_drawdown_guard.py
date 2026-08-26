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
