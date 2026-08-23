"""Small, deterministic provenance contract for strategy-plugin sidecars.

The registry deliberately describes plugins as observers.  It does not grant
position authority; that remains a strategy/runtime concern.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any, Mapping

import pandas as pd

PLUGIN_LINEAGE_SCHEMA_VERSION = "strategy_plugin_lineage.v1"

# Stable names are intentionally independent of implementation module names.
PLUGIN_LINEAGE_REGISTRY: dict[str, dict[str, str]] = {
    "crisis_response_shadow": {"lineage": "market_regime/crisis", "role": "shadow"},
    "macro_risk_governor": {"lineage": "market_regime/macro", "role": "shadow"},
    "market_regime_control": {"lineage": "market_regime/unified", "role": "shadow"},
    "panic_reversal_shadow": {"lineage": "event_context/panic_reversal", "role": "notification"},
    "taco_rebound_shadow": {"lineage": "event_context/taco_rebound", "role": "notification"},
}


def _json_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def input_digest(frame: pd.DataFrame, config: Mapping[str, Any]) -> str:
    """Hash the exact in-memory input and relevant configuration, not its path."""
    values = pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes()
    payload = {
        "columns": [str(column) for column in frame.columns],
        "dtypes": [str(dtype) for dtype in frame.dtypes],
        "rows_sha256": hashlib.sha256(values).hexdigest(),
        "config": {str(k): v for k, v in config.items() if k not in {"prices", "output_dir"}},
    }
    return _json_digest(payload)


def build_plugin_lineage(
    plugin: str,
    *,
    frame: pd.DataFrame,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    registration = PLUGIN_LINEAGE_REGISTRY.get(plugin, {"lineage": f"unregistered/{plugin}", "role": "shadow"})
    valid_until = str(config.get("evidence_valid_until") or "").strip() or None
    if valid_until:
        try:
            date.fromisoformat(valid_until)
        except ValueError as exc:
            raise ValueError(f"evidence_valid_until must be ISO date: {valid_until!r}") from exc
    raw_budget = config.get("bounded_budget")
    budget = raw_budget if isinstance(raw_budget, Mapping) else {}
    return {
        "schema_version": PLUGIN_LINEAGE_SCHEMA_VERSION,
        "plugin": plugin,
        "lineage": registration["lineage"],
        "role": registration["role"],
        "input_digest": input_digest(frame, config),
        "evidence_valid_until": valid_until,
        "evidence_expiry_status": "declared" if valid_until else "not_declared",
        "bounded_budget": dict(budget),
        "bounded_budget_status": "declared" if budget else "not_declared",
        "position_mutation_allowed": False,
        "broker_order_allowed": False,
    }
