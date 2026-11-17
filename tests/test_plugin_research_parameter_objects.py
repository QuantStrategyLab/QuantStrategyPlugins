from __future__ import annotations

from dataclasses import FrozenInstanceError, is_dataclass
import inspect

import pandas as pd
import pytest

from quant_strategy_plugins import crisis_response_research as crisis_shim
from quant_strategy_plugins import taco_panic_rebound_overlay_compare as overlay_shim
from quant_strategy_plugins.plugins import crisis_response_research as crisis_impl
from quant_strategy_plugins.plugins import taco_panic_rebound_overlay_compare as overlay_impl
from quant_strategy_plugins.taco_panic_rebound_research import EVENT_KIND_SHOCK, TradeWarEvent


def _synthetic_close_matrix(periods: int = 280) -> pd.DataFrame:
    dates = pd.bdate_range("2018-01-02", periods=periods)
    qqq = pd.Series(100.0, index=dates)
    qqq.iloc[:180] = pd.Series([100.0 + idx * 0.45 for idx in range(180)], index=dates[:180])
    qqq.iloc[180:235] = pd.Series([180.0 - idx * 1.15 for idx in range(55)], index=dates[180:235])
    qqq.iloc[235:] = pd.Series([117.0 + idx * 0.65 for idx in range(periods - 235)], index=dates[235:])

    tqqq = pd.Series(100.0, index=dates)
    tqqq.iloc[:180] = pd.Series([100.0 + idx * 1.10 for idx in range(180)], index=dates[:180])
    tqqq.iloc[180:235] = pd.Series([298.0 - idx * 3.40 for idx in range(55)], index=dates[180:235])
    tqqq.iloc[235:] = pd.Series([111.0 + idx * 1.80 for idx in range(periods - 235)], index=dates[235:])

    xlf = pd.Series(100.0, index=dates)
    xlf.iloc[175:235] = pd.Series([100.0 - idx * 0.70 for idx in range(60)], index=dates[175:235])
    xlf.iloc[235:] = pd.Series([58.0 + idx * 0.25 for idx in range(periods - 235)], index=dates[235:])

    hyg = pd.Series(100.0, index=dates)
    hyg.iloc[175:235] = pd.Series([100.0 - idx * 0.25 for idx in range(60)], index=dates[175:235])
    hyg.iloc[235:] = pd.Series([85.0 + idx * 0.10 for idx in range(periods - 235)], index=dates[235:])

    return pd.DataFrame(
        {
            "QQQ": qqq,
            "TQQQ": tqqq,
            "SPY": qqq * 0.95,
            "SHY": pd.Series(100.0, index=dates),
            "BOXX": pd.Series(100.0, index=dates),
            "XLF": xlf,
            "HYG": hyg,
            "IEF": pd.Series(100.0, index=dates),
        },
        index=dates,
    )


def _synthetic_external_context(index: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "as_of": index,
            "nasdaq_100_trailing_pe": 70.0,
            "nasdaq_100_forward_pe": 50.0,
            "nasdaq_100_cape_proxy": 50.0,
            "unprofitable_growth_proxy": 0.40,
            "nasdaq_100_pct_above_200d": 0.30,
            "nasdaq_100_pct_above_50d": 0.25,
            "nasdaq_100_new_high_new_low_spread": -0.20,
            "nasdaq_100_advance_decline_line_drawdown": -0.15,
            "nasdaq_100_negative_earnings_share": 0.30,
            "nasdaq_100_earnings_revision_3m": -0.10,
            "nasdaq_100_margin_revision_3m": -0.05,
        }
    )


def _synthetic_events(dates: pd.DatetimeIndex) -> tuple[TradeWarEvent, ...]:
    return (
        TradeWarEvent(
            event_id="synthetic-shock-1",
            event_date=str(dates[190].date()),
            kind=EVENT_KIND_SHOCK,
            region="china",
            title="Synthetic tariff escalation shock",
            source="test",
            source_url="https://example.test/shock-1",
        ),
    )


