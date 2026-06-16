from __future__ import annotations

import argparse
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import pandas as pd

from .artifacts import write_json
from .crisis_response_shadow_plugin import (
    SHADOW_MODE,
    build_crisis_response_shadow_signal,
    write_crisis_response_shadow_outputs,
)
from .macro_risk_governor_plugin import (
    MACRO_RISK_GOVERNOR_PROFILE,
    build_macro_risk_governor_signal,
    write_macro_risk_governor_outputs,
)
from .market_regime_control_plugin import (
    MARKET_REGIME_CONTROL_PROFILE,
    build_market_regime_control_signal,
    write_market_regime_control_outputs,
)
from .panic_reversal_shadow_plugin import (
    PANIC_REVERSAL_PROFILE,
    build_panic_reversal_shadow_signal,
    write_panic_reversal_shadow_outputs,
)
from .russell_1000_multi_factor_defensive_snapshot import read_table
from .taco_panic_rebound_research import DEFAULT_EVENT_SET, resolve_trade_war_event_set
from .taco_rebound_shadow_plugin import (
    TACO_REBOUND_PROFILE,
    build_taco_rebound_shadow_signal,
    write_taco_rebound_shadow_outputs,
)
from .volatility_delever_price_rebound import build_volatility_delever_price_rebound_context

DEFAULT_RUNNER_OUTPUT_DIR = "data/output/strategy_plugins"
GENERAL_MARKET_REGIME_NOTIFICATION_TARGET = "market_regime_notification"
PLUGIN_CRISIS_RESPONSE_SHADOW = "crisis_response_shadow"
PLUGIN_MARKET_REGIME_CONTROL = MARKET_REGIME_CONTROL_PROFILE
PLUGIN_MACRO_RISK_GOVERNOR = MACRO_RISK_GOVERNOR_PROFILE
PLUGIN_PANIC_REVERSAL_SHADOW = PANIC_REVERSAL_PROFILE
PLUGIN_TACO_REBOUND_SHADOW = TACO_REBOUND_PROFILE
SUPPORTED_PLUGIN_MODES = (SHADOW_MODE,)
STRATEGY_PLUGIN_MESSAGE_SCHEMA_VERSION = "strategy_plugin_messages.v1"
STRATEGY_PLUGIN_LOG_SCHEMA_VERSION = "strategy_plugin_log.v1"
DEFAULT_MESSAGE_LOCALE = "en-US"
SUPPORTED_MESSAGE_LOCALES = ("en-US", "zh-CN")
EVIDENCE_AUTOMATION_APPROVED = "automation_approved"
EVIDENCE_NOTIFICATION_ONLY = "notification_only"
EVIDENCE_DEPRECATED_COMPATIBILITY = "deprecated_compatibility"
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
class PluginRunResult:
    strategy: str
    plugin: str
    enabled: bool
    mode: str
    effective_mode: str | None
    status: str
    output_dir: str | None = None
    latest_signal_path: str | None = None
    message: str = ""
    target_type: str = "strategy"
    notification_target: str | None = None


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


