"""Open strategy plugin implementations for QuantStrategyLab runtimes."""

from .crisis_response_shadow_plugin import (
    SCHEMA_VERSION as CRISIS_RESPONSE_SHADOW_SCHEMA_VERSION,
    SHADOW_PROFILE as CRISIS_RESPONSE_SHADOW_PROFILE,
    build_crisis_response_shadow_signal,
    write_crisis_response_shadow_outputs,
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
    "TACO_REBOUND_PROFILE",
    "TACO_REBOUND_SHADOW_SCHEMA_VERSION",
    "build_crisis_response_shadow_signal",
    "build_taco_rebound_shadow_signal",
    "run_configured_plugins",
    "write_crisis_response_shadow_outputs",
    "write_taco_rebound_shadow_outputs",
]
