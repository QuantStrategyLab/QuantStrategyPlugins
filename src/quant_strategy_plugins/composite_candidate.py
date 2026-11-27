"""V2 composite candidate contract validation for strategy plugins.

Enforces research-only composition invariants before any strategy-plugin pair
may enter shadow, paper, or live-candidate evaluation:
- binds explicit strategy revision, plugin revision, 64-hex dataset manifest
  SHA-256, and sizing policy ID;
- fails closed unless ``position_mutation_allowed`` and ``broker_order_allowed``
  are explicitly ``False`` (in both the spec and catalog entry);
- requires a valid 64-hex evidence digest for any stage beyond
  ``research_active`` and never grants ``live_enabled`` authority.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from .plugin_catalog import build_plugin_catalog

COMPOSITE_CANDIDATE_SCHEMA_VERSION = "strategy_plugin_composite_candidate.v2"
SUPPORTED_ASSET_CLASSES = (
    "equity",
    "etf",
    "gold",
    "treasury",
    "non_us_equity",
    "commodity",
    "fx",
    "futures",
    "crypto",
)
VALID_LIFECYCLE_STAGES = (
    "research_active",
    "shadow_active",
    "paper_active",
    "live_candidate",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class CompositeCandidateSpec:
    candidate_id: str
    strategy_profile: str
    strategy_revision: str
    plugin_id: str
    plugin_revision: str
    asset_class: str
    input_manifest_sha256: str
    sizing_policy_id: str
    lifecycle_stage: str = "research_active"
    evidence_digest: str | None = None
    position_mutation_allowed: bool = False
    broker_order_allowed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": COMPOSITE_CANDIDATE_SCHEMA_VERSION,
            "candidate_id": self.candidate_id,
            "strategy_profile": self.strategy_profile,
            "strategy_revision": self.strategy_revision,
            "plugin_id": self.plugin_id,
            "plugin_revision": self.plugin_revision,
            "asset_class": self.asset_class,
            "input_manifest_sha256": self.input_manifest_sha256,
            "sizing_policy_id": self.sizing_policy_id,
            "lifecycle_stage": self.lifecycle_stage,
            "evidence_digest": self.evidence_digest,
            "position_mutation_allowed": self.position_mutation_allowed,
            "broker_order_allowed": self.broker_order_allowed,
        }


@dataclass(frozen=True)
class CompositeCandidateValidation:
    valid: bool
    errors: tuple[str, ...]
    spec: CompositeCandidateSpec

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": COMPOSITE_CANDIDATE_SCHEMA_VERSION,
            "valid": self.valid,
            "errors": list(self.errors),
            "spec": self.spec.to_dict(),
        }


def validate_composite_candidate(
    spec: CompositeCandidateSpec,
    *,
    catalog: Mapping[str, Any] | None = None,
) -> CompositeCandidateValidation:
    """Validate a V2 composite candidate binding fail-closed against the plugin catalog."""
    errors: list[str] = []

    for field_name, value in (
        ("candidate_id", spec.candidate_id),
        ("strategy_profile", spec.strategy_profile),
        ("strategy_revision", spec.strategy_revision),
        ("plugin_id", spec.plugin_id),
        ("plugin_revision", spec.plugin_revision),
        ("sizing_policy_id", spec.sizing_policy_id),
    ):
        if not isinstance(value, str) or not value.strip():
            errors.append(f"missing_{field_name}")

    catalog_data = build_plugin_catalog() if catalog is None else catalog
    raw_entries = catalog_data.get("entries") if isinstance(catalog_data, Mapping) else None
    if not isinstance(raw_entries, list):
        errors.append("invalid_plugin_catalog")
        known_plugins: dict[str, Mapping[str, Any]] = {}
    else:
        known_plugins = {}
        for entry in raw_entries:
            if not isinstance(entry, Mapping) or not isinstance(entry.get("plugin_id"), str):
                errors.append("invalid_plugin_catalog")
                continue
            known_plugins[entry["plugin_id"]] = entry

    catalog_entry = known_plugins.get(spec.plugin_id)
    if catalog_entry is None:
        errors.append("unknown_plugin_id")
    elif (
        bool(catalog_entry.get("position_mutation_allowed"))
        or bool(catalog_entry.get("broker_order_allowed"))
        or str(catalog_entry.get("status", "")).upper() == "LIVE_ENABLED"
    ):
        errors.append("catalog_authority_forbidden")

    if spec.asset_class not in SUPPORTED_ASSET_CLASSES:
        errors.append("unsupported_asset_class")

    if not isinstance(spec.input_manifest_sha256, str) or not _SHA256_RE.fullmatch(spec.input_manifest_sha256):
        errors.append("invalid_input_manifest_sha256")

    if spec.lifecycle_stage not in VALID_LIFECYCLE_STAGES:
        errors.append("invalid_lifecycle_stage")
    elif spec.lifecycle_stage != "research_active":
        if not isinstance(spec.evidence_digest, str) or not _SHA256_RE.fullmatch(spec.evidence_digest):
            errors.append("missing_evidence_digest")
    elif spec.evidence_digest is not None and (
        not isinstance(spec.evidence_digest, str) or not _SHA256_RE.fullmatch(spec.evidence_digest)
    ):
        errors.append("invalid_evidence_digest")

    if not isinstance(spec.position_mutation_allowed, bool) or spec.position_mutation_allowed is not False:
        errors.append("position_mutation_forbidden")
    if not isinstance(spec.broker_order_allowed, bool) or spec.broker_order_allowed is not False:
        errors.append("broker_order_forbidden")

    return CompositeCandidateValidation(
        valid=len(errors) == 0,
        errors=tuple(errors),
        spec=spec,
    )


__all__ = [
    "COMPOSITE_CANDIDATE_SCHEMA_VERSION",
    "CompositeCandidateSpec",
    "CompositeCandidateValidation",
    "SUPPORTED_ASSET_CLASSES",
    "VALID_LIFECYCLE_STAGES",
    "validate_composite_candidate",
]
