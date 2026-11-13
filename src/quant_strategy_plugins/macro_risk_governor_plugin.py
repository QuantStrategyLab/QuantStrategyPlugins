"""Compatibility shim; implementation lives in plugins.macro_risk_governor_plugin."""

from .plugins.macro_risk_governor_plugin import (
    MACRO_RISK_GOVERNOR_PROFILE,
    ROUTE_CRISIS,
    ROUTE_DELEVER,
    ROUTE_NO_ACTION,
    ROUTE_WATCH,
    SCHEMA_VERSION,
    SHADOW_MODE,
    build_macro_risk_governor_signal,
    main,
    write_macro_risk_governor_outputs,
)

__all__ = [
    "MACRO_RISK_GOVERNOR_PROFILE",
    "ROUTE_CRISIS",
    "ROUTE_DELEVER",
    "ROUTE_NO_ACTION",
    "ROUTE_WATCH",
    "SCHEMA_VERSION",
    "SHADOW_MODE",
    "build_macro_risk_governor_signal",
    "main",
    "write_macro_risk_governor_outputs",
]
