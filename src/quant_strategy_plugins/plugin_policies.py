from __future__ import annotations

from dataclasses import dataclass

EVIDENCE_AUTOMATION_APPROVED = "automation_approved"
EVIDENCE_NOTIFICATION_ONLY = "notification_only"
EVIDENCE_DEPRECATED_COMPATIBILITY = "deprecated_compatibility"
PLUGIN_LIFECYCLE_AUTOMATION_APPROVED = "automation_approved"
PLUGIN_LIFECYCLE_NOTIFICATION_ONLY = "notification_only"
PLUGIN_LIFECYCLE_DEPRECATED_COMPATIBILITY = "deprecated_compatibility"

GENERAL_MARKET_REGIME_NOTIFICATION_TARGET = "market_regime_notification"

PLUGIN_CRISIS_RESPONSE_SHADOW = "crisis_response_shadow"
PLUGIN_MARKET_REGIME_CONTROL = "market_regime_control"
PLUGIN_MACRO_RISK_GOVERNOR = "macro_risk_governor"
PLUGIN_PANIC_REVERSAL_SHADOW = "panic_reversal_shadow"
PLUGIN_TACO_REBOUND_SHADOW = "taco_rebound_shadow"

PLUGIN_SCHEMA_VERSIONS: dict[str, tuple[str, ...]] = {
    PLUGIN_CRISIS_RESPONSE_SHADOW: ("crisis_response_shadow.v1",),
    PLUGIN_MARKET_REGIME_CONTROL: ("market_regime_control.v1",),
    PLUGIN_MACRO_RISK_GOVERNOR: ("macro_risk_governor.v1",),
    PLUGIN_PANIC_REVERSAL_SHADOW: ("panic_reversal_shadow.v1",),
    PLUGIN_TACO_REBOUND_SHADOW: ("taco_rebound_shadow.v2",),
}

PLUGIN_DEPRECATED_SUCCESSORS: dict[str, str] = {
    PLUGIN_CRISIS_RESPONSE_SHADOW: PLUGIN_MARKET_REGIME_CONTROL,
    PLUGIN_MACRO_RISK_GOVERNOR: PLUGIN_MARKET_REGIME_CONTROL,
    PLUGIN_TACO_REBOUND_SHADOW: PLUGIN_MARKET_REGIME_CONTROL,
}
PLUGIN_RESEARCH_ONLY_REASONS: dict[str, str] = {}


@dataclass(frozen=True)
class PluginConsumptionPolicy:
    plugin: str
    strategy: str
    notification_allowed: bool
    position_control_allowed: bool
    evidence_status: str
    since_version: str
    description: str
    intended_strategy_role: str | None = None
    manual_review_notification_target: str | None = None


@dataclass(frozen=True)
class PluginNotificationTargetPolicy:
    plugin: str
    notification_target: str
    notification_allowed: bool
    position_control_allowed: bool
    evidence_status: str
    since_version: str
    description: str
    notification_role: str


@dataclass(frozen=True)
class PluginLifecyclePolicy:
    plugin: str
    lifecycle_stage: str
    schema_versions: tuple[str, ...]
    new_mount_allowed: bool
    replay_only: bool
    description: str
    successor: str | None = None


PLUGIN_LIFECYCLE_POLICIES: tuple[PluginLifecyclePolicy, ...] = (
    PluginLifecyclePolicy(
        plugin=PLUGIN_MARKET_REGIME_CONTROL,
        lifecycle_stage=PLUGIN_LIFECYCLE_AUTOMATION_APPROVED,
        schema_versions=PLUGIN_SCHEMA_VERSIONS[PLUGIN_MARKET_REGIME_CONTROL],
        new_mount_allowed=True,
        replay_only=False,
        description="Unified market-regime sidecar; automated consumption still requires per-strategy policy approval.",
    ),
    PluginLifecyclePolicy(
        plugin=PLUGIN_PANIC_REVERSAL_SHADOW,
        lifecycle_stage=PLUGIN_LIFECYCLE_NOTIFICATION_ONLY,
        schema_versions=PLUGIN_SCHEMA_VERSIONS[PLUGIN_PANIC_REVERSAL_SHADOW],
        new_mount_allowed=True,
        replay_only=False,
        description="Research notification sidecar; never grants automated position control.",
    ),
    PluginLifecyclePolicy(
        plugin=PLUGIN_CRISIS_RESPONSE_SHADOW,
        lifecycle_stage=PLUGIN_LIFECYCLE_DEPRECATED_COMPATIBILITY,
        schema_versions=PLUGIN_SCHEMA_VERSIONS[PLUGIN_CRISIS_RESPONSE_SHADOW],
        new_mount_allowed=False,
        replay_only=True,
        successor=PLUGIN_MARKET_REGIME_CONTROL,
        description="Legacy crisis sidecar retained for historical replay; new mounts use market_regime_control.",
    ),
    PluginLifecyclePolicy(
        plugin=PLUGIN_MACRO_RISK_GOVERNOR,
        lifecycle_stage=PLUGIN_LIFECYCLE_DEPRECATED_COMPATIBILITY,
        schema_versions=PLUGIN_SCHEMA_VERSIONS[PLUGIN_MACRO_RISK_GOVERNOR],
        new_mount_allowed=False,
        replay_only=True,
        successor=PLUGIN_MARKET_REGIME_CONTROL,
        description="Legacy macro sidecar retained for historical replay; new mounts use market_regime_control.",
    ),
    PluginLifecyclePolicy(
        plugin=PLUGIN_TACO_REBOUND_SHADOW,
        lifecycle_stage=PLUGIN_LIFECYCLE_DEPRECATED_COMPATIBILITY,
        schema_versions=PLUGIN_SCHEMA_VERSIONS[PLUGIN_TACO_REBOUND_SHADOW],
        new_mount_allowed=False,
        replay_only=True,
        successor=PLUGIN_MARKET_REGIME_CONTROL,
        description="Legacy event rebound notifier retained for replay; new mounts use market_regime_control/manual review.",
    ),
)