@pytest.mark.parametrize(
    "cls",
    [
        overlay_impl.DualDriveBaseWeightsConfig,
        overlay_impl.OverlayPortfolioConfig,
        overlay_impl.StrategyReturnBundle,
        overlay_impl.OverlayStrategyReturnsSpec,
        crisis_impl.ExternalValuationThresholds,
        crisis_impl.V2ContextOpinionsSpec,
        crisis_impl.UnifiedResponseReturnsSpec,
    ],
)
def test_parameter_objects_are_frozen_and_slotted(cls) -> None:
    assert is_dataclass(cls)
    assert hasattr(cls, "__slots__")


def test_parameter_objects_reject_mutation() -> None:
    cfg = overlay_impl.DualDriveBaseWeightsConfig()
    with pytest.raises(FrozenInstanceError):
        cfg.benchmark_symbol = "SPY"  # type: ignore[misc]

    thresholds = crisis_impl.ExternalValuationThresholds()
    with pytest.raises(FrozenInstanceError):
        thresholds.external_cape_threshold = 99.0  # type: ignore[misc]


def test_converged_function_signatures_and_shim_parity() -> None:
    assert len(inspect.signature(overlay_impl.build_tqqq_growth_income_base_weights).parameters) <= 4
    assert len(inspect.signature(overlay_impl._add_overlay_strategy_returns).parameters) <= 4
    assert len(inspect.signature(crisis_impl._build_v2_context_opinions).parameters) <= 5
    assert len(inspect.signature(crisis_impl._add_unified_response_returns).parameters) <= 4

    assert overlay_shim.__all__ == overlay_impl.__all__
    assert crisis_shim.__all__ == crisis_impl.__all__
    for name in overlay_impl.__all__:
        assert getattr(overlay_shim, name) is getattr(overlay_impl, name)
    for name in crisis_impl.__all__:
        assert getattr(crisis_shim, name) is getattr(crisis_impl, name)


@pytest.mark.parametrize("threshold_mode", ["volatility_scaled", "fixed"])
def test_base_weights_config_matches_legacy_kwargs(threshold_mode: str) -> None:
    close = _synthetic_close_matrix()
    kwargs = dict(
        start_date="2018-02-01",
        end_date=str(close.index[-1].date()),
        benchmark_symbol="QQQ",
        attack_symbol="TQQQ",
        safe_symbol="BOXX",
        cash_symbol="CASH",
        qqq_weight=0.40,
        tqqq_weight=0.40,
        safe_weight=0.15,
        cash_weight=0.05,
        idle_safe_weight=0.95,
        idle_cash_weight=0.05,
        pullback_rebound_window=15,
        pullback_rebound_threshold_mode=threshold_mode,
        pullback_rebound_threshold=0.03,
        pullback_rebound_volatility_multiplier=1.5,
    )
    via_config = overlay_impl.build_tqqq_growth_income_base_weights(
        close,
        overlay_impl.DualDriveBaseWeightsConfig(**kwargs),
    )
    via_legacy = overlay_impl.build_tqqq_growth_income_base_weights(close, **kwargs)
    pd.testing.assert_frame_equal(via_config, via_legacy)


def test_base_weights_rejects_invalid_or_mixed_arguments() -> None:
    close = _synthetic_close_matrix()
    cfg = overlay_impl.DualDriveBaseWeightsConfig()
    with pytest.raises(TypeError):
        overlay_impl.build_tqqq_growth_income_base_weights(close, cfg, start_date="2019-01-01")
    with pytest.raises(TypeError):
        overlay_impl.build_tqqq_growth_income_base_weights(close, unknown_option=True)
    with pytest.raises(TypeError):
        overlay_impl.build_tqqq_growth_income_base_weights(close, "not-a-config")  # type: ignore[arg-type]


