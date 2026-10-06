"""Offline composition of frozen, already-mapped research constraints.

DESIGN_ONLY_NOT_RUNTIME: this comparator is not a strategy adapter, release
store, risk gate, source reader, or permission issuer. Source-to-cap mappings
are supplied and hash-bound by a synthetic research trial, not inferred here.
No caller, including a caller supplying permissive caps, receives authority.
"""
from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .plugin_signal_envelope_v2 import (
    SignalEnvelopeValidationError,
    canonical_json_bytes,
    payload_sha256,
    validate_signal_envelope,
)

POLICY_ID = "market_regime_composition.same_dimension_min.v1"
POLICY_VERSION = "v1"
VALIDITY_POLICY_VERSION = "research.explicit_interval_and_age.v1"
DIMENSIONS = ("leverage_leg_nominal", "total_risk_asset_nominal")
_MEASUREMENT = "baseline_nominal_ratio.v1"
_POLICY_FIELDS = {
    "policy_id", "policy_version", "strategy", "baseline", "scope", "denominators",
    "requested_as_of", "decision_at", "validity_policy_version", "inputs",
}
_BINDING_FIELDS = {
    "observation_id", "required", "applicable", "factor_id", "algorithm_version", "window", "sampling",
    "max_delay_seconds", "source_sha256", "constraints_sha256",
}
_CONSTRAINT_FIELDS = {
    "constraint_id", "observation_id", "policy_version", "scope", "dimension", "measurement",
    "unit", "denominator_id", "cap", "kind", "reason_codes", "reason_group_id",
}


class ResearchCompositionError(ValueError):
    """A malformed/unknown frozen research contract was rejected, without output."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ResearchCompositionError(message)


def _fields(value: Any, fields: set[str], location: str) -> None:
    _require(isinstance(value, dict) and set(value) == fields, f"invalid {location} fields")


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def _hash(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _time(value: Any) -> datetime:
    _require(_text(value), "timestamp must be a timezone-aware ISO string")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        _require(result.tzinfo is not None and result.utcoffset() is not None, "timestamp needs a timezone")
        return result.astimezone(timezone.utc)
    except ValueError as exc:
        raise ResearchCompositionError("invalid timestamp") from exc


def _scope(scope: Any) -> None:
    _fields(scope, {"market", "symbols", "calendar", "time_zone"}, "scope")
    _require(all(_text(scope[k]) for k in ("market", "calendar", "time_zone")), "invalid scope")
    symbols = scope["symbols"]
    _require(isinstance(symbols, list) and bool(symbols) and all(_text(s) for s in symbols), "invalid symbols")
    _require(len(symbols) == len(set(symbols)), "duplicate symbols")
    try:
        ZoneInfo(scope["time_zone"])
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ResearchCompositionError("unknown scope timezone") from exc


def _unique(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Detached canonical exact set; order/receipt counts have no semantics."""
    import json

    _require(isinstance(records, (list, tuple)), "records must be a list or tuple")
    _require(all(isinstance(record, Mapping) for record in records), "record must be an object")
    try:
        return [json.loads(raw) for raw in sorted({canonical_json_bytes(record) for record in records})]
    except SignalEnvelopeValidationError as exc:
        raise ResearchCompositionError("records must be finite JSON") from exc


def constraints_sha256(constraints: Sequence[Mapping[str, Any]]) -> str:
    """Hash an exact, canonical constraint set when freezing a research trial."""
    return payload_sha256(_unique(constraints))


