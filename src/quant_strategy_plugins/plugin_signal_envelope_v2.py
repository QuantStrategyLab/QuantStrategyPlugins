"""Pure-local validation for immutable deterministic plugin signal envelopes.

This module defines a design-only artifact contract.  It intentionally has no
runtime, broker, cloud-storage, legacy-resolver, or strategy integration.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any


SCHEMA_VERSION = "qsl.strategy-plugin-signal.v2"
SIGNAL_KIND = "deterministic_signal"

_ENVELOPE_FIELDS = frozenset(
    {"schema_version", "plugin_id", "kind", "producer", "input", "payload", "payload_sha256"}
)
_PRODUCER_FIELDS = frozenset({"repo", "revision", "entrypoint", "code_sha256", "config_sha256"})
_INPUT_FIELDS = frozenset({"p1_manifest_sha256", "input_root_sha256", "date_cutoff"})
_PLUGIN_ID_PATTERN = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_REPOSITORY_PATTERN = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_REVISION_PATTERN = re.compile(r"[0-9a-f]{40,64}\Z")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_ENTRYPOINT_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*\Z")


class SignalEnvelopeValidationError(ValueError):
    """Raised when a V2 deterministic signal envelope is malformed or unsafe."""


def canonical_json_bytes(value: Any) -> bytes:
    """Return the contract's deterministic JSON bytes for a JSON-compatible value."""

    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise SignalEnvelopeValidationError("value is not canonical JSON") from exc
    return encoded.encode("utf-8")


def payload_sha256(payload: Any) -> str:
    """Return the SHA-256 of a canonical JSON payload."""

    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def validate_signal_envelope(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return a detached, JSON-only V2 signal envelope.

    The returned mapping remains ordinary JSON data.  Its immutable identity is
    the producer/input provenance plus the verified ``payload_sha256``; callers
    must re-validate after any mutation.
    """

    if not isinstance(envelope, Mapping):
        raise SignalEnvelopeValidationError("envelope must be an object")
    _require_exact_fields(envelope, _ENVELOPE_FIELDS, "envelope")
    normalized = _normalize_json_value(envelope, "envelope")
    _reject_forbidden_fields(normalized, "envelope")

    if normalized["schema_version"] != SCHEMA_VERSION:
        raise SignalEnvelopeValidationError(f"unsupported schema_version: {normalized['schema_version']!r}")
    if normalized["kind"] != SIGNAL_KIND:
        raise SignalEnvelopeValidationError(f"unsupported kind: {normalized['kind']!r}")

    _validate_plugin_id(normalized["plugin_id"])
    _validate_producer(normalized["producer"])
    _validate_input(normalized["input"])

    payload = normalized["payload"]
    if not isinstance(payload, dict) or not payload:
        raise SignalEnvelopeValidationError("payload must be a non-empty object")
    _reject_latest_references(payload, "payload")

    supplied_hash = normalized["payload_sha256"]
    _validate_sha256(supplied_hash, "payload_sha256")
    actual_hash = payload_sha256(payload)
    if supplied_hash != actual_hash:
        raise SignalEnvelopeValidationError(
            f"payload_sha256 does not match canonical payload: expected {actual_hash}, got {supplied_hash}"
        )
    return normalized


def build_signal_envelope(
    *,
    plugin_id: str,
    producer: Mapping[str, Any],
    input_provenance: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Build then validate a deterministic V2 signal envelope without I/O."""

    normalized_payload = _normalize_json_value(payload, "payload")
    envelope: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "plugin_id": plugin_id,
        "kind": SIGNAL_KIND,
        "producer": dict(producer),
        "input": dict(input_provenance),
        "payload": normalized_payload,
        "payload_sha256": payload_sha256(normalized_payload),
    }
    return validate_signal_envelope(envelope)


def _require_exact_fields(value: Mapping[str, Any], expected: frozenset[str], location: str) -> None:
    keys = set(value)
    if any(not isinstance(key, str) for key in keys):
        raise SignalEnvelopeValidationError(f"{location} field names must be strings")
    missing = sorted(expected - keys)
    unknown = sorted(keys - expected)
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append(f"missing={','.join(missing)}")
        if unknown:
            details.append(f"unknown={','.join(unknown)}")
        raise SignalEnvelopeValidationError(f"{location} fields invalid ({'; '.join(details)})")