def test_add_overlay_strategy_returns_spec_matches_legacy_kwargs() -> None:
    close = _synthetic_close_matrix()
    index = close.index
    returns = close.pct_change(fill_method=None).fillna(0.0).reindex(index).fillna(0.0)
    base_weights = overlay_impl.build_tqqq_growth_income_base_weights(
        close,
        overlay_impl.DualDriveBaseWeightsConfig(start_date=str(index[0].date())),
    ).reindex(index[:-1]).ffill().fillna(0.0)
    overlay_weights = pd.DataFrame(
        {"TQQQ": 0.25, "CASH": 0.75},
        index=index[:-1],
    )
    trades = pd.DataFrame({"signal_date": [str(index[195].date())]})
    taco_result = {"weights_history": overlay_weights, "trades": trades}

    spec_bundle = overlay_impl.StrategyReturnBundle()
    overlay_impl._add_overlay_strategy_returns(
        overlay_impl.OverlayStrategyReturnsSpec(
            scenario_prefix="taco_test",
            taco_result=taco_result,
            returns=returns,
            base_weights=base_weights,
            index=index,
            outputs=spec_bundle,
            portfolio=overlay_impl.OverlayPortfolioConfig(
                overlay_sleeve_ratios=(0.05, 0.10),
                attack_symbol="TQQQ",
                safe_symbol="BOXX",
                cash_symbol="CASH",
                turnover_cost_bps=5.0,
            ),
        )
    )

    legacy_returns: dict[str, pd.Series] = {}
    legacy_weights: dict[str, pd.DataFrame] = {}
    legacy_trades: dict[str, pd.DataFrame] = {}
    overlay_impl._add_overlay_strategy_returns(
        scenario_prefix="taco_test",
        taco_result=taco_result,
        returns=returns,
        base_weights=base_weights,
        returns_by_strategy=legacy_returns,
        weights_by_strategy=legacy_weights,
        trades_by_strategy=legacy_trades,
        index=index,
        overlay_sleeve_ratios=(0.05, 0.10),
        attack_symbol="TQQQ",
        safe_symbol="BOXX",
        cash_symbol="CASH",
        turnover_cost_bps=5.0,
    )

    assert set(spec_bundle.returns_by_strategy) == set(legacy_returns) == {"taco_test_5pct", "taco_test_10pct"}
    for name in spec_bundle.returns_by_strategy:
        pd.testing.assert_series_equal(spec_bundle.returns_by_strategy[name], legacy_returns[name])
        pd.testing.assert_frame_equal(spec_bundle.weights_by_strategy[name], legacy_weights[name])
        pd.testing.assert_frame_equal(spec_bundle.trades_by_strategy[name], legacy_trades[name])


