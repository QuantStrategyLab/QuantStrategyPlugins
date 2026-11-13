"""Compatibility shim; implementation lives in plugins.crisis_response_shadow_plugin."""

from .plugins.crisis_response_shadow_plugin import (
    SCHEMA_VERSION,
    SHADOW_MODE,
    SHADOW_PROFILE,
    build_crisis_response_shadow_signal,
    main,
    write_crisis_response_shadow_outputs,
)

__all__ = [
    "SCHEMA_VERSION",
    "SHADOW_MODE",
    "SHADOW_PROFILE",
    "build_crisis_response_shadow_signal",
    "main",
    "write_crisis_response_shadow_outputs",
]
