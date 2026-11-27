"""CLI validator for V2 composite candidate JSON specifications."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from quant_strategy_plugins.composite_candidate import (
    CompositeCandidateSpec,
    validate_composite_candidate,
)


def _load_spec(path: Path) -> CompositeCandidateSpec:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Composite candidate spec JSON must be an object")
    required = ("candidate_id", "strategy_profile", "strategy_revision", "plugin_id", "plugin_revision", "asset_class", "input_manifest_sha256", "sizing_policy_id")
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")
    return CompositeCandidateSpec(
        candidate_id=payload["candidate_id"],
        strategy_profile=payload["strategy_profile"],
        strategy_revision=payload["strategy_revision"],
        plugin_id=payload["plugin_id"],
        plugin_revision=payload["plugin_revision"],
        asset_class=payload["asset_class"],
        input_manifest_sha256=payload["input_manifest_sha256"],
        sizing_policy_id=payload["sizing_policy_id"],
        lifecycle_stage=payload.get("lifecycle_stage", "research_active"),
        evidence_digest=payload.get("evidence_digest"),
        position_mutation_allowed=payload.get("position_mutation_allowed", False),
        broker_order_allowed=payload.get("broker_order_allowed", False),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a V2 composite candidate JSON specification.")
    parser.add_argument("--spec", required=True, type=Path, help="Path to the candidate JSON specification.")
    args = parser.parse_args(argv)

    try:
        spec = _load_spec(args.spec)
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}, indent=2, sort_keys=True))
        return 1
    result = validate_composite_candidate(spec)
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