def test_build_v2_context_opinions_spec_matches_legacy_kwargs() -> None:
    close = _synthetic_close_matrix()
    events = _synthetic_events(close.index)
    ext = _synthetic_external_context(close.index)
    price_signal = pd.Series(False, index=close.index)
    price_signal.iloc[195:210] = True

    thresholds = crisis_impl.ExternalValuationThresholds(
        external_trailing_pe_threshold=55.0,
        external_forward_pe_threshold=42.0,
        external_cape_threshold=40.0,
        external_unprofitable_growth_threshold=0.30,
        external_pct_above_200d_threshold=0.45,
        external_pct_above_50d_threshold=0.35,
        external_new_high_new_low_spread_threshold=-0.10,
        external_advance_decline_drawdown_threshold=-0.10,
        external_negative_earnings_share_threshold=0.25,
        external_earnings_revision_3m_threshold=-0.05,
        external_margin_revision_3m_threshold=-0.02,
    )
    spec = crisis_impl.V2ContextOpinionsSpec(
        events=events,
        external_context=ext,
        start_date=str(close.index[0].date()),
        end_date=str(close.index[-1].date()),
        benchmark_symbol="QQQ",
        market_symbol="SPY",
        financial_symbols=("XLF",),
        credit_pairs=(("HYG", "IEF"),),
        rate_symbols=("IEF",),
        external_valuation_mode=crisis_impl.EXTERNAL_VALUATION_MODE_PRICE_OR_EXTERNAL,
        external_thresholds=thresholds,
    )
    opinions_spec, features_spec = crisis_impl._build_v2_context_opinions(close, price_signal, spec)
    opinions_legacy, features_legacy = crisis_impl._build_v2_context_opinions(
        close,
        price_signal,
        events=events,
        external_context=ext,
        start_date=str(close.index[0].date()),
        end_date=str(close.index[-1].date()),
        benchmark_symbol="QQQ",
        market_symbol="SPY",
        financial_symbols=("XLF",),
        credit_pairs=(("HYG", "IEF"),),
        rate_symbols=("IEF",),
        external_valuation_mode=crisis_impl.EXTERNAL_VALUATION_MODE_PRICE_OR_EXTERNAL,
        external_trailing_pe_threshold=55.0,
        external_forward_pe_threshold=42.0,
        external_cape_threshold=40.0,
        external_unprofitable_growth_threshold=0.30,
        external_pct_above_200d_threshold=0.45,
        external_pct_above_50d_threshold=0.35,
        external_new_high_new_low_spread_threshold=-0.10,
        external_advance_decline_drawdown_threshold=-0.10,
        external_negative_earnings_share_threshold=0.25,
        external_earnings_revision_3m_threshold=-0.05,
        external_margin_revision_3m_threshold=-0.02,
    )

    pd.testing.assert_frame_equal(opinions_spec, opinions_legacy)
    pd.testing.assert_frame_equal(features_spec, features_legacy)
    assert not opinions_spec.empty

    with pytest.raises(TypeError):
        crisis_impl._build_v2_context_opinions(close, price_signal, spec, start_date="2019-01-01")
    with pytest.raises(TypeError):
        crisis_impl._build_v2_context_opinions(close, price_signal, unexpected_kwarg=1)


@pytest.mark.parametrize("with_fragility", [False, True])
def test_add_unified_response_returns_spec_matches_legacy_kwargs(with_fragility: bool) -> None:
    close = _synthetic_close_matrix()
    index = close.index
    returns = close.pct_change(fill_method=None).fillna(0.0).reindex(index).fillna(0.0)
    base_weights = overlay_impl.build_tqqq_growth_income_base_weights(
        close,
        overlay_impl.DualDriveBaseWeightsConfig(start_date=str(index[0].date()), safe_symbol="SHY"),
    ).reindex(index[:-1]).ffill().fillna(0.0)

    crisis_signal = pd.Series(False, index=index)
    crisis_signal.iloc[200:215] = True
    crisis_weights = overlay_impl.apply_price_crisis_guard_to_weights(
        base_weights,
        crisis_signal,
        safe_symbol="SHY",
        risk_multiplier=0.25,
    ).reindex(index[:-1]).ffill().fillna(0.0)

    fragility_signal = None
    fragility_weights = None
    if with_fragility:
        fragility_signal = pd.Series(False, index=index)
        fragility_signal.iloc[185:200] = True
        fragility_weights = overlay_impl.apply_price_crisis_guard_to_weights(
            base_weights,
            fragility_signal,
            safe_symbol="SHY",
            risk_multiplier=0.50,
        ).reindex(index[:-1]).ffill().fillna(0.0)

    taco_result = {
        "weights_history": pd.DataFrame({"TQQQ": 0.4, "CASH": 0.6}, index=index[:-1]),
        "trades": pd.DataFrame({"signal_date": [str(index[220].date())]}),
    }

    spec_bundle = overlay_impl.StrategyReturnBundle()
    crisis_impl._add_unified_response_returns(
        crisis_impl.UnifiedResponseReturnsSpec(
            scenario_prefix="unified_test",
            taco_result=taco_result,
            returns=returns,
            base_weights=base_weights,
            crisis_weights=crisis_weights,
            crisis_signal=crisis_signal,
            index=index,
            outputs=spec_bundle,
            portfolio=overlay_impl.OverlayPortfolioConfig(
                overlay_sleeve_ratios=(0.05,),
                attack_symbol="TQQQ",
                safe_symbol="SHY",
                cash_symbol="CASH",
                turnover_cost_bps=5.0,
            ),
            fragility_weights=fragility_weights,
            fragility_signal=fragility_signal,
        )
    )

    legacy_returns: dict[str, pd.Series] = {}
    legacy_weights: dict[str, pd.DataFrame] = {}
    legacy_trades: dict[str, pd.DataFrame] = {}
    crisis_impl._add_unified_response_returns(
        scenario_prefix="unified_test",
        taco_result=taco_result,
        returns=returns,
        base_weights=base_weights,
        crisis_weights=crisis_weights,
        crisis_signal=crisis_signal,
        fragility_weights=fragility_weights,
        fragility_signal=fragility_signal,
        returns_by_strategy=legacy_returns,
        weights_by_strategy=legacy_weights,
        trades_by_strategy=legacy_trades,
        index=index,
        overlay_sleeve_ratios=(0.05,),
        attack_symbol="TQQQ",
        safe_symbol="SHY",
        cash_symbol="CASH",
        turnover_cost_bps=5.0,
    )

    assert set(spec_bundle.returns_by_strategy) == set(legacy_returns) == {"unified_test_5pct"}
    pd.testing.assert_series_equal(
        spec_bundle.returns_by_strategy["unified_test_5pct"],
        legacy_returns["unified_test_5pct"],
    )
    pd.testing.assert_frame_equal(
        spec_bundle.weights_by_strategy["unified_test_5pct"],
        legacy_weights["unified_test_5pct"],
    )


