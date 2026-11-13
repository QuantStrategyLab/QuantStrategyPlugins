"""Compatibility shim; implementation lives in plugins.market_regime_control_plugin."""

from .plugins.market_regime_control_plugin import (
    MARKET_REGIME_CONTROL_PROFILE,
    SCHEMA_VERSION,
    build_market_regime_control_signal,
    write_market_regime_control_outputs,
)

__all__ = [
    "MARKET_REGIME_CONTROL_PROFILE",
    "SCHEMA_VERSION",
    "build_market_regime_control_signal",
    "write_market_regime_control_outputs",
]
