"""Compatibility shim; implementation lives in plugins.panic_reversal_shadow_plugin."""

from .plugins.panic_reversal_shadow_plugin import (
    ACTION_NOTIFY_MANUAL_REVIEW,
    PANIC_REVERSAL_PROFILE,
    ROUTE_PANIC_REVERSAL,
    SCHEMA_VERSION,
    build_panic_reversal_shadow_signal,
    main,
    run_panic_reversal_event_study,
    scan_panic_reversal_signals,
    write_panic_reversal_shadow_outputs,
)

__all__ = [
    "ACTION_NOTIFY_MANUAL_REVIEW",
    "PANIC_REVERSAL_PROFILE",
    "ROUTE_PANIC_REVERSAL",
    "SCHEMA_VERSION",
    "build_panic_reversal_shadow_signal",
    "main",
    "run_panic_reversal_event_study",
    "scan_panic_reversal_signals",
    "write_panic_reversal_shadow_outputs",
]
