"""Compatibility shim; implementation lives in plugins.benchmark_drawdown_guard."""

from .plugins.benchmark_drawdown_guard import (
    ACTION_BLOCKED,
    ACTION_DEFEND,
    ACTION_DELEVER,
    ACTION_NO_ACTION,
    PROFILE,
    ROUTE_BLOCKED,
    ROUTE_NO_ACTION,
    ROUTE_RISK_OFF,
    ROUTE_RISK_REDUCED,
    SCHEMA_VERSION,
    build_benchmark_drawdown_guard_signal,
)

__all__ = [
    "ACTION_BLOCKED",
    "ACTION_DEFEND",
    "ACTION_DELEVER",
    "ACTION_NO_ACTION",
    "PROFILE",
    "ROUTE_BLOCKED",
    "ROUTE_NO_ACTION",
    "ROUTE_RISK_OFF",
    "ROUTE_RISK_REDUCED",
    "SCHEMA_VERSION",
    "build_benchmark_drawdown_guard_signal",
]
