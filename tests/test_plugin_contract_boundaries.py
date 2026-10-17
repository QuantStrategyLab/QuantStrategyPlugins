"""Offline checks of existing contracts; every configured producer stays OFF."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from quant_strategy_plugins.artifacts import sha256_file, write_json
from quant_strategy_plugins.plugin_catalog import build_plugin_catalog
from quant_strategy_plugins.plugin_signal_envelope_v2 import (
    SignalEnvelopeValidationError,
    validate_signal_envelope,
)
from quant_strategy_plugins.russell_1000_multi_factor_defensive_snapshot import read_table
from quant_strategy_plugins import strategy_plugin_runner as runner


def test_catalog_is_detached_and_has_stable_identifier_order():
    expected = build_plugin_catalog()
    returned = build_plugin_catalog()
    ids = [entry["plugin_id"] for entry in expected["entries"]]
    assert ids == sorted(ids) and len(ids) == len(set(ids))
    returned["entries"][0]["owner_strategy"].append("synthetic_caller_mutation")
    returned["entries"][0]["broker_order_allowed"] = True
    assert build_plugin_catalog() == expected


@pytest.mark.parametrize("target_type", ["strategy_plugins", "notification_targets"])
def test_all_disabled_entries_do_not_load_inputs_or_write_signals(tmp_path, monkeypatch, target_type):
    def unexpected_read(*args, **kwargs):
        raise AssertionError("disabled producer must not read material")

    monkeypatch.setattr(runner, "read_table", unexpected_read)
    entries = []
    for entry in reversed(build_plugin_catalog()["entries"]):
        scope = {"strategy": entry["owner_strategy"][0]} if target_type == "strategy_plugins" else {
            "notification_target": "synthetic_disabled_target",
        }
        entries.append({
            **scope, "plugin": entry["plugin_id"], "enabled": False,
            "inputs": {"prices": str(tmp_path / "must-not-exist.csv")},
            "outputs": {"output_dir": str(tmp_path / "signals" / entry["plugin_id"])},
        })
    config = {"output_dir": str(tmp_path / "summary"), target_type: entries}
    original = deepcopy(config)
    result = runner.run_configured_plugins(config)
    assert config == original
    assert [r["plugin"] for r in result[target_type]] == [e["plugin"] for e in entries]
    assert all(r["status"] == "skipped" and r["enabled"] is False
               and r["effective_mode"] is None and r["latest_signal_path"] is None
               for r in result[target_type])
    assert not (tmp_path / "signals").exists()
    assert json.loads((tmp_path / "summary/latest_run.json").read_text()) == result


@pytest.mark.parametrize("container", ["inputs", "outputs", "settings"])
def test_nested_settings_cannot_override_explicit_disabled_flag(container):
    with pytest.raises(ValueError, match="duplicate strategy plugin config key.*enabled"):
        runner._flatten_strategy_plugin_entry({
            "plugin": "market_regime_control", "enabled": False, container: {"enabled": True},
        })


@pytest.mark.parametrize("plugin", ["panic_reversal_shadow", "synthetic_unknown_plugin"])
def test_incompatible_strategy_is_rejected_without_running_a_producer(plugin):
    with pytest.raises(ValueError, match="strategy-limited|unsupported plugin"):
        runner._validate_plugin_strategy(plugin, "soxl_soxx_trend_income")


def test_existing_envelope_fixture_survives_artifact_roundtrip_and_rejects_tamper(tmp_path):
    fixture = Path(__file__).parent / "fixtures/plugin_signal_envelope_v2/valid_signal.json"
    envelope = json.loads(fixture.read_text())
    output = write_json(tmp_path / "frozen-synthetic-signal.json", envelope)
    raw = output.read_bytes()
    assert sha256_file(output) == hashlib.sha256(raw).hexdigest()
    loaded = json.loads(raw)
    assert validate_signal_envelope(loaded) == envelope
    loaded["payload"]["regime"] = "synthetic_tampered_state"
    write_json(output, loaded)
    with pytest.raises(SignalEnvelopeValidationError, match="does not match canonical payload"):
        validate_signal_envelope(json.loads(output.read_text()))


def test_missing_local_material_is_rejected(tmp_path):
    with pytest.raises(FileNotFoundError, match="file not found"):
        read_table(tmp_path / "absent-synthetic-input.csv")


def test_unsupported_local_material_format_is_rejected(tmp_path):
    path = tmp_path / "synthetic-input.unsupported"
    path.write_text("{}")
    with pytest.raises(ValueError, match="Unsupported table format"):
        read_table(path)
