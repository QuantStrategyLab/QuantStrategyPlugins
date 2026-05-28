"""Open strategy plugin implementations for QuantStrategyLab runtimes."""

from .crisis_response_shadow_plugin import (
    SCHEMA_VERSION as CRISIS_RESPONSE_SHADOW_SCHEMA_VERSION,
    SHADOW_PROFILE as CRISIS_RESPONSE_SHADOW_PROFILE,
    build_crisis_response_shadow_signal,
    write_crisis_response_shadow_outputs,
)
from .macro_risk_governor_plugin import (
    MACRO_RISK_GOVERNOR_PROFILE,
    SCHEMA_VERSION as MACRO_RISK_GOVERNOR_SCHEMA_VERSION,
    build_macro_risk_governor_signal,
    write_macro_risk_governor_outputs,
)
from .market_regime_control_plugin import (
    MARKET_REGIME_CONTROL_PROFILE,
    SCHEMA_VERSION as MARKET_REGIME_CONTROL_SCHEMA_VERSION,
    build_market_regime_control_signal,
    write_market_regime_control_outputs,
)
from .strategy_plugin_runner import run_configured_plugins
from .taco_rebound_shadow_plugin import (
    SCHEMA_VERSION as TACO_REBOUND_SHADOW_SCHEMA_VERSION,
    TACO_REBOUND_PROFILE,
    build_taco_rebound_shadow_signal,
    write_taco_rebound_shadow_outputs,
)

__all__ = [
    "CRISIS_RESPONSE_SHADOW_PROFILE",
    "CRISIS_RESPONSE_SHADOW_SCHEMA_VERSION",
    "MACRO_RISK_GOVERNOR_PROFILE",
    "MACRO_RISK_GOVERNOR_SCHEMA_VERSION",
    "MARKET_REGIME_CONTROL_PROFILE",
    "MARKET_REGIME_CONTROL_SCHEMA_VERSION",
    "TACO_REBOUND_PROFILE",
    "TACO_REBOUND_SHADOW_SCHEMA_VERSION",
    "build_crisis_response_shadow_signal",
    "build_macro_risk_governor_signal",
    "build_market_regime_control_signal",
    "build_taco_rebound_shadow_signal",
    "run_configured_plugins",
    "write_crisis_response_shadow_outputs",
    "write_macro_risk_governor_outputs",
    "write_market_regime_control_outputs",
    "write_taco_rebound_shadow_outputs",
]