def _validate_policy(policy: dict[str, Any], expected_sha256: str) -> None:
    _fields(policy, _POLICY_FIELDS, "policy")
    _require(_hash(expected_sha256) and payload_sha256(policy) == expected_sha256, "policy hash mismatch")
    _require(policy["policy_id"] == POLICY_ID and policy["policy_version"] == POLICY_VERSION,
             "unknown composition policy")
    _require(policy["validity_policy_version"] == VALIDITY_POLICY_VERSION, "unknown validity policy")
    _fields(policy["strategy"], {"candidate_id", "revision", "config_sha256"}, "strategy")
    strategy = policy["strategy"]
    _require(_text(strategy["candidate_id"]) and isinstance(strategy["revision"], str)
             and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", strategy["revision"]) is not None
             and _hash(strategy["config_sha256"]), "invalid strategy identity")
    _fields(policy["baseline"], {"baseline_id", "baseline_sha256"}, "baseline")
    _require(_text(policy["baseline"]["baseline_id"]) and _hash(policy["baseline"]["baseline_sha256"]),
             "invalid frozen baseline identity")
    _scope(policy["scope"])
    _fields(policy["denominators"], set(DIMENSIONS), "denominators")
    _require(all(_text(x) for x in policy["denominators"].values())
             and len(set(policy["denominators"].values())) == 2, "dimensions need distinct denominator identities")
    _require(_time(policy["requested_as_of"]) <= _time(policy["decision_at"]), "request cutoff after decision")
    _require(isinstance(policy["inputs"], list) and bool(policy["inputs"]), "input bindings are required")
    seen = set()
    for binding in policy["inputs"]:
        _fields(binding, _BINDING_FIELDS, "input binding")
        _require(all(_text(binding[k]) for k in (
            "observation_id", "factor_id", "algorithm_version", "window", "sampling")), "invalid input identity")
        _require(binding["observation_id"] not in seen, "duplicate policy observation identity")
        seen.add(binding["observation_id"])
        _require(type(binding["required"]) is bool and type(binding["applicable"]) is bool, "invalid applicability")
        _require(type(binding["max_delay_seconds"]) is int and binding["max_delay_seconds"] >= 0,
                 "invalid maximum delay")
        _require(_hash(binding["source_sha256"]) and _hash(binding["constraints_sha256"]), "invalid input hashes")


def _validate_constraint(constraint: dict[str, Any], policy: dict[str, Any]) -> None:
    _fields(constraint, _CONSTRAINT_FIELDS, "constraint")
    _require(all(_text(constraint[k]) for k in ("constraint_id", "observation_id", "reason_group_id")),
             "invalid constraint identity")
    dimension = constraint["dimension"]
    _require(isinstance(dimension, str) and dimension in DIMENSIONS, "unsupported dimension")
    _require(constraint["policy_version"] == POLICY_VERSION, "constraint policy mismatch")
    _require(constraint["scope"] == policy["scope"], "constraint scope mismatch")
    _require(constraint["unit"] == "ratio" and constraint["measurement"] == _MEASUREMENT
             and constraint["denominator_id"] == policy["denominators"][dimension], "incomparable constraint")
    cap = constraint["cap"]
    _require(type(cap) in (int, float) and 0 <= cap <= 1 and math.isfinite(cap), "invalid cap")
    _require(constraint["kind"] in ("hard", "soft", "watch_only", "opportunity"), "unsupported constraint kind")
    reasons = constraint["reason_codes"]
    _require(isinstance(reasons, list) and bool(reasons) and all(_text(x) for x in reasons), "invalid reason codes")


def _constraint_identity(constraint: Mapping[str, Any]) -> bytes:
    return canonical_json_bytes([constraint.get(k) for k in (
        "constraint_id", "scope", "dimension", "observation_id", "policy_version"
    )])