def test_run_crisis_response_research_and_overlay_comparison_end_to_end() -> None:
    close = _synthetic_close_matrix()
    prices = overlay_impl.close_matrix_to_price_history(close)
    events = _synthetic_events(close.index)
    ext = _synthetic_external_context(close.index)

    v1_result = crisis_impl.run_crisis_response_research(
        prices,
        events=events,
        start_date=str(close.index[0].date()),
        end_date=str(close.index[-1].date()),
        synthetic_attack_multiple=0.0,
        crisis_drawdown=-0.10,
        crisis_confirm_days=2,
        crisis_context_mode=crisis_impl.CRISIS_CONTEXT_MODE_V1_RUBRIC,
    )
    assert "base" in v1_result["returns_by_strategy"]
    assert "true_crisis_guard_base" in v1_result["returns_by_strategy"]
    assert "taco_only_5pct" in v1_result["returns_by_strategy"]
    assert "unified_response_5pct" in v1_result["returns_by_strategy"]

    v2_result = crisis_impl.run_crisis_response_research(
        prices,
        events=events,
        external_context=ext,
        start_date=str(close.index[0].date()),
        end_date=str(close.index[-1].date()),
        synthetic_attack_multiple=0.0,
        crisis_drawdown=-0.10,
        crisis_confirm_days=2,
        severe_crisis_risk_multiplier=0.0,
        bubble_fragility_risk_multiplier=0.5,
        bubble_fragility_drawdown=-0.05,
        bubble_fragility_confirm_days=2,
        crisis_context_mode=crisis_impl.CRISIS_CONTEXT_MODE_V2_CONTEXT_PACK,
        external_valuation_mode=crisis_impl.EXTERNAL_VALUATION_MODE_PRICE_OR_EXTERNAL,
    )
    assert not v2_result["crisis_context_features"].empty
    assert "bubble_fragility_guard_base" in v2_result["returns_by_strategy"]
    assert "route_audit_effectiveness" in v2_result

    overlay_result = overlay_impl.run_overlay_comparison(
        prices,
        events=events,
        start_date=str(close.index[0].date()),
        end_date=str(close.index[-1].date()),
        include_price_crisis_guard=True,
        crisis_guard_drawdown=-0.10,
    )
    assert "price_stress_taco_5pct" in overlay_result["returns_by_strategy"]
    assert "price_crisis_guard_taco_5pct" in overlay_result["returns_by_strategy"]
    assert "dual_audit_crisis_veto_taco_5pct" in overlay_result["returns_by_strategy"]