PLUGIN_LIFECYCLE_POLICY_REGISTRY: dict[str, PluginLifecyclePolicy] = {
    policy.plugin: policy for policy in PLUGIN_LIFECYCLE_POLICIES
}


PLUGIN_CONSUMPTION_POLICIES: tuple[PluginConsumptionPolicy, ...] = (
    PluginConsumptionPolicy(
        plugin=PLUGIN_MARKET_REGIME_CONTROL,
        strategy="tqqq_growth_income",
        notification_allowed=True,
        position_control_allowed=True,
        evidence_status=EVIDENCE_AUTOMATION_APPROVED,
        since_version="strategy_plugins.v1",
        description="Backtested automatic macro/crisis risk controls for the TQQQ growth-income strategy.",
        manual_review_notification_target=GENERAL_MARKET_REGIME_NOTIFICATION_TARGET,
    ),
    PluginConsumptionPolicy(
        plugin=PLUGIN_MARKET_REGIME_CONTROL,
        strategy="global_etf_rotation",
        notification_allowed=True,
        position_control_allowed=False,
        evidence_status=EVIDENCE_NOTIFICATION_ONLY,
        since_version="strategy_plugins.v1",
        description="Pending 25-30 year market-regime-control validation for broad ETF rotation.",
        manual_review_notification_target=GENERAL_MARKET_REGIME_NOTIFICATION_TARGET,
    ),
    PluginConsumptionPolicy(
        plugin=PLUGIN_MARKET_REGIME_CONTROL,
        strategy="russell_1000_multi_factor_defensive",
        notification_allowed=True,
        position_control_allowed=False,
        evidence_status=EVIDENCE_NOTIFICATION_ONLY,
        since_version="strategy_plugins.v1",
        description="Pending 25-30 year market-regime-control validation for the Russell 1000 defensive sleeve.",
        manual_review_notification_target=GENERAL_MARKET_REGIME_NOTIFICATION_TARGET,
    ),
    PluginConsumptionPolicy(
        plugin=PLUGIN_MARKET_REGIME_CONTROL,
        strategy="mega_cap_leader_rotation_top50_balanced",
        notification_allowed=True,
        position_control_allowed=False,
        evidence_status=EVIDENCE_NOTIFICATION_ONLY,
        since_version="strategy_plugins.v1",
        description="Pending 25-30 year market-regime-control validation for the mega-cap leader rotation profile.",
        manual_review_notification_target=GENERAL_MARKET_REGIME_NOTIFICATION_TARGET,
    ),
    PluginConsumptionPolicy(
        plugin=PLUGIN_MARKET_REGIME_CONTROL,
        strategy="soxl_soxx_trend_income",
        notification_allowed=True,
        position_control_allowed=True,
        evidence_status=EVIDENCE_AUTOMATION_APPROVED,
        since_version="strategy_plugins.v1",
        description="Backtested automatic macro/crisis risk controls for the SOXL/SOXX trend-income strategy.",
        manual_review_notification_target=GENERAL_MARKET_REGIME_NOTIFICATION_TARGET,
    ),
    PluginConsumptionPolicy(
        plugin=PLUGIN_CRISIS_RESPONSE_SHADOW,
        strategy="tqqq_growth_income",
        notification_allowed=True,
        position_control_allowed=False,
        evidence_status=EVIDENCE_DEPRECATED_COMPATIBILITY,
        since_version="strategy_plugins.v1",
        description="Deprecated direct crisis shadow mount kept for historical replay; new consumers use market_regime_control.",
    ),
    PluginConsumptionPolicy(
        plugin=PLUGIN_MACRO_RISK_GOVERNOR,
        strategy="tqqq_growth_income",
        notification_allowed=True,
        position_control_allowed=False,
        evidence_status=EVIDENCE_DEPRECATED_COMPATIBILITY,
        since_version="strategy_plugins.v1",
        description="Deprecated direct macro governor mount kept for historical replay; new consumers use market_regime_control.",
    ),
    PluginConsumptionPolicy(
        plugin=PLUGIN_TACO_REBOUND_SHADOW,
        strategy="tqqq_growth_income",
        notification_allowed=True,
        position_control_allowed=False,
        evidence_status=EVIDENCE_NOTIFICATION_ONLY,
        since_version="strategy_plugins.v1",
        description="Manual-review event rebound notifier for TQQQ only.",
    ),
    PluginConsumptionPolicy(
        plugin=PLUGIN_PANIC_REVERSAL_SHADOW,
        strategy="tqqq_growth_income",
        notification_allowed=True,
        position_control_allowed=False,
        evidence_status=EVIDENCE_NOTIFICATION_ONLY,
        since_version="strategy_plugins.v1",
        description="Research-only VIX panic reversal notifier for TQQQ manual review.",
    ),
)