def _source_envelope(source: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    """Provided sources must be valid even when their scope is inapplicable."""
    _fields(source, {"observation_id", "envelope", "received_at"}, "source")
    envelope = validate_signal_envelope(source["envelope"])
    _require(re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", envelope["producer"]["revision"]) is not None,
             "producer revision must be a full Git SHA-1 or SHA-256")
    _require(payload_sha256(source) == binding["source_sha256"], "source hash mismatch")
    _time(source["received_at"])
    payload = envelope["payload"]
    for field in ("observation_id", "factor_id", "algorithm_version", "window", "sampling"):
        _require(payload.get(field) == binding[field], f"source {field} mismatch")
    return envelope


def _validate_source(source: dict[str, Any], binding: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    payload = _source_envelope(source, binding)["payload"]
    _require(payload.get("scope") == policy["scope"], "source scope/calendar mismatch")
    _require(payload.get("window_complete") is True, "incomplete observation window")
    try:
        observed, published, effective, until = (
            _time(payload[field]) for field in ("observed_as_of", "published_at", "effective_from", "valid_until")
        )
    except KeyError as exc:
        raise ResearchCompositionError("missing input time") from exc
    received = _time(source["received_at"])
    decision, requested = _time(policy["decision_at"]), _time(policy["requested_as_of"])
    reasons = []
    if not observed <= published <= received <= decision or observed > requested:
        reasons.append("NOT_VISIBLE_AT_CUTOFF")
    if not effective <= decision:
        reasons.append("NOT_EFFECTIVE")
    if not effective < until or decision >= until:
        reasons.append("EXPIRED")
    if (decision - observed).total_seconds() > binding["max_delay_seconds"]:
        reasons.append("STALE_OBSERVATION")
    return reasons


def compose_research_constraints(
    policy: Mapping[str, Any],
    sources: Sequence[Mapping[str, Any]],
    constraints: Sequence[Mapping[str, Any]],
    *,
    expected_policy_sha256: str,
    ai_narrative: Any = None,
) -> dict[str, Any]:
    """Return a non-executable min-cap comparator, or reject a malformed policy.

    Policy content includes exact source/constraint bindings for this trial.
    Hash checks are integrity checks, not signatures or runtime-install proofs.
    Invalid required observations block the proposal and retain other validated
    constraints. Missing dimensions under BLOCKED are null, never a free budget.
    ``ai_narrative`` is intentionally not inspected, returned, or digest-bound.
    """
    policy = _unique([policy])[0]
    _validate_policy(policy, expected_policy_sha256)
    sources, constraints = _unique(sources), _unique(constraints)
    bindings = {item["observation_id"]: item for item in policy["inputs"]}
    for record in sources + constraints:
        _require(_text(record.get("observation_id")), "missing observation identity")
    unknown = sorted({r["observation_id"] for r in sources + constraints} - bindings.keys())
    reports, valid = [], set()
    blocked = bool(unknown)
    for obs, binding in sorted(bindings.items()):
        observed = [s for s in sources if s["observation_id"] == obs]
        mapped = [c for c in constraints if c["observation_id"] == obs]
        reasons = []
        if not binding["applicable"]:
            _require(len(observed) <= 1, "conflicting inapplicable source identity")
            if observed:
                try:
                    _source_envelope(observed[0], binding)
                except SignalEnvelopeValidationError as exc:
                    raise ResearchCompositionError("invalid inapplicable envelope: " + str(exc)) from exc
            if mapped:
                identities = [_constraint_identity(c) for c in mapped]
                _require(len(identities) == len(set(identities)), "conflicting inapplicable constraint identity")
                _require(constraints_sha256(mapped) == binding["constraints_sha256"],
                         "inapplicable constraints hash mismatch")
            status = "NOT_APPLICABLE"
        else:
            if len(observed) != 1:
                reasons.append("MISSING_INPUT" if not observed else "CONFLICTING_SOURCE_IDENTITY")
            identities = [_constraint_identity(c) for c in mapped]
            if len(identities) != len(set(identities)):
                reasons.append("CONFLICTING_CONSTRAINT_IDENTITY")
            try:
                if len(observed) == 1:
                    reasons.extend(_validate_source(observed[0], binding, policy))
                for item in mapped:
                    _validate_constraint(item, policy)
                _require(constraints_sha256(mapped) == binding["constraints_sha256"], "constraints hash mismatch")
            except (ResearchCompositionError, SignalEnvelopeValidationError) as exc:
                reasons.append("INVALID_INPUT:" + str(exc))
            status = "UNAVAILABLE" if reasons else "VALID"
            if status == "VALID":
                valid.add(obs)
            elif binding["required"] or any(r.startswith("CONFLICTING_") for r in reasons):
                blocked = True
        reports.append({"observation_id": obs, "status": status, "reason_codes": sorted(set(reasons))})
    reports.extend({"observation_id": obs, "status": "UNAVAILABLE", "reason_codes": ["UNBOUND_INPUT"]}
                   for obs in unknown)
    caps = {}
    for dimension in DIMENSIONS:
        values = [c["cap"] for c in constraints if c["observation_id"] in valid
                  and c["kind"] == "hard" and c["dimension"] == dimension]
        caps[dimension] = min(values) if values else (None if blocked else 1.0)
    selections = []
    for constraint in constraints:
        obs = constraint["observation_id"]
        if obs in bindings and not bindings[obs]["applicable"]:
            selection = "NOT_APPLICABLE"
        elif obs not in valid:
            selection = "INPUT_UNAVAILABLE"
        elif constraint["kind"] == "hard":
            selection = "BINDING" if constraint["cap"] == caps[constraint["dimension"]] else "NON_BINDING"
        else:
            selection = {"opportunity": "OPPORTUNITY_VETOED", "watch_only": "WATCH_ONLY", "soft": "SOFT"}[
                constraint["kind"]
            ]
        selections.append({"constraint": constraint, "selection": selection})
    result = {
        "mode": "research_only", "policy": policy, "policy_sha256": expected_policy_sha256,
        "status": "BLOCKED" if blocked else "READY_RESEARCH", "data_state": "UNKNOWN" if blocked else "KNOWN",
        "caps": caps, "inputs": sorted(reports, key=lambda item: item["observation_id"]),
        "sources": sources, "constraints": selections,
        "executable": False, "risk_increase_allowed": False, "release_authority": False,
    }
    result["decision_digest"] = payload_sha256(result)
    return result