def _normalize_json_value(value: Any, location: str) -> Any:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SignalEnvelopeValidationError(f"{location} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                raise SignalEnvelopeValidationError(f"{location} contains an empty or non-string field name")
            normalized[key] = _normalize_json_value(item, f"{location}.{key}")
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [_normalize_json_value(item, f"{location}[{index}]") for index, item in enumerate(value)]
    raise SignalEnvelopeValidationError(f"{location} contains a non-JSON value: {type(value).__name__}")


def _validate_plugin_id(plugin_id: Any) -> None:
    if not isinstance(plugin_id, str) or not _PLUGIN_ID_PATTERN.fullmatch(plugin_id):
        raise SignalEnvelopeValidationError("plugin_id must be lowercase [a-z0-9_-] and start with a letter")
    _reject_latest_reference(plugin_id, "plugin_id")


def _validate_producer(producer: Any) -> None:
    if not isinstance(producer, dict):
        raise SignalEnvelopeValidationError("producer must be an object")
    _require_exact_fields(producer, _PRODUCER_FIELDS, "producer")
    repo = producer["repo"]
    if not isinstance(repo, str) or not _REPOSITORY_PATTERN.fullmatch(repo):
        raise SignalEnvelopeValidationError("producer.repo must be an immutable repository slug (owner/repository)")
    _reject_latest_reference(repo, "producer.repo")
    revision = producer["revision"]
    if not isinstance(revision, str) or not _REVISION_PATTERN.fullmatch(revision):
        raise SignalEnvelopeValidationError("producer.revision must be a lowercase immutable git SHA")
    entrypoint = producer["entrypoint"]
    if not isinstance(entrypoint, str) or not _ENTRYPOINT_PATTERN.fullmatch(entrypoint):
        raise SignalEnvelopeValidationError("producer.entrypoint must be a Python module:function, not a path")
    _reject_latest_reference(entrypoint, "producer.entrypoint")
    _validate_sha256(producer["code_sha256"], "producer.code_sha256")
    _validate_sha256(producer["config_sha256"], "producer.config_sha256")


def _validate_input(input_provenance: Any) -> None:
    if not isinstance(input_provenance, dict):
        raise SignalEnvelopeValidationError("input must be an object")
    _require_exact_fields(input_provenance, _INPUT_FIELDS, "input")
    _validate_sha256(input_provenance["p1_manifest_sha256"], "input.p1_manifest_sha256")
    _validate_sha256(input_provenance["input_root_sha256"], "input.input_root_sha256")
    cutoff = input_provenance["date_cutoff"]
    if not isinstance(cutoff, str):
        raise SignalEnvelopeValidationError("input.date_cutoff must be YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(cutoff)
    except ValueError as exc:
        raise SignalEnvelopeValidationError("input.date_cutoff must be YYYY-MM-DD") from exc
    if parsed.isoformat() != cutoff:
        raise SignalEnvelopeValidationError("input.date_cutoff must be YYYY-MM-DD")


def _validate_sha256(value: Any, location: str) -> None:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise SignalEnvelopeValidationError(f"{location} must be a lowercase SHA-256 hex digest")


def _reject_forbidden_fields(value: Any, location: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized_key = _normalized_field_name(key)
            if _is_forbidden_field(normalized_key):
                raise SignalEnvelopeValidationError(f"{location}.{key} is forbidden in deterministic signal V2")
            _reject_forbidden_fields(item, f"{location}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_forbidden_fields(item, f"{location}[{index}]")


def _normalized_field_name(key: str) -> str:
    split_camel_case = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    return re.sub(r"[^a-z0-9]+", "_", split_camel_case.casefold()).strip("_")


def _is_forbidden_field(normalized_key: str) -> bool:
    if normalized_key in {
        "order",
        "orders",
        "target_weight",
        "target_weights",
        "authorization",
        "automation_approved",
        "ai",
        "llm",
    }:
        return True
    return normalized_key.startswith(
        ("order_", "orders_", "authorization_", "automation_approved_", "ai_", "llm_")
    )


def _reject_latest_reference(value: Any, location: str) -> None:
    if not isinstance(value, str):
        return
    normalized = value.strip().casefold().replace("\\", "/")
    parts = tuple(part for part in normalized.split("/") if part)
    if normalized == "latest" or any(
        part == "latest" or part.startswith("latest_") or part.startswith("latest-") or part.startswith("latest.")
        for part in parts
    ):
        raise SignalEnvelopeValidationError(f"{location} must not reference a mutable latest artifact")


def _reject_latest_references(value: Any, location: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_latest_references(item, f"{location}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_latest_references(item, f"{location}[{index}]")
        return
    _reject_latest_reference(value, location)