PLUGIN_CONSUMPTION_POLICY_REGISTRY: dict[tuple[str, str], PluginConsumptionPolicy] = {
    (policy.plugin, policy.strategy): policy for policy in PLUGIN_CONSUMPTION_POLICIES
}

PLUGIN_NOTIFICATION_TARGET_POLICIES: tuple[PluginNotificationTargetPolicy, ...] = (
    PluginNotificationTargetPolicy(
        plugin=PLUGIN_MARKET_REGIME_CONTROL,
        notification_target=GENERAL_MARKET_REGIME_NOTIFICATION_TARGET,
        notification_allowed=True,
        position_control_allowed=False,
        evidence_status=EVIDENCE_NOTIFICATION_ONLY,
        since_version="strategy_plugins.v1",
        description="General market-regime notice. Not mounted into an automated strategy runtime.",
        notification_role="general_market_regime_notification",
    ),
    PluginNotificationTargetPolicy(
        plugin=PLUGIN_PANIC_REVERSAL_SHADOW,
        notification_target=GENERAL_MARKET_REGIME_NOTIFICATION_TARGET,
        notification_allowed=True,
        position_control_allowed=False,
        evidence_status=EVIDENCE_NOTIFICATION_ONLY,
        since_version="strategy_plugins.v1",
        description="General research-only panic reversal notice. Not mounted into an automated strategy runtime.",
        notification_role="panic_reversal_notification",
    ),
)

PLUGIN_NOTIFICATION_TARGET_POLICY_REGISTRY: dict[tuple[str, str], PluginNotificationTargetPolicy] = {
    (policy.plugin, policy.notification_target): policy for policy in PLUGIN_NOTIFICATION_TARGET_POLICIES
}

PLUGIN_COMPATIBLE_STRATEGIES: dict[str, tuple[str, ...]] = {
    plugin: tuple(
        policy.strategy
        for policy in PLUGIN_CONSUMPTION_POLICIES
        if policy.plugin == plugin and policy.notification_allowed
    )
    for plugin in sorted({policy.plugin for policy in PLUGIN_CONSUMPTION_POLICIES})
}

PLUGIN_COMPATIBLE_NOTIFICATION_TARGETS: dict[str, tuple[str, ...]] = {
    plugin: tuple(
        policy.notification_target
        for policy in PLUGIN_NOTIFICATION_TARGET_POLICIES
        if policy.plugin == plugin and policy.notification_allowed
    )
    for plugin in sorted({policy.plugin for policy in PLUGIN_NOTIFICATION_TARGET_POLICIES})
}

__all__ = [
    "EVIDENCE_AUTOMATION_APPROVED",
    "EVIDENCE_DEPRECATED_COMPATIBILITY",
    "EVIDENCE_NOTIFICATION_ONLY",
    "GENERAL_MARKET_REGIME_NOTIFICATION_TARGET",
    "PLUGIN_COMPATIBLE_NOTIFICATION_TARGETS",
    "PLUGIN_COMPATIBLE_STRATEGIES",
    "PLUGIN_CONSUMPTION_POLICIES",
    "PLUGIN_CONSUMPTION_POLICY_REGISTRY",
    "PLUGIN_CRISIS_RESPONSE_SHADOW",
    "PLUGIN_DEPRECATED_SUCCESSORS",
    "PLUGIN_LIFECYCLE_AUTOMATION_APPROVED",
    "PLUGIN_LIFECYCLE_DEPRECATED_COMPATIBILITY",
    "PLUGIN_LIFECYCLE_NOTIFICATION_ONLY",
    "PLUGIN_LIFECYCLE_POLICIES",
    "PLUGIN_LIFECYCLE_POLICY_REGISTRY",
    "PLUGIN_MACRO_RISK_GOVERNOR",
    "PLUGIN_MARKET_REGIME_CONTROL",
    "PLUGIN_NOTIFICATION_TARGET_POLICIES",
    "PLUGIN_NOTIFICATION_TARGET_POLICY_REGISTRY",
    "PLUGIN_PANIC_REVERSAL_SHADOW",
    "PLUGIN_SCHEMA_VERSIONS",
    "PLUGIN_TACO_REBOUND_SHADOW",
    "PLUGIN_RESEARCH_ONLY_REASONS",
    "PluginConsumptionPolicy",
    "PluginLifecyclePolicy",
    "PluginNotificationTargetPolicy",
]
