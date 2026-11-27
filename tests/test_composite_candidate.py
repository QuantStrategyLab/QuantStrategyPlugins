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

    missing_flags_catalog = validate_composite_candidate(
        _spec(),
        catalog={"entries": [{"plugin_id": "market_regime_control", "status": "DEFERRED"}]},
    )
    assert missing_flags_catalog.valid is False
    assert "catalog_authority_forbidden" in missing_flags_catalog.errors

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


def test_validate_composite_candidate_cli(tmp_path) -> None:
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "validate_composite_candidate.py"
    env = {**os.environ, "PYTHONPATH": str(repo_root / "src")}

    valid_path = tmp_path / "valid.json"
    valid_path.write_text(json.dumps(_spec().to_dict()), encoding="utf-8")
    ok = subprocess.run([sys.executable, str(script), "--spec", str(valid_path)], capture_output=True, text=True, check=False, env=env)
    assert ok.returncode == 0
    assert json.loads(ok.stdout)["valid"] is True

    malformed = tmp_path / "bad.json"
    malformed.write_text("{not-json", encoding="utf-8")
    bad_json = subprocess.run([sys.executable, str(script), "--spec", str(malformed)], capture_output=True, text=True, check=False, env=env)
    assert bad_json.returncode == 1
    assert json.loads(bad_json.stdout)["valid"] is False

    missing_fields = tmp_path / "incomplete.json"
    missing_fields.write_text('{"candidate_id": "only"}', encoding="utf-8")
    incomplete = subprocess.run([sys.executable, str(script), "--spec", str(missing_fields)], capture_output=True, text=True, check=False, env=env)
    assert incomplete.returncode == 1
    assert "Missing required fields" in json.loads(incomplete.stdout)["errors"][0]

    missing_file = subprocess.run([sys.executable, str(script), "--spec", str(tmp_path / "absent.json")], capture_output=True, text=True, check=False, env=env)
    assert missing_file.returncode == 1
    assert json.loads(missing_file.stdout)["valid"] is False

    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text(json.dumps({**_spec().to_dict(), "broker_order_allowed": True}), encoding="utf-8")
    bad = subprocess.run([sys.executable, str(script), "--spec", str(invalid_path)], capture_output=True, text=True, check=False, env=env)
    assert bad.returncode == 1
    assert "broker_order_forbidden" in json.loads(bad.stdout)["errors"]

    unhashable_path = tmp_path / "unhashable.json"
    unhashable_path.write_text(json.dumps({**_spec().to_dict(), "plugin_id": ["unhashable"]}), encoding="utf-8")
    unhashable = subprocess.run([sys.executable, str(script), "--spec", str(unhashable_path)], capture_output=True, text=True, check=False, env=env)
    assert unhashable.returncode == 1
    assert json.loads(unhashable.stdout)["valid"] is False

    mut_path = tmp_path / "mutation.json"
    mut_path.write_text(json.dumps({**_spec().to_dict(), "position_mutation_allowed": True}), encoding="utf-8")
    mut = subprocess.run([sys.executable, str(script), "--spec", str(mut_path)], capture_output=True, text=True, check=False, env=env)
    assert mut.returncode == 1
    assert "position_mutation_forbidden" in json.loads(mut.stdout)["errors"]
