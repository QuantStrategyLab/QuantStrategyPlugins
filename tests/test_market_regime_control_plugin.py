from __future__ import annotations

from quant_strategy_plugins.market_regime_control_plugin import build_market_regime_control_signal


def test_market_regime_control_crisis_blocks_taco_opportunity() -> None:
    payload = build_market_regime_control_signal(
        {
            "crisis": {
                "profile": "crisis_response_shadow",
                "as_of": "2026-05-28",
                "canonical_route": "true_crisis",
                "suggested_action": "defend",
                "would_trade_if_enabled": True,
            },
            "taco": {
                "profile": "taco_rebound_shadow",
                "as_of": "2026-05-28",
                "canonical_route": "taco_rebound",
                "suggested_action": "notify_manual_review",
                "manual_review_required": True,
                "rebound_context_active": True,
            },
        }
    )

    assert payload["profile"] == "market_regime_control"
    assert payload["canonical_route"] == "risk_off"
    assert payload["suggested_action"] == "defend"
    assert payload["would_trade_if_enabled"] is True
    assert payload["position_control"]["leverage_scalar"] == 0.0
    assert payload["position_control"]["risk_asset_scalar"] == 0.0
    assert payload["position_control"]["taco_allowed"] is False
    assert payload["position_control"]["crisis_defense_required"] is True
    volatility_delever_context = payload["position_control"]["volatility_delever_context"]
    assert volatility_delever_context["hard_risk"] is True
    assert volatility_delever_context["retention_profiles"]["soxl_step_rebound_0.25_0.50"]["retention_ratio"] == 0.0
    assert (
        volatility_delever_context["retention_profiles"]["soxl_step_softzero_rebound_0.25_0.50"][
            "retention_ratio"
        ]
        == 0.0
    )
    assert "crisis_blocks_taco" in payload["arbiter"]["vetoes"]


def test_market_regime_control_macro_delever_blocks_taco_veto() -> None:
    payload = build_market_regime_control_signal(
        {
            "macro": {
                "profile": "macro_risk_governor",
                "as_of": "2026-05-28",
                "canonical_route": "delever",
                "suggested_action": "delever",
                "leverage_scalar": 0.0,
                "risk_asset_scalar": 1.0,
                "reason_codes": ["vix_crisis_level"],
            },
            "taco": {
                "profile": "taco_rebound_shadow",
                "as_of": "2026-05-28",
                "canonical_route": "taco_rebound",
                "suggested_action": "notify_manual_review",
                "manual_review_required": True,
                "rebound_context_active": True,
            },
        }
    )

    assert payload["canonical_route"] == "risk_reduced"
    assert payload["suggested_action"] == "delever"
    assert payload["position_control"]["leverage_scalar"] == 0.0
    assert payload["position_control"]["risk_asset_scalar"] == 1.0
    assert payload["position_control"]["taco_allowed"] is False
    volatility_delever_context = payload["position_control"]["volatility_delever_context"]
    assert volatility_delever_context["soft_risk"] is True
    assert (
        volatility_delever_context["retention_profiles"]["tqqq_step_softzero_0.35_0.50"]["retention_ratio"]
        == 0.0
    )
    assert volatility_delever_context["retention_profiles"]["soxl_step_rebound_0.25_0.50"]["retention_ratio"] == 0.0
    assert (
        volatility_delever_context["retention_profiles"]["soxl_step_softzero_rebound_0.25_0.50"][
            "retention_ratio"
        ]
        == 0.0
    )
    assert "macro_delever_blocks_taco" in payload["arbiter"]["vetoes"]
    assert "macro:vix_crisis_level" in payload["position_control"]["reason_codes"]