PLUGIN_CONSUMPTION_POLICIES: tuple[PluginConsumptionPolicy, ...] = (
    PluginConsumptionPolicy(
        plugin=PLUGIN_MARKET_REGIME_CONTROL,
        strategy="tqqq_growth_income",
        notification_allowed=True,
        position_control_allowed=True,
        evidence_status=EVIDENCE_AUTOMATION_APPROVED,
        since_version="strategy_plugins.v1",
        description="Backtested automatic macro/crisis risk controls for the TQQQ growth-income strategy.",
    ),
    PluginConsumptionPolicy(
        plugin=PLUGIN_MARKET_REGIME_CONTROL,
        strategy="global_etf_rotation",
        notification_allowed=True,
        position_control_allowed=False,
        evidence_status=EVIDENCE_NOTIFICATION_ONLY,
        since_version="strategy_plugins.v1",
        description="Pending 25-30 year market-regime-control validation for broad ETF rotation.",
    ),
    PluginConsumptionPolicy(
        plugin=PLUGIN_MARKET_REGIME_CONTROL,
        strategy="russell_1000_multi_factor_defensive",
        notification_allowed=True,
        position_control_allowed=False,
        evidence_status=EVIDENCE_NOTIFICATION_ONLY,
        since_version="strategy_plugins.v1",
        description="Pending 25-30 year market-regime-control validation for the Russell 1000 defensive sleeve.",
    ),
    PluginConsumptionPolicy(
        plugin=PLUGIN_MARKET_REGIME_CONTROL,
        strategy="mega_cap_leader_rotation_top50_balanced",
        notification_allowed=True,
        position_control_allowed=False,
        evidence_status=EVIDENCE_NOTIFICATION_ONLY,
        since_version="strategy_plugins.v1",
        description="Pending 25-30 year market-regime-control validation for the mega-cap leader rotation profile.",
    ),
    PluginConsumptionPolicy(
        plugin=PLUGIN_MARKET_REGIME_CONTROL,
        strategy="soxl_soxx_trend_income",
        notification_allowed=True,
        position_control_allowed=True,
        evidence_status=EVIDENCE_AUTOMATION_APPROVED,
        since_version="strategy_plugins.v1",
        description="Backtested automatic macro/crisis risk controls for the SOXL/SOXX trend-income strategy.",
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

LOCALIZED_ROUTE_LABELS: dict[str, dict[str, str]] = {
    "blocked": {"en-US": "Blocked", "zh-CN": "已阻断"},
    "crisis": {"en-US": "Crisis", "zh-CN": "危机"},
    "delever": {"en-US": "De-lever", "zh-CN": "降杠杆"},
    "no_action": {"en-US": "No action", "zh-CN": "无动作"},
    "opportunity_watch": {"en-US": "Opportunity watch", "zh-CN": "机会观察"},
    "panic_reversal": {"en-US": "Panic reversal", "zh-CN": "恐慌反转"},
    "risk_off": {"en-US": "Risk off", "zh-CN": "风险关闭"},
    "risk_reduced": {"en-US": "Risk reduced", "zh-CN": "风险降低"},
    "taco_rebound": {"en-US": "TACO rebound", "zh-CN": "TACO 反弹"},
    "true_crisis": {"en-US": "True crisis", "zh-CN": "真实危机"},
    "watch": {"en-US": "Watch", "zh-CN": "观察"},
}
LOCALIZED_ACTION_LABELS: dict[str, dict[str, str]] = {
    "blocked": {"en-US": "Blocked", "zh-CN": "已阻断"},
    "defend": {"en-US": "Defend", "zh-CN": "防守"},
    "delever": {"en-US": "De-lever", "zh-CN": "降杠杆"},
    "no_action": {"en-US": "No action", "zh-CN": "无动作"},
    "notify_manual_review": {"en-US": "Notify manual review", "zh-CN": "通知人工复核"},
    "watch_only": {"en-US": "Watch only", "zh-CN": "仅观察"},
}
LOCALIZED_PLUGIN_LABELS: dict[str, dict[str, str]] = {
    PLUGIN_CRISIS_RESPONSE_SHADOW: {"en-US": "Crisis response watch", "zh-CN": "危机响应观察"},
    PLUGIN_MACRO_RISK_GOVERNOR: {"en-US": "Macro risk governor", "zh-CN": "宏观风险控制"},
    PLUGIN_MARKET_REGIME_CONTROL: {"en-US": "Market regime control", "zh-CN": "市场状态控制"},
    PLUGIN_PANIC_REVERSAL_SHADOW: {"en-US": "Panic reversal watch", "zh-CN": "恐慌反转观察"},
    PLUGIN_TACO_REBOUND_SHADOW: {"en-US": "TACO rebound watch", "zh-CN": "TACO 反弹观察"},
}
LOCALIZED_SOURCE_LABELS: dict[str, dict[str, str]] = {
    "crisis": {"en-US": "Crisis", "zh-CN": "危机"},
    "data_quality": {"en-US": "Data quality", "zh-CN": "数据质量"},
    "macro": {"en-US": "Macro", "zh-CN": "宏观"},
    "panic_reversal": {"en-US": "Panic reversal", "zh-CN": "恐慌反转"},
    "taco": {"en-US": "TACO", "zh-CN": "TACO"},
}
LOCALIZED_REASON_LABELS: dict[str, dict[str, str]] = {
    "aaii_bear_bull_spread_watch": {
        "en-US": "AAII bearish-bullish spread watch",
        "zh-CN": "AAII 熊牛差观察",
    },
    "advance_decline_drawdown_watch": {
        "en-US": "Advance-decline drawdown watch",
        "zh-CN": "涨跌线回撤观察",
    },
    "benchmark_below_ma": {"en-US": "Benchmark below moving average", "zh-CN": "基准低于均线"},
    "benchmark_drawdown_crisis": {"en-US": "Benchmark crisis drawdown", "zh-CN": "基准危机回撤"},
    "benchmark_drawdown_watch": {"en-US": "Benchmark drawdown watch", "zh-CN": "基准回撤观察"},
    "benchmark_realized_volatility_high": {
        "en-US": "High realized volatility",
        "zh-CN": "实现波动偏高",
    },
    "blocked": {"en-US": "Blocked", "zh-CN": "已阻断"},
    "credit_pair_stress": {"en-US": "Credit-pair stress", "zh-CN": "信用 ETF 相对压力"},
    "crisis": {"en-US": "Crisis", "zh-CN": "危机"},
    "delever": {"en-US": "De-lever", "zh-CN": "降杠杆"},
    "dollar_stress_watch": {"en-US": "Dollar stress watch", "zh-CN": "美元压力观察"},
    "fear_greed_extreme_fear_watch": {
        "en-US": "Fear & Greed extreme fear watch",
        "zh-CN": "恐惧贪婪极度恐惧观察",
    },
    "financial_stress_index_high": {
        "en-US": "Financial stress index high",
        "zh-CN": "金融压力指数偏高",
    },
    "funding_stress_watch": {"en-US": "Funding stress watch", "zh-CN": "资金压力观察"},
    "hy_oas_watch_level": {"en-US": "High-yield OAS watch", "zh-CN": "高收益 OAS 观察"},
    "hy_oas_widening": {"en-US": "High-yield OAS widening", "zh-CN": "高收益 OAS 扩张"},
    "ig_oas_watch_level": {"en-US": "Investment-grade OAS watch", "zh-CN": "投资级 OAS 观察"},
    "ig_oas_widening_watch": {"en-US": "Investment-grade OAS widening watch", "zh-CN": "投资级 OAS 扩张观察"},
    "market_breadth_pct_above_50d_watch": {
        "en-US": "50-day market breadth watch",
        "zh-CN": "50 日市场宽度观察",
    },
    "market_breadth_pct_above_200d_watch": {
        "en-US": "200-day market breadth watch",
        "zh-CN": "200 日市场宽度观察",
    },
    "move_high_watch": {"en-US": "MOVE high watch", "zh-CN": "MOVE 偏高观察"},
    "naaim_exposure_low_watch": {"en-US": "NAAIM low exposure watch", "zh-CN": "NAAIM 低仓位观察"},
    "new_high_new_low_spread_watch": {
        "en-US": "New-high/new-low spread watch",
        "zh-CN": "新高新低差观察",
    },
    "no_action": {"en-US": "No action", "zh-CN": "无动作"},
    "opportunity_watch": {"en-US": "Opportunity watch", "zh-CN": "机会观察"},
    "pentagon_pizza_watch": {"en-US": "Pentagon pizza index watch", "zh-CN": "五角大楼比萨指数观察"},
    "panic_reversal": {"en-US": "Panic reversal context", "zh-CN": "恐慌反转上下文"},
    "panic_reversal_watch": {"en-US": "Panic reversal watch", "zh-CN": "恐慌反转观察"},
    "put_call_stress_watch": {"en-US": "Put/call stress watch", "zh-CN": "Put/call 压力观察"},
    "price_crisis_guard_active": {"en-US": "Price crisis guard active", "zh-CN": "价格危机保护激活"},
    "price_rebound_confirmation": {"en-US": "Price rebound confirmation", "zh-CN": "价格反弹确认"},
    "risk_off": {"en-US": "Risk off", "zh-CN": "风险关闭"},
    "risk_reduced": {"en-US": "Risk reduced", "zh-CN": "风险降低"},
    "safe_haven_demand_watch": {"en-US": "Safe-haven demand watch", "zh-CN": "避险需求观察"},
    "skew_high_watch": {"en-US": "SKEW high watch", "zh-CN": "SKEW 偏高观察"},
    "taco_rebound": {"en-US": "TACO rebound context", "zh-CN": "TACO 反弹上下文"},
    "true_crisis": {"en-US": "True crisis", "zh-CN": "真实危机"},
    "vix_crisis_level": {"en-US": "VIX crisis level", "zh-CN": "VIX 危机水平"},
    "vix_panic_reversal": {"en-US": "VIX panic reversal", "zh-CN": "VIX 恐慌回落"},
    "vix_spike": {"en-US": "VIX spike", "zh-CN": "VIX 尖峰"},
    "vix_term_structure_inverted_watch": {
        "en-US": "VIX term-structure inversion watch",
        "zh-CN": "VIX 期限结构倒挂观察",
    },
    "vix_watch_level": {"en-US": "VIX watch level", "zh-CN": "VIX 观察水平"},
    "vvix_high_watch": {"en-US": "VVIX high watch", "zh-CN": "VVIX 偏高观察"},
    "yield_curve_inversion_watch": {
        "en-US": "Yield-curve inversion watch",
        "zh-CN": "收益率曲线倒挂观察",
    },
    "watch": {"en-US": "Watch state", "zh-CN": "观察状态"},
}

OPPORTUNITY_REVIEW_STATUS_LABELS: dict[str, dict[str, str]] = {
    "blocked": {"en-US": "blocked", "zh-CN": "阻断状态"},
    "crisis": {"en-US": "crisis state", "zh-CN": "危机状态"},
    "delever": {"en-US": "de-risking state", "zh-CN": "降风险状态"},
    "no_action": {"en-US": "normal state", "zh-CN": "正常观察状态"},
    "opportunity_watch": {"en-US": "opportunity watch", "zh-CN": "机会观察状态"},
    "panic_reversal": {"en-US": "panic-reversal review", "zh-CN": "恐慌反转复核状态"},
    "risk_off": {"en-US": "defensive state", "zh-CN": "防守状态"},
    "risk_reduced": {"en-US": "de-risking state", "zh-CN": "降风险状态"},
    "taco_rebound": {"en-US": "event-rebound review", "zh-CN": "事件反弹复核状态"},
    "true_crisis": {"en-US": "crisis state", "zh-CN": "危机状态"},
    "watch": {"en-US": "watch state", "zh-CN": "观察状态"},
}

OPPORTUNITY_REVIEW_VETO_LABELS: dict[str, dict[str, str]] = {
    "crisis_blocks_panic_reversal": {
        "en-US": "crisis defense takes priority over the VIX panic-reversal signal",
        "zh-CN": "危机防守信号优先于 VIX 恐慌反转",
    },
    "crisis_blocks_taco": {
        "en-US": "crisis defense takes priority over the TACO rebound signal",
        "zh-CN": "危机防守信号优先于 TACO 事件反弹",
    },
    "macro_crisis_blocks_panic_reversal": {
        "en-US": "macro crisis signal takes priority over the VIX panic-reversal signal",
        "zh-CN": "宏观危机信号优先于 VIX 恐慌反转",
    },
    "macro_crisis_blocks_taco": {
        "en-US": "macro crisis signal takes priority over the TACO rebound signal",
        "zh-CN": "宏观危机信号优先于 TACO 事件反弹",
    },
    "macro_delever_blocks_panic_reversal": {
        "en-US": "macro de-risking signal takes priority over the VIX panic-reversal signal",
        "zh-CN": "宏观降风险信号优先于 VIX 恐慌反转",
    },
    "macro_delever_blocks_taco": {
        "en-US": "macro de-risking signal takes priority over the TACO rebound signal",
        "zh-CN": "宏观降风险信号优先于 TACO 事件反弹",
    },
}


PluginRunner = Callable[[Mapping[str, Any], str], PluginRunResult]
PluginPayloadBuilder = Callable[[pd.DataFrame, Mapping[str, Any]], dict[str, Any]]
PluginOutputWriter = Callable[[Mapping[str, Any], str | Path], Mapping[str, Path]]


@dataclass(frozen=True)
class PluginExecutionSpec:
    default_plugin: str
    build_payload: PluginPayloadBuilder
    write_outputs: PluginOutputWriter


def load_plugin_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"plugin config not found: {config_path}")
    return tomllib.loads(config_path.read_text(encoding="utf-8"))


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raw_values = value.split(",")
    else:
        raw_values = list(value)
    return tuple(str(item).strip() for item in raw_values if str(item).strip())


def _as_credit_pairs(value: Any) -> tuple[tuple[str, str], ...]:
    pairs: list[tuple[str, str]] = []
    for item in _as_str_tuple(value):
        parts = [part.strip().upper() for part in item.replace("/", ":").split(":")]
        if len(parts) != 2 or not all(parts):
            raise ValueError(f"credit pair must use NUMERATOR:DENOMINATOR syntax: {item!r}")
        pair = (parts[0], parts[1])
        if pair not in pairs:
            pairs.append(pair)
    return tuple(pairs)


def _optional_table(path: Any) -> pd.DataFrame | None:
    raw_path = str(path or "").strip()
    if not raw_path:
        return None
    return read_table(raw_path)


def _safe_scope_name(value: Any, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"strategy plugin entry requires {field}")
    safe = "".join(char if char.isalnum() or char in {"_", "-", "."} else "_" for char in text)
    return safe.strip("_") or text.replace("/", "_")


def _plugin_mode(plugin_config: Mapping[str, Any], default_mode: str) -> str:
    return str(plugin_config.get("mode", default_mode)).strip().lower()


def _validate_plugin_mode(plugin_name: str, mode: str) -> None:
    if mode not in SUPPORTED_PLUGIN_MODES:
        modes = ", ".join(SUPPORTED_PLUGIN_MODES)
        raise ValueError(f"{plugin_name} supports only configured modes {modes}; got mode={mode!r}")


def _validate_plugin_strategy(plugin_name: str, strategy: str) -> None:
    research_only_reason = PLUGIN_RESEARCH_ONLY_REASONS.get(plugin_name)
    if research_only_reason:
        raise ValueError(
            f"{plugin_name} is research-only and cannot be mounted to {strategy!r}: {research_only_reason}"
        )
    policy = PLUGIN_CONSUMPTION_POLICY_REGISTRY.get((plugin_name, strategy))
    if policy is None or not policy.notification_allowed:
        compatible = PLUGIN_COMPATIBLE_STRATEGIES.get(plugin_name, ())
        choices = ", ".join(compatible) if compatible else "(none)"
        raise ValueError(
            f"{plugin_name} is strategy-limited and can only be mounted to: {choices}; got strategy={strategy!r}"
        )


def _validate_plugin_notification_target(plugin_name: str, notification_target: str) -> None:
    policy = PLUGIN_NOTIFICATION_TARGET_POLICY_REGISTRY.get((plugin_name, notification_target))
    if policy is None or not policy.notification_allowed:
        compatible = PLUGIN_COMPATIBLE_NOTIFICATION_TARGETS.get(plugin_name, ())
        choices = ", ".join(compatible) if compatible else "(none)"
        raise ValueError(
            f"{plugin_name} is notification-target-limited and can only publish to: {choices}; "
            f"got notification_target={notification_target!r}"
        )


def _plugin_consumption_policy(plugin_name: str, strategy: str) -> PluginConsumptionPolicy | None:
    return PLUGIN_CONSUMPTION_POLICY_REGISTRY.get((plugin_name, strategy))


def _plugin_notification_target_policy(
    plugin_name: str,
    notification_target: str,
) -> PluginNotificationTargetPolicy | None:
    return PLUGIN_NOTIFICATION_TARGET_POLICY_REGISTRY.get((plugin_name, notification_target))


def _flatten_strategy_plugin_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    plugin_config = {
        key: value
        for key, value in entry.items()
        if key not in {"inputs", "outputs", "settings"}
    }
    for nested_key in ("inputs", "outputs", "settings"):
        nested = entry.get(nested_key, {})
        if nested is None:
            continue
        if not isinstance(nested, Mapping):
            raise ValueError(f"{nested_key} must be a table")
        duplicate_keys = sorted(set(plugin_config).intersection(nested))
        if duplicate_keys:
            keys = ", ".join(duplicate_keys)
            raise ValueError(f"duplicate strategy plugin config key(s) in {nested_key}: {keys}")
        plugin_config.update(nested)
    return plugin_config


def _default_plugin_output_dir(strategy: str, plugin: str) -> str:
    return str(Path("data/output") / strategy / "plugins" / plugin)


def _build_crisis_response_kwargs(plugin_config: Mapping[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    string_keys = {
        "as_of",
        "start_date",
        "end_date",
        "benchmark_symbol",
        "attack_symbol",
        "market_symbol",
        "synthetic_attack_from",
        "external_valuation_mode",
        "ai_audit_base_url",
        "ai_audit_model",
        "ai_audit_fallback_base_url",
        "ai_audit_fallback_model",
        "ai_audit_codex_model",
        "ai_audit_anthropic_base_url",
        "ai_audit_anthropic_model",
        "ai_audit_anthropic_version",
    }
    numeric_keys = {
        "synthetic_attack_multiple",
        "synthetic_attack_expense_rate",
        "crisis_drawdown",
        "crisis_risk_multiplier",
        "severe_crisis_risk_multiplier",
        "bubble_fragility_risk_multiplier",
        "bubble_fragility_drawdown",
        "external_trailing_pe_threshold",
        "external_forward_pe_threshold",
        "external_cape_threshold",
        "external_unprofitable_growth_threshold",
        "external_pct_above_200d_threshold",
        "external_pct_above_50d_threshold",
        "external_new_high_new_low_spread_threshold",
        "external_advance_decline_drawdown_threshold",
        "external_negative_earnings_share_threshold",
        "external_earnings_revision_3m_threshold",
        "external_margin_revision_3m_threshold",
        "ai_audit_timeout_seconds",
    }
    integer_keys = {
        "crisis_confirm_days",
        "bubble_fragility_ma_days",
        "bubble_fragility_ma_slope_days",
        "bubble_fragility_confirm_days",
        "max_price_age_days",
        "max_external_context_age_days",
    }
    for key in string_keys:
        if key in plugin_config and plugin_config[key] is not None:
            kwargs[key] = str(plugin_config[key]).strip()
    for key in numeric_keys:
        if key in plugin_config and plugin_config[key] is not None:
            kwargs[key] = float(plugin_config[key])
    for key in integer_keys:
        if key in plugin_config and plugin_config[key] is not None:
            kwargs[key] = int(plugin_config[key])
    for key in ("ai_audit_enabled", "ai_audit_codex_enabled"):
        if key in plugin_config and plugin_config[key] is not None:
            kwargs[key] = _as_bool(plugin_config[key])
    if "financial_symbols" in plugin_config:
        kwargs["financial_symbols"] = _as_str_tuple(plugin_config["financial_symbols"])
    if "rate_symbols" in plugin_config:
        kwargs["rate_symbols"] = _as_str_tuple(plugin_config["rate_symbols"])
    if "credit_pairs" in plugin_config:
        kwargs["credit_pairs"] = _as_credit_pairs(plugin_config["credit_pairs"])
    return kwargs


def _build_taco_rebound_kwargs(plugin_config: Mapping[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    string_keys = {
        "as_of",
        "start_date",
        "end_date",
        "benchmark_symbol",
        "attack_symbol",
        "ai_audit_base_url",
        "ai_audit_model",
        "ai_audit_fallback_base_url",
        "ai_audit_fallback_model",
        "ai_audit_codex_model",
        "ai_audit_anthropic_base_url",
        "ai_audit_anthropic_model",
        "ai_audit_anthropic_version",
    }
    numeric_keys = {
        "crisis_guard_drawdown",
        "min_benchmark_rebound_from_low",
        "min_attack_rebound_from_low",
        "min_benchmark_3d_return",
        "ai_audit_timeout_seconds",
    }
    integer_keys = {
        "active_signal_days",
        "crisis_guard_ma_days",
        "crisis_guard_ma_slope_days",
        "max_price_age_days",
        "confirmation_lookback_days",
        "min_confirmation_trading_days_after_event",
    }
    bool_keys = {
        "suppress_when_price_crisis_guard_active",
        "require_rebound_confirmation",
        "ai_audit_enabled",
        "ai_audit_codex_enabled",
    }
    for key in string_keys:
        if key in plugin_config and plugin_config[key] is not None:
            kwargs[key] = str(plugin_config[key]).strip()
    for key in numeric_keys:
        if key in plugin_config and plugin_config[key] is not None:
            kwargs[key] = float(plugin_config[key])
    for key in integer_keys:
        if key in plugin_config and plugin_config[key] is not None:
            kwargs[key] = int(plugin_config[key])
    for key in bool_keys:
        if key in plugin_config and plugin_config[key] is not None:
            kwargs[key] = _as_bool(plugin_config[key])
    return kwargs


def _build_panic_reversal_kwargs(plugin_config: Mapping[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    string_keys = {
        "as_of",
        "start_date",
        "end_date",
        "benchmark_symbol",
        "attack_symbol",
    }
    numeric_keys = {
        "min_vix_high",
        "min_vix_pullback_from_high",
        "min_vix_vix3m_ratio",
        "min_benchmark_rebound_from_low",
        "min_attack_rebound_from_low",
        "min_benchmark_3d_return",
        "crisis_guard_drawdown",
    }
    integer_keys = {
        "max_price_age_days",
        "max_vol_age_days",
        "vix_high_lookback_days",
        "confirmation_lookback_days",
        "crisis_guard_ma_days",
        "crisis_guard_ma_slope_days",
    }
    bool_keys = {
        "require_vix_term_structure",
        "suppress_when_price_crisis_guard_active",
    }
    for key in string_keys:
        if key in plugin_config and plugin_config[key] is not None:
            kwargs[key] = str(plugin_config[key]).strip()
    for key in numeric_keys:
        if key in plugin_config and plugin_config[key] is not None:
            kwargs[key] = float(plugin_config[key])
    for key in integer_keys:
        if key in plugin_config and plugin_config[key] is not None:
            kwargs[key] = int(plugin_config[key])
    for key in bool_keys:
        if key in plugin_config and plugin_config[key] is not None:
            kwargs[key] = _as_bool(plugin_config[key])
    if "vix_symbols" in plugin_config:
        kwargs["vix_symbols"] = _as_str_tuple(plugin_config["vix_symbols"])
    if "vix3m_symbols" in plugin_config:
        kwargs["vix3m_symbols"] = _as_str_tuple(plugin_config["vix3m_symbols"])
    return kwargs


def _build_macro_risk_governor_kwargs(plugin_config: Mapping[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    string_keys = {
        "as_of",
        "benchmark_symbol",
        "attack_symbol",
    }
    numeric_keys = {
        "benchmark_drawdown_watch",
        "benchmark_drawdown_crisis",
        "realized_vol_threshold",
        "vix_watch_level",
        "vix_crisis_level",
        "vix_spike_threshold",
        "credit_relative_threshold",
        "hy_oas_watch_level",
        "hy_oas_delta_threshold",
        "financial_stress_watch_level",
        "pizza_index_watch_level",
        "fear_greed_extreme_fear_level",
        "put_call_watch_level",
        "safe_haven_demand_watch_level",
        "vix_term_structure_watch_level",
        "vvix_watch_level",
        "skew_watch_level",
        "move_watch_level",
        "ig_oas_watch_level",
        "ig_oas_delta_threshold",
        "funding_stress_watch_level",
        "yield_curve_inversion_watch_level",
        "dollar_stress_return_threshold",
        "pct_above_200d_watch_level",
        "pct_above_50d_watch_level",
        "new_high_new_low_spread_watch_level",
        "advance_decline_drawdown_watch_level",
        "aaii_bear_bull_spread_watch_level",
        "naaim_exposure_watch_level",
        "watch_score_threshold",
        "delever_score_threshold",
        "crisis_score_threshold",
        "delever_leverage_scalar",
        "delever_risk_asset_scalar",
        "crisis_leverage_scalar",
        "crisis_risk_asset_scalar",
    }
    integer_keys = {
        "max_price_age_days",
        "max_external_context_age_days",
        "ma_days",
        "realized_vol_window",
        "vix_spike_lookback_days",
        "credit_relative_lookback_days",
        "hy_oas_delta_lookback_days",
    }
    bool_keys = {
        "realized_vol_requires_confirmation",
        "external_stress_actionable",
    }
    for key in string_keys:
        if key in plugin_config and plugin_config[key] is not None:
            kwargs[key] = str(plugin_config[key]).strip()
    for key in numeric_keys:
        if key in plugin_config and plugin_config[key] is not None:
            kwargs[key] = float(plugin_config[key])
    for key in integer_keys:
        if key in plugin_config and plugin_config[key] is not None:
            kwargs[key] = int(plugin_config[key])
    for key in bool_keys:
        if key in plugin_config and plugin_config[key] is not None:
            kwargs[key] = _as_bool(plugin_config[key])
    if "vix_symbols" in plugin_config:
        kwargs["vix_symbols"] = _as_str_tuple(plugin_config["vix_symbols"])
    if "vix3m_symbols" in plugin_config:
        kwargs["vix3m_symbols"] = _as_str_tuple(plugin_config["vix3m_symbols"])
    if "credit_pairs" in plugin_config:
        kwargs["credit_pairs"] = _as_credit_pairs(plugin_config["credit_pairs"])
    return kwargs


PLUGIN_MODE_EXECUTION_CONTROLS: dict[str, dict[str, Any]] = {
    SHADOW_MODE: {
        "capital_impact": "none",
        "broker_order_allowed": False,
        "live_allocation_mutation_allowed": False,
        "notification_profile": "shadow_only",
    },
}


def _mode_execution_controls(mode: str) -> dict[str, Any]:
    try:
        return dict(PLUGIN_MODE_EXECUTION_CONTROLS[mode])
    except KeyError as exc:
        raise ValueError(f"unsupported plugin mode: {mode!r}") from exc


def _payload_code(value: Any) -> str:
    return str(value or "").strip().lower()


def _localized_label(labels: Mapping[str, Mapping[str, str]], code: Any, locale: str) -> str:
    normalized = _payload_code(code)
    if not normalized:
        return ""
    localized = labels.get(normalized, {})
    if locale in localized:
        return localized[locale]
    if DEFAULT_MESSAGE_LOCALE in localized:
        return localized[DEFAULT_MESSAGE_LOCALE]
    return normalized if locale == "zh-CN" else normalized.replace("_", " ")


def _message_join(values: Sequence[str], locale: str) -> str:
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    if not cleaned:
        return "无" if locale == "zh-CN" else "none"
    return "、".join(cleaned) if locale == "zh-CN" else ", ".join(cleaned)


def _message_reason_codes(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def _nested_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, Mapping) else {}


def _payload_route(payload: Mapping[str, Any]) -> str:
    arbiter = _nested_mapping(payload, "arbiter")
    return _payload_code(payload.get("canonical_route") or payload.get("route") or arbiter.get("final_route"))


def _payload_action(payload: Mapping[str, Any]) -> str:
    arbiter = _nested_mapping(payload, "arbiter")
    return _payload_code(payload.get("suggested_action") or payload.get("action") or arbiter.get("suggested_action"))


def _payload_reason_codes(payload: Mapping[str, Any]) -> tuple[str, ...]:
    reason_codes: list[str] = []
    for container in (
        payload,
        _nested_mapping(payload, "arbiter"),
        _nested_mapping(payload, "notification"),
        _nested_mapping(payload, "position_control"),
    ):
        reason_codes.extend(_message_reason_codes(container.get("reason_codes")))
    if not reason_codes:
        route = _payload_route(payload)
        if route and route != "no_action":
            reason_codes.append(route)
    return tuple(dict.fromkeys(reason_codes))


def _localized_reason_label(reason_code: str, locale: str) -> str:
    source, separator, raw_code = str(reason_code).partition(":")
    if separator:
        source_label = _localized_label(LOCALIZED_SOURCE_LABELS, source, locale)
        reason_label = _localized_label(LOCALIZED_REASON_LABELS, raw_code, locale)
        separator_text = "：" if locale == "zh-CN" else ": "
        return f"{source_label}{separator_text}{reason_label}"
    return _localized_label(LOCALIZED_REASON_LABELS, source, locale)


def _localized_reason_labels(reason_codes: Sequence[str], locale: str) -> tuple[str, ...]:
    return tuple(_localized_reason_label(reason_code, locale) for reason_code in reason_codes)


def _localized_opportunity_status(route: str, locale: str) -> str:
    return _localized_label(OPPORTUNITY_REVIEW_STATUS_LABELS, route, locale)


def _localized_opportunity_veto_labels(vetoes: Sequence[str], locale: str) -> tuple[str, ...]:
    return tuple(_localized_label(OPPORTUNITY_REVIEW_VETO_LABELS, veto, locale) for veto in vetoes)


def _payload_should_notify(payload: Mapping[str, Any], route: str) -> bool:
    notification = _nested_mapping(payload, "notification")
    if "should_notify" in notification:
        return _as_bool(notification.get("should_notify"), default=False)
    if "manual_review_required" in payload:
        return _as_bool(payload.get("manual_review_required"), default=False) or route != "no_action"
    return route != "no_action"


def _as_float_or_none(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if pd.notna(result) else None


def _format_number(value: Any, *, digits: int = 2) -> str:
    number = _as_float_or_none(value)
    return "n/a" if number is None else f"{number:.{digits}f}"


def _format_pct(value: Any, *, digits: int = 1, signed: bool = False) -> str:
    number = _as_float_or_none(value)
    if number is None:
        return "n/a"
    sign = "+" if signed and number > 0 else ""
    return f"{sign}{number * 100:.{digits}f}%"


def _component_payload(payload: Mapping[str, Any], component: str) -> Mapping[str, Any]:
    components = _nested_mapping(payload, "component_signals")
    value = components.get(component)
    return value if isinstance(value, Mapping) and value.get("available", True) else {}


def _active_panic_payload(payload: Mapping[str, Any], plugin: str) -> Mapping[str, Any]:
    if plugin == PLUGIN_PANIC_REVERSAL_SHADOW or "reversal_confirmation" in payload:
        return payload
    component = _component_payload(payload, "panic_reversal")
    if not component:
        return {}
    if _as_bool(component.get("manual_review_required"), default=False) or _as_bool(
        component.get("panic_reversal_context_active"),
        default=False,
    ):
        return component
    return {}


def _vetoed_opportunity_components(payload: Mapping[str, Any]) -> frozenset[str]:
    notification = _nested_mapping(payload, "notification")
    raw = notification.get("vetoed_opportunities")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return frozenset()
    components: set[str] = set()
    for item in raw:
        if isinstance(item, Mapping):
            component = str(item.get("component") or "").strip().lower()
            if component:
                components.add(component)
    return frozenset(components)


def _active_taco_payload(payload: Mapping[str, Any], plugin: str) -> Mapping[str, Any]:
    if plugin == PLUGIN_TACO_REBOUND_SHADOW or "rebound_confirmation" in payload:
        return payload
    component = _component_payload(payload, "taco")
    if not component:
        return {}
    if _as_bool(component.get("manual_review_required"), default=False) or _as_bool(
        component.get("rebound_context_active"),
        default=False,
    ):
        return component
    return {}


def _review_attack_symbol(*sources: Mapping[str, Any]) -> str:
    for source in sources:
        for container_key in ("metrics", "rebound_confirmation"):
            container = source.get(container_key)
            if isinstance(container, Mapping):
                symbol = str(container.get("attack_symbol") or "").strip().upper()
                if symbol:
                    return symbol
    return ""


def _review_benchmark_symbol(*sources: Mapping[str, Any]) -> str:
    for source in sources:
        for container_key in ("metrics", "rebound_confirmation"):
            container = source.get(container_key)
            if isinstance(container, Mapping):
                symbol = str(container.get("benchmark_symbol") or "").strip().upper()
                if symbol:
                    return symbol
    return ""


def _manual_review_source_title(
    *,
    panic_payload: Mapping[str, Any],
    taco_payload: Mapping[str, Any],
    locale: str,
) -> str:
    panic_active = bool(panic_payload)
    taco_active = bool(taco_payload)
    if locale == "zh-CN":
        if panic_active and taco_active:
            return "事件缓和 + VIX 恐慌反转共振"
        if panic_active:
            return "VIX 恐慌反转"
        if taco_active:
            return "TACO 事件反弹"
        return "机会观察"
    if panic_active and taco_active:
        return "event de-escalation + VIX panic reversal"
    if panic_active:
        return "VIX panic reversal"
    if taco_active:
        return "TACO event rebound"
    return "opportunity watch"


def _append_panic_review_lines(lines: list[str], panic_payload: Mapping[str, Any], *, locale: str) -> None:
    metrics = _nested_mapping(panic_payload, "metrics")
    confirmation = _nested_mapping(panic_payload, "reversal_confirmation")
    thresholds = _nested_mapping(confirmation, "thresholds")
    benchmark = str(metrics.get("benchmark_symbol") or "benchmark").upper()
    attack = str(metrics.get("attack_symbol") or "attack").upper()
    if locale == "zh-CN":
        lines.extend(
            [
                (
                    "- VIX 曾达到恐慌区间："
                    f"{int(_as_float_or_none(thresholds.get('vix_high_lookback_days')) or 5)} 日高点 "
                    f"{_format_number(metrics.get('vix_lookback_high'))}，阈值 "
                    f"{_format_number(thresholds.get('min_vix_high'))}"
                ),
                (
                    "- VIX 已从高点回落："
                    f"当前 {_format_number(metrics.get('vix'))}，较高点回落 "
                    f"{_format_pct(metrics.get('vix_pullback_from_high'))}"
                ),
                (
                    "- VIX 继续下降："
                    f"前值 {_format_number(metrics.get('vix_previous'))}，当前 {_format_number(metrics.get('vix'))}"
                ),
                (
                    "- VIX/VIX3M = "
                    f"{_format_number(metrics.get('vix_vix3m_ratio'))}，用于确认恐慌结构仍可观测"
                ),
                (
                    f"- {benchmark} 3 日收益 {_format_pct(metrics.get('benchmark_3d_return'), signed=True)}，"
                    f"从近 5 日低点反弹 {_format_pct(metrics.get('benchmark_rebound_from_recent_low'), signed=True)}"
                ),
                f"- {attack} 从近 5 日低点反弹 {_format_pct(metrics.get('attack_rebound_from_recent_low'), signed=True)}",
            ]
        )
        return
    lines.extend(
        [
            (
                "- VIX reached panic territory: "
                f"{int(_as_float_or_none(thresholds.get('vix_high_lookback_days')) or 5)}-day high "
                f"{_format_number(metrics.get('vix_lookback_high'))}; threshold "
                f"{_format_number(thresholds.get('min_vix_high'))}"
            ),
            (
                "- VIX has pulled back from the high: "
                f"current {_format_number(metrics.get('vix'))}, pullback "
                f"{_format_pct(metrics.get('vix_pullback_from_high'))}"
            ),
            (
                "- VIX is still falling: "
                f"previous {_format_number(metrics.get('vix_previous'))}, current {_format_number(metrics.get('vix'))}"
            ),
            f"- VIX/VIX3M = {_format_number(metrics.get('vix_vix3m_ratio'))}",
            (
                f"- {benchmark} 3-day return {_format_pct(metrics.get('benchmark_3d_return'), signed=True)}; "
                f"rebound from recent low {_format_pct(metrics.get('benchmark_rebound_from_recent_low'), signed=True)}"
            ),
            f"- {attack} rebound from recent low {_format_pct(metrics.get('attack_rebound_from_recent_low'), signed=True)}",
        ]
    )


def _append_taco_review_lines(lines: list[str], taco_payload: Mapping[str, Any], *, locale: str) -> None:
    event = _nested_mapping(taco_payload, "selected_event")
    confirmation = _nested_mapping(taco_payload, "rebound_confirmation")
    benchmark = str(confirmation.get("benchmark_symbol") or "benchmark").upper()
    attack = str(confirmation.get("attack_symbol") or "attack").upper()
    if locale == "zh-CN":
        lines.extend(
            [
                "事件：",
                f"- 类型：{event.get('kind') or 'n/a'} / 区域：{event.get('region') or 'n/a'}",
                f"- 日期：{event.get('event_date') or 'n/a'}",
                f"- 标题：{event.get('title') or 'n/a'}",
                f"- 来源：{event.get('source') or 'n/a'}",
                "价格确认：",
                f"- 事件后已过 {confirmation.get('trading_days_after_event', 'n/a')} 个交易日",
                (
                    f"- {benchmark} 3 日收益 {_format_pct(confirmation.get('benchmark_3d_return'), signed=True)}，"
                    f"从近 5 日低点反弹 "
                    f"{_format_pct(confirmation.get('benchmark_rebound_from_recent_low'), signed=True)}"
                ),
                f"- {attack} 从近 5 日低点反弹 {_format_pct(confirmation.get('attack_rebound_from_recent_low'), signed=True)}",
            ]
        )
        return
    lines.extend(
        [
            "Event:",
            f"- Type: {event.get('kind') or 'n/a'} / region: {event.get('region') or 'n/a'}",
            f"- Date: {event.get('event_date') or 'n/a'}",
            f"- Title: {event.get('title') or 'n/a'}",
            f"- Source: {event.get('source') or 'n/a'}",
            "Price confirmation:",
            f"- {confirmation.get('trading_days_after_event', 'n/a')} trading days after the event",
            (
                f"- {benchmark} 3-day return {_format_pct(confirmation.get('benchmark_3d_return'), signed=True)}; "
                f"rebound from recent low "
                f"{_format_pct(confirmation.get('benchmark_rebound_from_recent_low'), signed=True)}"
            ),
            f"- {attack} rebound from recent low {_format_pct(confirmation.get('attack_rebound_from_recent_low'), signed=True)}",
        ]
    )


def _format_manual_review_notification_message(
    payload: Mapping[str, Any],
    *,
    locale: str,
    target_label: str,
    plugin: str,
    as_of: str,
    route: str,
) -> str | None:
    vetoed_components = _vetoed_opportunity_components(payload)
    is_vetoed_opportunity_notice = bool(vetoed_components)
    if _payload_action(payload) != "notify_manual_review" and not is_vetoed_opportunity_notice:
        return None
    panic_payload = _active_panic_payload(payload, plugin)
    taco_payload = _active_taco_payload(payload, plugin)
    if "panic_reversal" not in vetoed_components and is_vetoed_opportunity_notice:
        panic_payload = {}
    if "taco" not in vetoed_components and is_vetoed_opportunity_notice:
        taco_payload = {}
    if not panic_payload and not taco_payload:
        return None

    vetoes = _message_reason_codes(_nested_mapping(payload, "arbiter").get("vetoes"))
    attack_symbol = _review_attack_symbol(panic_payload, taco_payload) or target_label
    benchmark_symbol = _review_benchmark_symbol(panic_payload, taco_payload)
    source_title = _manual_review_source_title(panic_payload=panic_payload, taco_payload=taco_payload, locale=locale)
    if locale == "zh-CN":
        benchmark_label = benchmark_symbol or "基准指数"
        route_status = _localized_opportunity_status(route, locale)
        veto_text = _message_join(_localized_opportunity_veto_labels(vetoes, locale), locale)
        card_prefix = "机会被拦截" if is_vetoed_opportunity_notice else "机会复核"
        if panic_payload and taco_payload:
            opportunity_summary = (
                f"- 事件缓和与 VIX 恐慌回落同时出现，{benchmark_label}/{attack_symbol} 已从短期低点反弹，"
                "属于恐慌后反转复核信号。"
            )
        elif panic_payload:
            opportunity_summary = (
                f"- VIX 已从极端恐慌高位回落，{benchmark_label}/{attack_symbol} 已从短期低点反弹，"
                "出现恐慌后反转观察信号。"
            )
        else:
            opportunity_summary = (
                f"- 事件缓和后，{benchmark_label}/{attack_symbol} 出现反弹确认，出现事件反弹复核信号。"
            )
        situation_lines = [opportunity_summary]
        if is_vetoed_opportunity_notice:
            situation_lines.append(f"- 但当前仍处于{route_status}，说明策略环境还没有完全解除防守。")
            if vetoes:
                situation_lines.append(f"- {veto_text}，所以这条通知先作为人工检查线索。")
        else:
            situation_lines.append(f"- 当前处于{route_status}，可以进入人工复核。")
        if is_vetoed_opportunity_notice:
            if panic_payload and taco_payload:
                confirmation_line = (
                    f"- 先看 VIX 是否继续回落、事件是否继续缓和、{benchmark_label}/{attack_symbol} "
                    "反弹是否维持，避免把一次反抽误判为趋势恢复。"
                )
            elif panic_payload:
                confirmation_line = (
                    f"- 先看 VIX 是否继续回落、{benchmark_label}/{attack_symbol} 反弹是否维持，"
                    "避免把一次反抽误判为趋势恢复。"
                )
            else:
                confirmation_line = (
                    f"- 先看事件是否继续缓和、{benchmark_label}/{attack_symbol} 反弹是否维持，"
                    "避免把一次反抽误判为趋势恢复。"
                )
            guidance_lines = [
                confirmation_line,
                "- 对照策略侧当前仓位和风控状态，判断是否停止继续降风险、恢复观察，或继续保持防守。",
                "- 如果 VIX 回升、价格跌回短期低点附近，忽略本次机会信号。",
            ]
        else:
            if panic_payload and taco_payload:
                confirmation_target = f"VIX 和事件是否继续改善，{benchmark_label}/{attack_symbol}"
                reversal_target = "VIX、事件或价格确认"
            elif panic_payload:
                confirmation_target = f"VIX 是否继续回落，{benchmark_label}/{attack_symbol}"
                reversal_target = "VIX 或价格确认"
            else:
                confirmation_target = f"事件是否继续缓和，{benchmark_label}/{attack_symbol}"
                reversal_target = "事件或价格确认"
            guidance_lines = [
                f"- 检查 {confirmation_target} 的价格确认是否延续。",
                "- 对照策略侧仓位和风险预算，判断是否需要人工干预。",
                f"- 如果 {reversal_target}反转，忽略本次信号。",
            ]
        lines = [
            f"【{card_prefix}｜{attack_symbol}｜{source_title}】",
            f"日期：{as_of or '未知日期'}",
            "情况说明：",
            *situation_lines,
        ]
        if panic_payload:
            _append_panic_review_lines(lines, panic_payload, locale=locale)
        if taco_payload:
            _append_taco_review_lines(lines, taco_payload, locale=locale)
        lines.extend(
            [
                "建议操作：",
                *guidance_lines,
            ]
        )
        return "\n".join(lines)

    benchmark_label = benchmark_symbol or "benchmark"
    route_status = _localized_opportunity_status(route, locale)
    veto_text = _message_join(_localized_opportunity_veto_labels(vetoes, locale), locale)
    card_prefix = "Opportunity Vetoed" if is_vetoed_opportunity_notice else "Opportunity Review"
    if panic_payload and taco_payload:
        opportunity_summary = (
            f"- Event de-escalation and a VIX panic pullback are both present; {benchmark_label}/{attack_symbol} "
            "has rebounded from short-term lows, so this is a panic-reversal review signal."
        )
    elif panic_payload:
        opportunity_summary = (
            f"- VIX has pulled back from extreme panic levels, and {benchmark_label}/{attack_symbol} "
            "has rebounded from short-term lows, so this is a panic-reversal watch signal."
        )
    else:
        opportunity_summary = (
            f"- After event de-escalation, {benchmark_label}/{attack_symbol} shows rebound confirmation, "
            "so this is an event-rebound review signal."
        )
    situation_lines = [opportunity_summary]
    if is_vetoed_opportunity_notice:
        situation_lines.append(f"- Current state is still {route_status}, so the strategy environment is not fully out of defense.")
        if vetoes:
            situation_lines.append(f"- {veto_text}; treat this notification as a manual check cue for now.")
    else:
        situation_lines.append(f"- Current state is {route_status}, so it can move into manual review.")
    if is_vetoed_opportunity_notice:
        if panic_payload and taco_payload:
            confirmation_line = (
                f"- Check whether VIX keeps falling, the event keeps de-escalating, and the "
                f"{benchmark_label}/{attack_symbol} rebound holds; avoid treating a one-day bounce as recovery."
            )
        elif panic_payload:
            confirmation_line = (
                f"- Check whether VIX keeps falling and whether the {benchmark_label}/{attack_symbol} rebound holds; "
                "avoid treating a one-day bounce as recovery."
            )
        else:
            confirmation_line = (
                f"- Check whether the event keeps de-escalating and whether the "
                f"{benchmark_label}/{attack_symbol} rebound holds; avoid treating a one-day bounce as recovery."
            )
        guidance_lines = [
            confirmation_line,
            "- Compare against the strategy-side exposure and risk-control state before deciding whether to stop further de-risking, return to watch, or stay defensive.",
            "- Ignore this opportunity signal if VIX rises again or price falls back near short-term lows.",
        ]
    else:
        if panic_payload and taco_payload:
            confirmation_target = f"VIX and event conditions keep improving and whether {benchmark_label}/{attack_symbol}"
            reversal_target = "VIX, event context, or price confirmation"
        elif panic_payload:
            confirmation_target = f"VIX keeps falling and whether {benchmark_label}/{attack_symbol}"
            reversal_target = "VIX or price confirmation"
        else:
            confirmation_target = f"the event keeps de-escalating and whether {benchmark_label}/{attack_symbol}"
            reversal_target = "event context or price confirmation"
        guidance_lines = [
            f"- Check whether {confirmation_target} price confirmation continues.",
            "- Compare against strategy-side exposure and risk budget before any manual intervention.",
            f"- Ignore this signal if {reversal_target} reverses.",
        ]
    lines = [
        f"[{card_prefix} | {attack_symbol} | {source_title}]",
        f"Date: {as_of or 'unknown date'}",
        "Situation:",
        *situation_lines,
    ]
    if panic_payload:
        _append_panic_review_lines(lines, panic_payload, locale=locale)
    if taco_payload:
        _append_taco_review_lines(lines, taco_payload, locale=locale)
    lines.extend(
        [
            "Suggested action:",
            *guidance_lines,
        ]
    )
    return "\n".join(lines)


def _format_notification_message(
    *,
    locale: str,
    target_label: str,
    target_type: str,
    plugin_label: str,
    as_of: str,
    route_label: str,
    action_label: str,
    reason_labels: Sequence[str],
    should_notify: bool,
) -> str:
    reason_text = _message_join(reason_labels, locale)
    if locale == "zh-CN":
        prefix = "需要通知" if should_notify else "无需通知"
        scope = "通知目标" if target_type == "notification_target" else "策略"
        return (
            f"{prefix}：{scope} {target_label} 的 {plugin_label} 在 {as_of or '未知日期'} 输出"
            f"市场状态 {route_label}，建议动作 {action_label}，原因：{reason_text}。"
        )
    prefix = "Notification required" if should_notify else "No notification required"
    scope = "notification target" if target_type == "notification_target" else "strategy"
    return (
        f"{prefix}: {plugin_label} for {scope} {target_label} produced market regime {route_label} "
        f"on {as_of or 'unknown date'} with suggested action {action_label}. Reasons: {reason_text}."
    )


def _format_log_message(
    *,
    locale: str,
    target_label: str,
    target_type: str,
    plugin: str,
    plugin_label: str,
    as_of: str,
    route: str,
    action: str,
    route_label: str,
    action_label: str,
    reason_codes: Sequence[str],
    reason_labels: Sequence[str],
) -> str:
    code_text = _message_join(reason_codes, "en-US")
    label_text = _message_join(reason_labels, locale)
    if locale == "zh-CN":
        target_key = "通知目标" if target_type == "notification_target" else "策略"
        return (
            f"{target_key}={target_label} 插件={plugin_label} 日期={as_of or '未知'} "
            f"路线={route_label} 动作={action_label} 原因={label_text}"
        )
    return (
        f"target_type={target_type} target={target_label} plugin={plugin} as_of={as_of or 'unknown'} route={route}({route_label}) "
        f"action={action}({action_label}) reason_codes={code_text} reasons={label_text}"
    )


def _build_localized_messages(
    payload: Mapping[str, Any],
    *,
    strategy: str | None = None,
    notification_target: str | None = None,
    plugin: str,
) -> dict[str, Any]:
    route = _payload_route(payload) or "unknown"
    action = _payload_action(payload) or "unknown"
    reason_codes = _payload_reason_codes(payload)
    as_of = str(payload.get("as_of") or "").strip()
    should_notify = _payload_should_notify(payload, route)
    target_type = "notification_target" if notification_target else "strategy"
    target_label = str(notification_target or strategy or "").strip()

    route_labels = {
        locale: _localized_label(LOCALIZED_ROUTE_LABELS, route, locale) for locale in SUPPORTED_MESSAGE_LOCALES
    }
    action_labels = {
        locale: _localized_label(LOCALIZED_ACTION_LABELS, action, locale) for locale in SUPPORTED_MESSAGE_LOCALES
    }
    reason_labels = {
        locale: list(_localized_reason_labels(reason_codes, locale)) for locale in SUPPORTED_MESSAGE_LOCALES
    }
    plugin_labels = {
        locale: _localized_label(LOCALIZED_PLUGIN_LABELS, plugin, locale) for locale in SUPPORTED_MESSAGE_LOCALES
    }
    notification_messages = {
        locale: _format_manual_review_notification_message(
            payload,
            locale=locale,
            target_label=target_label,
            plugin=plugin,
            as_of=as_of,
            route=route,
        )
        or _format_notification_message(
            locale=locale,
            target_label=target_label,
            target_type=target_type,
            plugin_label=plugin_labels[locale],
            as_of=as_of,
            route_label=route_labels[locale],
            action_label=action_labels[locale],
            reason_labels=reason_labels[locale],
            should_notify=should_notify,
        )
        for locale in SUPPORTED_MESSAGE_LOCALES
    }
    log_messages = {
        locale: _format_log_message(
            locale=locale,
            target_label=target_label,
            target_type=target_type,
            plugin=plugin,
            plugin_label=plugin_labels[locale],
            as_of=as_of,
            route=route,
            action=action,
            route_label=route_labels[locale],
            action_label=action_labels[locale],
            reason_codes=reason_codes,
            reason_labels=reason_labels[locale],
        )
        for locale in SUPPORTED_MESSAGE_LOCALES
    }
    return {
        "schema_version": STRATEGY_PLUGIN_MESSAGE_SCHEMA_VERSION,
        "default_locale": DEFAULT_MESSAGE_LOCALE,
        "supported_locales": list(SUPPORTED_MESSAGE_LOCALES),
        "labels": {
            "plugin": plugin_labels,
            "canonical_route": route_labels,
            "suggested_action": action_labels,
            "reason_codes": reason_labels,
        },
        "notification": notification_messages,
        "log": log_messages,
    }


def _build_log_record(
    payload: Mapping[str, Any],
    *,
    strategy: str | None = None,
    notification_target: str | None = None,
    plugin: str,
    mode: str,
    localized_messages: Mapping[str, Any],
) -> dict[str, Any]:
    reason_codes = _payload_reason_codes(payload)
    execution_controls = _nested_mapping(payload, "execution_controls")
    return {
        "schema_version": STRATEGY_PLUGIN_LOG_SCHEMA_VERSION,
        "event": "strategy_plugin_signal",
        "namespace": str(execution_controls.get("log_namespace") or plugin),
        "target_type": "notification_target" if notification_target else "strategy",
        "strategy": strategy or "",
        "notification_target": notification_target or "",
        "plugin": plugin,
        "mode": mode,
        "as_of": str(payload.get("as_of") or "").strip(),
        "canonical_route": _payload_route(payload),
        "suggested_action": _payload_action(payload),
        "reason_codes": list(reason_codes),
        "default_locale": DEFAULT_MESSAGE_LOCALE,
        "localized_messages": dict(localized_messages.get("log", {})),
    }


def _apply_plugin_contract(
    payload: Mapping[str, Any],
    *,
    strategy: str | None = None,
    notification_target: str | None = None,
    plugin: str,
    mode: str,
    consumption_policy: PluginConsumptionPolicy | None = None,
    notification_target_policy: PluginNotificationTargetPolicy | None = None,
) -> dict[str, Any]:
    contracted_payload = dict(payload)
    if strategy:
        contracted_payload["target_type"] = "strategy"
        contracted_payload["strategy"] = strategy
        contracted_payload.pop("notification_target", None)
    elif notification_target:
        contracted_payload["target_type"] = "notification_target"
        contracted_payload["notification_target"] = notification_target
        contracted_payload.pop("strategy", None)
    else:
        raise ValueError("plugin contract requires either strategy or notification_target")
    contracted_payload["plugin"] = plugin
    contracted_payload["mode"] = mode
    contracted_payload["configured_mode"] = mode
    contracted_payload["effective_mode"] = mode
    if consumption_policy is not None:
        contracted_payload["consumption_policy"] = asdict(consumption_policy)
    if notification_target_policy is not None:
        contracted_payload["notification_target_policy"] = asdict(notification_target_policy)

    execution_controls = dict(contracted_payload.get("execution_controls") or {})
    execution_controls.update(_mode_execution_controls(mode))
    execution_controls["configured_mode"] = mode
    execution_controls["effective_mode"] = mode
    execution_controls["repository_broker_write_allowed"] = False
    execution_controls["repository_allocation_mutation_allowed"] = False
    if consumption_policy is not None:
        execution_controls["notification_allowed"] = bool(consumption_policy.notification_allowed)
        execution_controls["position_control_allowed"] = bool(consumption_policy.position_control_allowed)
        execution_controls["consumption_evidence_status"] = consumption_policy.evidence_status
        if consumption_policy.position_control_allowed:
            execution_controls["capital_impact"] = "strategy_opt_in"
            execution_controls["strategy_runtime_metadata_allowed"] = True
            execution_controls["position_control_shadow_only"] = False
        else:
            execution_controls["capital_impact"] = "notification_only"
            execution_controls["strategy_runtime_metadata_allowed"] = False
            execution_controls["position_control_shadow_only"] = True
    if notification_target_policy is not None:
        execution_controls["notification_allowed"] = bool(notification_target_policy.notification_allowed)
        execution_controls["position_control_allowed"] = False
        execution_controls["consumption_evidence_status"] = notification_target_policy.evidence_status
        execution_controls["notification_role"] = notification_target_policy.notification_role
        execution_controls["capital_impact"] = "notification_only"
        execution_controls["strategy_runtime_metadata_allowed"] = False
        execution_controls["position_control_shadow_only"] = True
        execution_controls["notification_target"] = notification_target
        execution_controls["target_type"] = "notification_target"
    execution_controls["mode_note"] = (
        "Mode is the platform behavior contract; this repository writes artifacts and does not call brokers"
    )
    execution_controls["message_i18n_schema_version"] = STRATEGY_PLUGIN_MESSAGE_SCHEMA_VERSION
    execution_controls["log_schema_version"] = STRATEGY_PLUGIN_LOG_SCHEMA_VERSION
    execution_controls["default_locale"] = DEFAULT_MESSAGE_LOCALE
    execution_controls["supported_locales"] = list(SUPPORTED_MESSAGE_LOCALES)
    contracted_payload["execution_controls"] = execution_controls
    localized_messages = _build_localized_messages(
        contracted_payload,
        strategy=strategy,
        notification_target=notification_target,
        plugin=plugin,
    )
    contracted_payload["localized_messages"] = localized_messages
    contracted_payload["log_record"] = _build_log_record(
        contracted_payload,
        strategy=strategy,
        notification_target=notification_target,
        plugin=plugin,
        mode=mode,
        localized_messages=localized_messages,
    )
    notification = contracted_payload.get("notification")
    if isinstance(notification, Mapping):
        localized_notification = dict(notification)
        localized_notification["localized_message_schema_version"] = STRATEGY_PLUGIN_MESSAGE_SCHEMA_VERSION
        localized_notification["default_locale"] = DEFAULT_MESSAGE_LOCALE
        localized_notification["supported_locales"] = list(SUPPORTED_MESSAGE_LOCALES)
        localized_notification["localized_messages"] = dict(localized_messages["notification"])
        localized_notification["localized_reason_labels"] = dict(localized_messages["labels"]["reason_codes"])
        contracted_payload["notification"] = localized_notification
    return contracted_payload


def _build_crisis_response_payload(price_history: pd.DataFrame, plugin_config: Mapping[str, Any]) -> dict[str, Any]:
    external_context = _optional_table(plugin_config.get("external_context"))
    event_set = str(plugin_config.get("event_set", DEFAULT_EVENT_SET)).strip() or DEFAULT_EVENT_SET
    return build_crisis_response_shadow_signal(
        price_history,
        events=resolve_trade_war_event_set(event_set),
        external_context=external_context,
        **_build_crisis_response_kwargs(plugin_config),
    )


def _build_taco_rebound_payload(price_history: pd.DataFrame, plugin_config: Mapping[str, Any]) -> dict[str, Any]:
    event_set = str(plugin_config.get("event_set", DEFAULT_EVENT_SET)).strip() or DEFAULT_EVENT_SET
    return build_taco_rebound_shadow_signal(
        price_history,
        events=resolve_trade_war_event_set(event_set),
        **_build_taco_rebound_kwargs(plugin_config),
    )


def _build_panic_reversal_payload(price_history: pd.DataFrame, plugin_config: Mapping[str, Any]) -> dict[str, Any]:
    external_context = _optional_table(plugin_config.get("external_context"))
    return build_panic_reversal_shadow_signal(
        price_history,
        external_context=external_context,
        **_build_panic_reversal_kwargs(plugin_config),
    )


def _build_macro_risk_governor_payload(price_history: pd.DataFrame, plugin_config: Mapping[str, Any]) -> dict[str, Any]:
    external_context = _optional_table(plugin_config.get("external_context"))
    return build_macro_risk_governor_signal(
        price_history,
        external_context=external_context,
        **_build_macro_risk_governor_kwargs(plugin_config),
    )


def _build_market_regime_control_payload(price_history: pd.DataFrame, plugin_config: Mapping[str, Any]) -> dict[str, Any]:
    components: dict[str, Mapping[str, Any]] = {}
    if _as_bool(plugin_config.get("crisis_enabled"), default=True):
        components["crisis"] = _build_crisis_response_payload(price_history, plugin_config)
    if _as_bool(plugin_config.get("macro_enabled"), default=True):
        components["macro"] = _build_macro_risk_governor_payload(price_history, plugin_config)
    if _as_bool(plugin_config.get("taco_enabled"), default=True):
        components["taco"] = _build_taco_rebound_payload(price_history, plugin_config)
    if _as_bool(plugin_config.get("panic_reversal_enabled"), default=False):
        panic_config = dict(plugin_config)
        panic_config.setdefault("suppress_when_price_crisis_guard_active", False)
        components["panic_reversal"] = _build_panic_reversal_payload(price_history, panic_config)
    return build_market_regime_control_signal(
        components,
        strategy_policy=str(plugin_config.get("strategy_policy", "levered_growth_income_v1")).strip(),
        taco_opportunity_size_scalar=float(plugin_config.get("taco_opportunity_size_scalar", 0.0) or 0.0),
        volatility_delever_price_rebound_context=build_volatility_delever_price_rebound_context(
            price_history,
            plugin_config,
        ),
        as_of=str(plugin_config.get("as_of", "") or "").strip() or None,
    )


def _run_table_strategy_plugin(
    plugin_config: Mapping[str, Any],
    default_mode: str,
    spec: PluginExecutionSpec,
) -> PluginRunResult:
    strategy = _safe_scope_name(plugin_config.get("strategy"), field="strategy")
    plugin = _safe_scope_name(plugin_config.get("plugin", spec.default_plugin), field="plugin")
    mode = _plugin_mode(plugin_config, default_mode)
    output_dir = str(plugin_config.get("output_dir") or _default_plugin_output_dir(strategy, plugin)).strip()
    enabled = _as_bool(plugin_config.get("enabled"), default=True)
    if not enabled:
        return PluginRunResult(
            strategy=strategy,
            plugin=plugin,
            enabled=False,
            mode=mode,
            effective_mode=None,
            status="skipped",
            output_dir=output_dir,
            message="plugin disabled",
        )
    _validate_plugin_mode(plugin, mode)
    _validate_plugin_strategy(plugin, strategy)
    consumption_policy = _plugin_consumption_policy(plugin, strategy)

    prices_path = str(plugin_config.get("prices", "")).strip()
    if not prices_path:
        raise ValueError(f"{plugin} for strategy={strategy} requires a prices path")
    payload = spec.build_payload(read_table(prices_path), plugin_config)
    payload = _apply_plugin_contract(
        payload,
        strategy=strategy,
        plugin=plugin,
        mode=mode,
        consumption_policy=consumption_policy,
    )
    paths = spec.write_outputs(payload, output_dir)
    return PluginRunResult(
        strategy=strategy,
        plugin=plugin,
        enabled=True,
        mode=mode,
        effective_mode=mode,
        status="ok",
        output_dir=output_dir,
        latest_signal_path=str(paths["latest_signal"]),
        message=f"route={payload['canonical_route']} action={payload['suggested_action']}",
    )


def _run_table_notification_target_plugin(
    plugin_config: Mapping[str, Any],
    default_mode: str,
    spec: PluginExecutionSpec,
) -> PluginRunResult:
    notification_target = _safe_scope_name(plugin_config.get("notification_target"), field="notification_target")
    plugin = _safe_scope_name(plugin_config.get("plugin", spec.default_plugin), field="plugin")
    mode = _plugin_mode(plugin_config, default_mode)
    output_dir = str(plugin_config.get("output_dir") or _default_plugin_output_dir(notification_target, plugin)).strip()
    enabled = _as_bool(plugin_config.get("enabled"), default=True)
    if not enabled:
        return PluginRunResult(
            strategy="",
            plugin=plugin,
            enabled=False,
            mode=mode,
            effective_mode=None,
            status="skipped",
            output_dir=output_dir,
            message="plugin disabled",
            target_type="notification_target",
            notification_target=notification_target,
        )
    _validate_plugin_mode(plugin, mode)
    _validate_plugin_notification_target(plugin, notification_target)
    notification_target_policy = _plugin_notification_target_policy(plugin, notification_target)

    prices_path = str(plugin_config.get("prices", "")).strip()
    if not prices_path:
        raise ValueError(f"{plugin} for notification_target={notification_target} requires a prices path")
    payload = spec.build_payload(read_table(prices_path), plugin_config)
    payload = _apply_plugin_contract(
        payload,
        notification_target=notification_target,
        plugin=plugin,
        mode=mode,
        notification_target_policy=notification_target_policy,
    )
    paths = spec.write_outputs(payload, output_dir)
    return PluginRunResult(
        strategy="",
        plugin=plugin,
        enabled=True,
        mode=mode,
        effective_mode=mode,
        status="ok",
        output_dir=output_dir,
        latest_signal_path=str(paths["latest_signal"]),
        message=f"route={payload['canonical_route']} action={payload['suggested_action']}",
        target_type="notification_target",
        notification_target=notification_target,
    )


CRISIS_RESPONSE_SHADOW_SPEC = PluginExecutionSpec(
    default_plugin=PLUGIN_CRISIS_RESPONSE_SHADOW,
    build_payload=_build_crisis_response_payload,
    write_outputs=write_crisis_response_shadow_outputs,
)
TACO_REBOUND_SHADOW_SPEC = PluginExecutionSpec(
    default_plugin=PLUGIN_TACO_REBOUND_SHADOW,
    build_payload=_build_taco_rebound_payload,
    write_outputs=write_taco_rebound_shadow_outputs,
)
PANIC_REVERSAL_SHADOW_SPEC = PluginExecutionSpec(
    default_plugin=PLUGIN_PANIC_REVERSAL_SHADOW,
    build_payload=_build_panic_reversal_payload,
    write_outputs=write_panic_reversal_shadow_outputs,
)
MACRO_RISK_GOVERNOR_SPEC = PluginExecutionSpec(
    default_plugin=PLUGIN_MACRO_RISK_GOVERNOR,
    build_payload=_build_macro_risk_governor_payload,
    write_outputs=write_macro_risk_governor_outputs,
)
MARKET_REGIME_CONTROL_SPEC = PluginExecutionSpec(
    default_plugin=PLUGIN_MARKET_REGIME_CONTROL,
    build_payload=_build_market_regime_control_payload,
    write_outputs=write_market_regime_control_outputs,
)


def run_crisis_response_shadow_plugin(plugin_config: Mapping[str, Any], default_mode: str) -> PluginRunResult:
    return _run_table_strategy_plugin(plugin_config, default_mode, CRISIS_RESPONSE_SHADOW_SPEC)


def run_taco_rebound_shadow_plugin(plugin_config: Mapping[str, Any], default_mode: str) -> PluginRunResult:
    return _run_table_strategy_plugin(plugin_config, default_mode, TACO_REBOUND_SHADOW_SPEC)


def run_panic_reversal_shadow_plugin(plugin_config: Mapping[str, Any], default_mode: str) -> PluginRunResult:
    return _run_table_strategy_plugin(plugin_config, default_mode, PANIC_REVERSAL_SHADOW_SPEC)


def run_macro_risk_governor_plugin(plugin_config: Mapping[str, Any], default_mode: str) -> PluginRunResult:
    return _run_table_strategy_plugin(plugin_config, default_mode, MACRO_RISK_GOVERNOR_SPEC)


def run_market_regime_control_plugin(plugin_config: Mapping[str, Any], default_mode: str) -> PluginRunResult:
    return _run_table_strategy_plugin(plugin_config, default_mode, MARKET_REGIME_CONTROL_SPEC)


PLUGIN_RUNNERS: dict[str, PluginRunner] = {
    PLUGIN_CRISIS_RESPONSE_SHADOW: run_crisis_response_shadow_plugin,
    PLUGIN_MARKET_REGIME_CONTROL: run_market_regime_control_plugin,
    PLUGIN_MACRO_RISK_GOVERNOR: run_macro_risk_governor_plugin,
    PLUGIN_PANIC_REVERSAL_SHADOW: run_panic_reversal_shadow_plugin,
    PLUGIN_TACO_REBOUND_SHADOW: run_taco_rebound_shadow_plugin,
}
PLUGIN_SPECS: dict[str, PluginExecutionSpec] = {
    PLUGIN_CRISIS_RESPONSE_SHADOW: CRISIS_RESPONSE_SHADOW_SPEC,
    PLUGIN_MARKET_REGIME_CONTROL: MARKET_REGIME_CONTROL_SPEC,
    PLUGIN_MACRO_RISK_GOVERNOR: MACRO_RISK_GOVERNOR_SPEC,
    PLUGIN_PANIC_REVERSAL_SHADOW: PANIC_REVERSAL_SHADOW_SPEC,
    PLUGIN_TACO_REBOUND_SHADOW: TACO_REBOUND_SHADOW_SPEC,
}


def _strategy_plugin_entries(
    config: Mapping[str, Any],
    *,
    selected_plugins: Sequence[str] | None = None,
    selected_strategies: Sequence[str] | None = None,
) -> tuple[dict[str, Any], ...]:
    entries = config.get("strategy_plugins", [])
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        raise ValueError("strategy_plugins config must be an array of tables")

    plugin_filter = set(_as_str_tuple(selected_plugins))
    strategy_filter = set(_as_str_tuple(selected_strategies))
    selected: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ValueError("each strategy_plugins entry must be a table")
        plugin_config = _flatten_strategy_plugin_entry(entry)
        strategy = _safe_scope_name(plugin_config.get("strategy"), field="strategy")
        plugin = _safe_scope_name(plugin_config.get("plugin"), field="plugin")
        if plugin_filter and plugin not in plugin_filter:
            continue
        if strategy_filter and strategy not in strategy_filter:
            continue
        if _as_bool(plugin_config.get("enabled"), default=True):
            _validate_plugin_strategy(plugin, strategy)
        plugin_config["strategy"] = strategy
        plugin_config["plugin"] = plugin
        selected.append(plugin_config)
    return tuple(selected)


def _notification_target_entries(
    config: Mapping[str, Any],
    *,
    selected_plugins: Sequence[str] | None = None,
    selected_notification_targets: Sequence[str] | None = None,
) -> tuple[dict[str, Any], ...]:
    entries = config.get("notification_targets", [])
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        raise ValueError("notification_targets config must be an array of tables")

    plugin_filter = set(_as_str_tuple(selected_plugins))
    target_filter = set(_as_str_tuple(selected_notification_targets))
    selected: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ValueError("each notification_targets entry must be a table")
        plugin_config = _flatten_strategy_plugin_entry(entry)
        notification_target = _safe_scope_name(plugin_config.get("notification_target"), field="notification_target")
        plugin = _safe_scope_name(plugin_config.get("plugin"), field="plugin")
        if plugin_filter and plugin not in plugin_filter:
            continue
        if target_filter and notification_target not in target_filter:
            continue
        if _as_bool(plugin_config.get("enabled"), default=True):
            _validate_plugin_notification_target(plugin, notification_target)
        plugin_config["notification_target"] = notification_target
        plugin_config["plugin"] = plugin
        selected.append(plugin_config)
    return tuple(selected)


def run_configured_plugins(
    config: Mapping[str, Any],
    *,
    selected_plugins: Sequence[str] | None = None,
    selected_strategies: Sequence[str] | None = None,
    selected_notification_targets: Sequence[str] | None = None,
) -> dict[str, Any]:
    default_mode = str(config.get("default_mode", SHADOW_MODE)).strip().lower()
    plugin_configs = _strategy_plugin_entries(
        config,
        selected_plugins=selected_plugins,
        selected_strategies=selected_strategies,
    )
    notification_target_configs = _notification_target_entries(
        config,
        selected_plugins=selected_plugins,
        selected_notification_targets=selected_notification_targets,
    )

    results: list[PluginRunResult] = []
    for plugin_config in plugin_configs:
        plugin = str(plugin_config["plugin"])
        if plugin not in PLUGIN_RUNNERS:
            raise ValueError(f"unsupported plugin: {plugin}")
        results.append(PLUGIN_RUNNERS[plugin](plugin_config, default_mode))
    notification_target_results: list[PluginRunResult] = []
    for plugin_config in notification_target_configs:
        plugin = str(plugin_config["plugin"])
        if plugin not in PLUGIN_RUNNERS:
            raise ValueError(f"unsupported plugin: {plugin}")
        notification_target_results.append(
            _run_table_notification_target_plugin(plugin_config, default_mode, PLUGIN_SPECS[plugin])
        )

    output_dir = Path(str(config.get("output_dir", DEFAULT_RUNNER_OUTPUT_DIR)).strip())
    summary = {
        "schema_version": "strategy_plugins.v1",
        "default_mode": default_mode,
        "strategy_plugins": [asdict(result) for result in results],
        "notification_targets": [asdict(result) for result in notification_target_results],
    }
    write_json(output_dir / "latest_run.json", summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run configured sidecar strategy plugins.")
    parser.add_argument("--config", required=True, help="TOML config file listing strategy plugins and notification targets")
    parser.add_argument("--plugins", default=None, help="Optional comma-separated plugin allowlist")
    parser.add_argument("--strategies", default=None, help="Optional comma-separated strategy allowlist")
    parser.add_argument("--notification-targets", default=None, help="Optional comma-separated notification target allowlist")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_plugin_config(args.config)
    summary = run_configured_plugins(
        config,
        selected_plugins=_as_str_tuple(args.plugins) or None,
        selected_strategies=_as_str_tuple(args.strategies) or None,
        selected_notification_targets=_as_str_tuple(args.notification_targets) or None,
    )
    for result in summary["strategy_plugins"]:
        print(
            f"{result['strategy']}:{result['plugin']} {result['status']} mode={result['mode']} "
            f"latest={result.get('latest_signal_path') or ''} {result.get('message') or ''}".rstrip()
        )
    for result in summary["notification_targets"]:
        print(
            f"{result['notification_target']}:{result['plugin']} {result['status']} mode={result['mode']} "
            f"latest={result.get('latest_signal_path') or ''} {result.get('message') or ''}".rstrip()
        )
    return 0


__all__ = [
    "GENERAL_MARKET_REGIME_NOTIFICATION_TARGET",
    "PLUGIN_CRISIS_RESPONSE_SHADOW",
    "PLUGIN_MARKET_REGIME_CONTROL",
    "PLUGIN_MACRO_RISK_GOVERNOR",
    "PLUGIN_PANIC_REVERSAL_SHADOW",
    "PLUGIN_TACO_REBOUND_SHADOW",
    "PLUGIN_COMPATIBLE_STRATEGIES",
    "PLUGIN_COMPATIBLE_NOTIFICATION_TARGETS",
    "PLUGIN_CONSUMPTION_POLICIES",
    "PLUGIN_CONSUMPTION_POLICY_REGISTRY",
    "PLUGIN_DEPRECATED_SUCCESSORS",
    "PLUGIN_NOTIFICATION_TARGET_POLICIES",
    "PLUGIN_NOTIFICATION_TARGET_POLICY_REGISTRY",
    "PLUGIN_RESEARCH_ONLY_REASONS",
    "PLUGIN_SCHEMA_VERSIONS",
    "STRATEGY_PLUGIN_LOG_SCHEMA_VERSION",
    "STRATEGY_PLUGIN_MESSAGE_SCHEMA_VERSION",
    "PluginConsumptionPolicy",
    "PluginNotificationTargetPolicy",
    "PluginRunResult",
    "load_plugin_config",
    "main",
    "run_configured_plugins",
    "run_crisis_response_shadow_plugin",
    "run_market_regime_control_plugin",
    "run_macro_risk_governor_plugin",
    "run_panic_reversal_shadow_plugin",
    "run_taco_rebound_shadow_plugin",
]
