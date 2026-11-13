"""Compatibility shim; implementation lives in plugins.taco_panic_rebound_backtest."""

from .plugins.taco_panic_rebound_backtest import (
    BASKET_PRESETS,
    DEFAULT_PRESET,
    PRESIDENTIAL_PERIODS,
    build_period_summary,
    collect_required_symbols,
    normalize_basket,
    run_backtest,
    summarize_returns,
    main,
)

__all__ = [
    "BASKET_PRESETS",
    "DEFAULT_PRESET",
    "PRESIDENTIAL_PERIODS",
    "build_period_summary",
    "collect_required_symbols",
    "normalize_basket",
    "run_backtest",
    "summarize_returns",
    "main",
]