def test_market_regime_control_taco_is_notification_with_local_veto_only() -> None:
    payload = build_market_regime_control_signal(
        {
            "taco": {
                "profile": "taco_rebound_shadow",
                "as_of": "2026-05-28",
                "canonical_route": "taco_rebound",
                "suggested_action": "notify_manual_review",
                "manual_review_required": True,
                "rebound_context_active": True,
            },
        },
        taco_opportunity_size_scalar=0.25,
    )

    assert payload["canonical_route"] == "opportunity_watch"
    assert payload["suggested_action"] == "notify_manual_review"
    assert payload["would_trade_if_enabled"] is False
    assert payload["notification"]["should_notify"] is True
    assert payload["position_control"]["taco_allowed"] is True
    assert payload["position_control"]["local_delever_veto_allowed"] is True
    assert payload["position_control"]["taco_size_scalar"] == 0.25
    assert payload["position_control"]["panic_reversal_allowed"] is False
    volatility_delever_context = payload["position_control"]["volatility_delever_context"]
    assert volatility_delever_context["constructive"] is True
    assert volatility_delever_context["rebound_confirm"] is True
    assert (
        volatility_delever_context["retention_profiles"]["tqqq_step_softzero_0.25_0.50"]["retention_ratio"]
        == 0.25
    )
    assert volatility_delever_context["retention_profiles"]["soxl_step_rebound_0.25_0.50"]["retention_ratio"] == 0.0
    assert (
        volatility_delever_context["retention_profiles"]["soxl_step_softzero_rebound_0.25_0.50"][
            "retention_ratio"
        ]
        == 0.0
    )
    assert payload["execution_controls"]["broker_order_allowed"] is False
    assert payload["execution_controls"]["live_allocation_mutation_allowed"] is False


def test_market_regime_control_price_rebound_only_updates_volatility_retention_profile() -> None:
    payload = build_market_regime_control_signal(
        {},
        volatility_delever_price_rebound_context={
            "schema_version": "volatility_delever_price_rebound_context.v1",
            "confirmed": True,
            "reason_codes": ["price_rebound_confirm"],
        },
    )

    assert payload["canonical_route"] == "no_action"
    assert payload["suggested_action"] == "no_action"
    assert payload["notification"]["should_notify"] is False
    volatility_delever_context = payload["position_control"]["volatility_delever_context"]
    assert volatility_delever_context["rebound_confirm"] is True
    assert volatility_delever_context["rebound_sources"] == ["price_rebound"]
    assert (
        volatility_delever_context["retention_profiles"]["tqqq_step_softzero_0.25_0.50"]["retention_ratio"]
        == 0.25
    )
    soxl_profile = volatility_delever_context["retention_profiles"]["soxl_step_rebound_0.25_0.50"]
    assert soxl_profile["retention_ratio"] == 0.5
    assert soxl_profile["reason_codes"] == ["constructive", "price_rebound_confirm"]
    softzero_profile = volatility_delever_context["retention_profiles"]["soxl_step_softzero_rebound_0.25_0.50"]
    assert softzero_profile["retention_ratio"] == 0.5
    assert softzero_profile["reason_codes"] == ["constructive", "price_rebound_confirm"]


def test_market_regime_control_soxl_aggressive_profile_retains_soft_price_rebound_candidate() -> None:
    payload = build_market_regime_control_signal(
        {
            "macro": {
                "profile": "macro_risk_governor",
                "as_of": "2026-06-16",
                "canonical_route": "delever",
                "suggested_action": "delever",
                "leverage_scalar": 0.0,
                "risk_asset_scalar": 1.0,
            },
        },
        volatility_delever_price_rebound_context={
            "schema_version": "volatility_delever_price_rebound_context.v1",
            "confirmed": False,
            "volatility_triggered": True,
            "trend_ok": True,
            "rebound_nd": True,
            "hard_filter": False,
            "soft_filter": True,
            "reason_codes": ["soft_filter"],
        },
    )

    volatility_delever_context = payload["position_control"]["volatility_delever_context"]
    assert volatility_delever_context["soft_risk"] is True
    assert volatility_delever_context["price_rebound_candidate"] is True
    soxl_profile = volatility_delever_context["retention_profiles"]["soxl_step_rebound_0.25_0.50"]
    assert soxl_profile["retention_ratio"] == 0.25
    assert soxl_profile["reason_codes"] == ["price_rebound_candidate", "soft_risk"]
    softzero_profile = volatility_delever_context["retention_profiles"]["soxl_step_softzero_rebound_0.25_0.50"]
    assert softzero_profile["retention_ratio"] == 0.0
    assert softzero_profile["reason_codes"] == ["soft_risk"]


