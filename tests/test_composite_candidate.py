"""Tests for V2 composite candidate contract validation."""

from __future__ import annotations

from quant_strategy_plugins import (
    COMPOSITE_CANDIDATE_SCHEMA_VERSION,
    SUPPORTED_ASSET_CLASSES,
    VALID_LIFECYCLE_STAGES,
    CompositeCandidateSpec,
    validate_composite_candidate,
)

_SHA = "b" * 64
_EVIDENCE = "c" * 64


def _spec(**overrides: object) -> CompositeCandidateSpec:
    base: dict[str, object] = {
        "candidate_id": "cand-breadth-gold-v2",
        "strategy_profile": "breadth_gold_1x",
        "strategy_revision": "rev-001",
        "plugin_id": "market_regime_control",
        "plugin_revision": "v1.0.0",
        "asset_class": "gold",
        "input_manifest_sha256": _SHA,
        "sizing_policy_id": "policy_v0_1x",
        "lifecycle_stage": "research_active",
    }
    base.update(overrides)
    return CompositeCandidateSpec(**base)  # type: ignore[arg-type]


def test_validate_composite_candidate_accepts_research_and_evidenced_shadow() -> None:
    research = validate_composite_candidate(_spec())
    assert research.valid is True
    assert research.errors == ()

    shadow = validate_composite_candidate(
        _spec(
            asset_class="futures",
            lifecycle_stage="shadow_active",
            evidence_digest=_EVIDENCE,
        )
    )
    assert shadow.valid is True
    assert shadow.errors == ()
    assert shadow.to_dict()["schema_version"] == COMPOSITE_CANDIDATE_SCHEMA_VERSION
    assert "futures" in SUPPORTED_ASSET_CLASSES
    assert "live_enabled" not in VALID_LIFECYCLE_STAGES


def test_validate_composite_candidate_rejects_authority_and_contract_violations() -> None:
    bad = validate_composite_candidate(
        _spec(
            candidate_id="  ",
            plugin_id="unregistered_plugin",
            asset_class="exotic_margin",
            input_manifest_sha256=_SHA + "\n",
            lifecycle_stage="live_enabled",
            position_mutation_allowed=True,
            broker_order_allowed=None,
        )
    )
    assert bad.valid is False
    assert set(bad.errors) >= {
        "missing_candidate_id",
        "unknown_plugin_id",
        "unsupported_asset_class",
        "invalid_input_manifest_sha256",
        "invalid_lifecycle_stage",
        "position_mutation_forbidden",
        "broker_order_forbidden",
    }
    assert bad.to_dict()["valid"] is False

    live_catalog = validate_composite_candidate(
        _spec(),
        catalog={"entries": [{"plugin_id": "market_regime_control", "status": "LIVE_ENABLED", "broker_order_allowed": True}]},
    )
    assert live_catalog.valid is False
    assert "catalog_authority_forbidden" in live_catalog.errors

    bad_evidence_nl = validate_composite_candidate(
        _spec(lifecycle_stage="shadow_active", evidence_digest=_EVIDENCE + "\n")
    )
    assert bad_evidence_nl.valid is False
    assert "missing_evidence_digest" in bad_evidence_nl.errors


def test_validate_composite_candidate_requires_evidence_beyond_research_active() -> None:
    missing_evidence = validate_composite_candidate(_spec(lifecycle_stage="shadow_active", evidence_digest=None))
    assert missing_evidence.valid is False
    assert "missing_evidence_digest" in missing_evidence.errors

    bad_optional_evidence = validate_composite_candidate(
        _spec(lifecycle_stage="research_active", evidence_digest="bad-digest")
    )
    assert bad_optional_evidence.valid is False
    assert "invalid_evidence_digest" in bad_optional_evidence.errors
