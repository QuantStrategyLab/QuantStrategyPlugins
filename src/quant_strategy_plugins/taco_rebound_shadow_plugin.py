"""Compatibility shim; implementation lives in plugins.taco_rebound_shadow_plugin."""

from .plugins.taco_rebound_shadow_plugin import (
    ACTION_NOTIFY_MANUAL_REVIEW,
    ROUTE_TACO_REBOUND,
    SCHEMA_VERSION,
    TACO_REBOUND_PROFILE,
    build_taco_rebound_shadow_signal,
    main,
    write_taco_rebound_shadow_outputs,
)

__all__ = [
    "ACTION_NOTIFY_MANUAL_REVIEW",
    "ROUTE_TACO_REBOUND",
    "SCHEMA_VERSION",
    "TACO_REBOUND_PROFILE",
    "build_taco_rebound_shadow_signal",
    "main",
    "write_taco_rebound_shadow_outputs",
]
