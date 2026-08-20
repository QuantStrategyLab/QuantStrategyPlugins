from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from quant_strategy_plugins.plugin_signal_envelope_v2 import (
    SCHEMA_VERSION,
    SignalEnvelopeValidationError,
    build_signal_envelope,
    canonical_json_bytes,
    payload_sha256,
    validate_signal_envelope,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "plugin_signal_envelope_v2"


def _load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def test_valid_fixture_has_a_stable_canonical_payload_hash() -> None:
    envelope = _load_fixture("valid_signal.json")

    validated = validate_signal_envelope(envelope)

    assert validated == envelope
    assert canonical_json_bytes(validated["payload"]) == (
        b'{"as_of":"2000-03-10","reason_codes":["trend_break","volatility_spike"],'
        b'"regime":"risk_off","signal":{"risk_state":"reduced"}}'
    )
    assert payload_sha256(validated["payload"]) == validated["payload_sha256"]


def test_builder_creates_a_valid_detached_envelope() -> None:
    source = _load_fixture("valid_signal.json")
    envelope = build_signal_envelope(
        plugin_id=str(source["plugin_id"]),
        producer=source["producer"],
        input_provenance=source["input"],
        payload=source["payload"],
    )

    assert envelope["schema_version"] == SCHEMA_VERSION
    assert envelope["payload_sha256"] == source["payload_sha256"]
    envelope["payload"]["regime"] = "mutated"
    with pytest.raises(SignalEnvelopeValidationError, match="payload_sha256"):
        validate_signal_envelope(envelope)


@pytest.mark.parametrize(
    ("fixture_name", "message"),
    [("forbidden_target_weight.json", "target_weight is forbidden")],
)
def test_rejects_forbidden_execution_or_authority_fields(fixture_name: str, message: str) -> None:
    with pytest.raises(SignalEnvelopeValidationError, match=message):
        validate_signal_envelope(_load_fixture(fixture_name))


@pytest.mark.parametrize("forbidden_key", ["order", "targetWeight", "authorization", "automation_approved", "ai_model", "llm"])
def test_rejects_forbidden_fields_nested_in_payload(forbidden_key: str) -> None:
    envelope = _load_fixture("valid_signal.json")
    payload = deepcopy(envelope["payload"])
    payload["nested"] = {forbidden_key: "unsafe"}
    envelope["payload"] = payload
    envelope["payload_sha256"] = payload_sha256(payload)

    with pytest.raises(SignalEnvelopeValidationError, match="forbidden"):
        validate_signal_envelope(envelope)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda envelope: envelope.update({"schema_version": "qsl.strategy-plugin-signal.v1"}), "unsupported schema"),
        (lambda envelope: envelope.update({"unexpected": True}), "unknown=unexpected"),
        (lambda envelope: envelope["producer"].update({"branch": "main"}), "producer fields invalid"),
        (lambda envelope: envelope["producer"].update({"entrypoint": "latest_signal.json"}), "entrypoint"),
        (lambda envelope: envelope["payload"].update({"artifact_path": "signals/latest_signal.json"}), "latest artifact"),
        (lambda envelope: envelope["input"].update({"date_cutoff": "2000/03/10"}), "date_cutoff"),
        (lambda envelope: envelope.update({"payload_sha256": "0" * 64}), "does not match"),
    ],
)
def test_rejects_unknown_mutable_or_malformed_values(mutator, message: str) -> None:
    envelope = _load_fixture("valid_signal.json")
    mutator(envelope)

    with pytest.raises(SignalEnvelopeValidationError, match=message):
        validate_signal_envelope(envelope)


def test_rejects_missing_required_input_provenance() -> None:
    envelope = _load_fixture("valid_signal.json")
    del envelope["input"]["input_root_sha256"]

    with pytest.raises(SignalEnvelopeValidationError, match="missing=input_root_sha256"):
        validate_signal_envelope(envelope)


def test_rejects_non_finite_payload_numbers() -> None:
    envelope = _load_fixture("valid_signal.json")
    envelope["payload"] = {"score": float("nan")}
    envelope["payload_sha256"] = "0" * 64

    with pytest.raises(SignalEnvelopeValidationError, match="non-finite"):
        validate_signal_envelope(envelope)
