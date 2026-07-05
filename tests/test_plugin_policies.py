from __future__ import annotations

import quant_strategy_plugins.strategy_plugin_runner as strategy_plugin_runner
from quant_strategy_plugins.plugin_policies import (
    EVIDENCE_AUTOMATION_APPROVED,
    GENERAL_MARKET_REGIME_NOTIFICATION_TARGET,
    PLUGIN_COMPATIBLE_STRATEGIES,
    PLUGIN_CONSUMPTION_POLICY_REGISTRY,
    PLUGIN_CRISIS_RESPONSE_SHADOW,
    PLUGIN_LIFECYCLE_DEPRECATED_COMPATIBILITY,
    PLUGIN_LIFECYCLE_POLICY_REGISTRY,
    PLUGIN_MARKET_REGIME_CONTROL,
    PLUGIN_NOTIFICATION_TARGET_POLICY_REGISTRY,
)


def test_market_regime_control_tqqq_policy_is_automation_approved() -> None:
    policy = PLUGIN_CONSUMPTION_POLICY_REGISTRY[(PLUGIN_MARKET_REGIME_CONTROL, "tqqq_growth_income")]

    assert policy.evidence_status == EVIDENCE_AUTOMATION_APPROVED
    assert policy.notification_allowed is True
    assert policy.position_control_allowed is True
    assert policy.manual_review_notification_target == GENERAL_MARKET_REGIME_NOTIFICATION_TARGET


def test_runner_reexports_policy_registries() -> None:
    assert strategy_plugin_runner.PLUGIN_CONSUMPTION_POLICY_REGISTRY is PLUGIN_CONSUMPTION_POLICY_REGISTRY
    assert strategy_plugin_runner.PLUGIN_NOTIFICATION_TARGET_POLICY_REGISTRY is PLUGIN_NOTIFICATION_TARGET_POLICY_REGISTRY
    assert strategy_plugin_runner.PLUGIN_COMPATIBLE_STRATEGIES is PLUGIN_COMPATIBLE_STRATEGIES
    assert strategy_plugin_runner.PLUGIN_LIFECYCLE_POLICY_REGISTRY is PLUGIN_LIFECYCLE_POLICY_REGISTRY


def test_deprecated_plugin_lifecycle_blocks_new_mounts_but_keeps_replay() -> None:
    policy = PLUGIN_LIFECYCLE_POLICY_REGISTRY[PLUGIN_CRISIS_RESPONSE_SHADOW]

    assert policy.lifecycle_stage == PLUGIN_LIFECYCLE_DEPRECATED_COMPATIBILITY
    assert policy.new_mount_allowed is False
    assert policy.replay_only is True
    assert policy.successor == PLUGIN_MARKET_REGIME_CONTROL
