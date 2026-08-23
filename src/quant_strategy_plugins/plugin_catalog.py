"""Deterministic inventory for strategy-plugin sidecars.

This is an inventory/matrix boundary, not a promotion gate.  It deliberately
does not invent evidence digests: those are populated by a concrete run.
"""

from __future__ import annotations

from typing import Any

from .plugin_lineage import PLUGIN_LINEAGE_REGISTRY
from .plugin_policies import (
    PLUGIN_COMPATIBLE_STRATEGIES,
    PLUGIN_DIRECT_POSITION_CONTROL_ALLOWED,
    PLUGIN_LIFECYCLE_POLICY_REGISTRY,
    PLUGIN_CONSUMPTION_POLICY_REGISTRY,
)

PLUGIN_CATALOG_SCHEMA_VERSION = "strategy_plugin_catalog.v1"


def build_plugin_catalog() -> dict[str, Any]:
    """Return the sidecar inventory consumed by lifecycle matrix tooling.

    ``owner_strategy`` is a tuple because a sidecar may be mounted by more
    than one strategy.  A missing run-specific digest/expiry remains ``None``
    and therefore cannot be mistaken for valid evidence.
    """
    entries: list[dict[str, Any]] = []
    for plugin_id in sorted(PLUGIN_LIFECYCLE_POLICY_REGISTRY):
        lifecycle = PLUGIN_LIFECYCLE_POLICY_REGISTRY[plugin_id]
        lineage = PLUGIN_LINEAGE_REGISTRY[plugin_id]
        policies = [
            policy
            for (policy_plugin, _), policy in PLUGIN_CONSUMPTION_POLICY_REGISTRY.items()
            if policy_plugin == plugin_id
        ]
        position_allowed = bool(
            PLUGIN_DIRECT_POSITION_CONTROL_ALLOWED
            and any(policy.position_control_allowed for policy in policies)
        )
        entries.append(
            {
                "plugin_id": plugin_id,
                "lineage": lineage["lineage"],
                "owner_strategy": list(PLUGIN_COMPATIBLE_STRATEGIES.get(plugin_id, ())),
                "input_digest": None,
                "evidence_package_id": None,
                "evidence_valid_until": None,
                "bounded_budget": None,
                "position_mutation_allowed": False,
                "broker_order_allowed": False,
                "policy_position_control_allowed": position_allowed,
                "lifecycle_stage": lifecycle.lifecycle_stage,
                "status": "DEFERRED",
                "new_mount_allowed": lifecycle.new_mount_allowed,
                "replay_only": lifecycle.replay_only,
                "successor": lifecycle.successor,
            }
        )
    return {
        "schema_version": PLUGIN_CATALOG_SCHEMA_VERSION,
        "inventory_only": True,
        "source_policy": "Metadata inventory only; do not claim evidence or live authority.",
        "entries": entries,
    }


__all__ = ["PLUGIN_CATALOG_SCHEMA_VERSION", "build_plugin_catalog"]