def test_market_regime_control_panic_reversal_is_opportunity_watch_only() -> None:
    payload = build_market_regime_control_signal(
        {
            "panic_reversal": {
                "profile": "panic_reversal_shadow",
                "as_of": "2025-04-09",
                "canonical_route": "panic_reversal",
                "suggested_action": "notify_manual_review",
                "manual_review_required": True,
                "panic_reversal_context_active": True,
                "would_trade_if_enabled": False,
            },
        }
    )

    assert payload["canonical_route"] == "opportunity_watch"
    assert payload["suggested_action"] == "notify_manual_review"
    assert payload["would_trade_if_enabled"] is False
    assert payload["position_control"]["taco_allowed"] is False
    assert payload["position_control"]["panic_reversal_allowed"] is True
    assert payload["position_control"]["panic_reversal_size_scalar"] == 0.0
    assert payload["position_control"]["local_delever_veto_allowed"] is True
    assert payload["execution_controls"]["broker_order_allowed"] is False
    assert payload["execution_controls"]["live_allocation_mutation_allowed"] is False


def test_market_regime_control_macro_delever_blocks_panic_reversal() -> None:
    payload = build_market_regime_control_signal(
        {
            "macro": {
                "profile": "macro_risk_governor",
                "as_of": "2025-04-09",
                "canonical_route": "delever",
                "suggested_action": "delever",
                "leverage_scalar": 0.0,
                "risk_asset_scalar": 1.0,
                "reason_codes": ["vix_crisis_level"],
            },
            "panic_reversal": {
                "profile": "panic_reversal_shadow",
                "as_of": "2025-04-09",
                "canonical_route": "panic_reversal",
                "suggested_action": "notify_manual_review",
                "manual_review_required": True,
                "panic_reversal_context_active": True,
            },
        }
    )

    assert payload["canonical_route"] == "risk_reduced"
    assert payload["suggested_action"] == "delever"
    assert payload["position_control"]["panic_reversal_allowed"] is False
    assert "macro_delever_blocks_panic_reversal" in payload["arbiter"]["vetoes"]
    assert payload["notification"]["opportunity_vetoed_should_notify"] is True
    assert payload["notification"]["vetoed_opportunities"][0]["component"] == "panic_reversal"
    assert payload["notification"]["vetoed_opportunities"][0]["veto"] == "macro_delever_blocks_panic_reversal"


def test_market_regime_control_blocked_component_blocks_taco_opportunity() -> None:
    payload = build_market_regime_control_signal(
        {
            "macro": {
                "profile": "macro_risk_governor",
                "as_of": "2026-05-28",
                "canonical_route": "no_action",
                "suggested_action": "blocked",
                "kill_switch_active": True,
            },
            "taco": {
                "profile": "taco_rebound_shadow",
                "as_of": "2026-05-28",
                "canonical_route": "taco_rebound",
                "suggested_action": "notify_manual_review",
                "manual_review_required": True,
                "rebound_context_active": True,
            },
        }
    )

    assert payload["canonical_route"] == "blocked"
    assert payload["suggested_action"] == "blocked"
    assert payload["position_control"]["taco_allowed"] is False
    assert "macro:blocked" in payload["position_control"]["reason_codes"]


def test_market_regime_control_exposes_tecl_retention_profiles() -> None:
    payload = build_market_regime_control_signal(
        {},
        volatility_delever_price_rebound_context={
            "schema_version": "volatility_delever_price_rebound_context.v1",
            "confirmed": True,
            "reason_codes": ["price_rebound_confirm"],
        },
    )

    profiles = payload["position_control"]["volatility_delever_context"]["retention_profiles"]
    assert profiles["tecl_step_rebound_0.25_0.50"]["retention_ratio"] == 0.50
    assert profiles["tecl_step_softzero_rebound_0.25_0.50"]["retention_ratio"] == 0.50
