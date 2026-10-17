from copy import deepcopy

import pytest

from quant_strategy_plugins.market_regime_control_plugin import build_market_regime_control_signal


CONTRACTS = {
    "crisis": ("crisis_response_shadow", "crisis_response_shadow.v1"),
    "macro": ("macro_risk_governor", "macro_risk_governor.v1"),
    "taco": ("taco_rebound_shadow", "taco_rebound_shadow.v2"),
    "panic_reversal": ("panic_reversal_shadow", "panic_reversal_shadow.v1"),
    "benchmark_guard": ("benchmark_drawdown_guard", "benchmark_drawdown_guard.v1"),
}


def component(kind="crisis", route="no_action"):
    identity, version = CONTRACTS[kind]
    return {
        "profile": identity,
        "schema_version": version,
        "as_of": "2026-10-16",
        "canonical_route": route,
        "suggested_action": "defend" if route == "true_crisis" else "no_action",
    }


def without_generated_at(payload):
    # Artifact creation time changes naturally; every strategy/authority field remains compared.
    return {key: value for key, value in payload.items() if key != "generated_at"}


@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_sequence_rejects_instead_of_selecting_first_or_last(reverse):
    signals = [component(route="true_crisis"), component()]
    if reverse:
        signals.reverse()
    with pytest.raises(ValueError, match="duplicate_component.*crisis"):
        build_market_regime_control_signal(signals)


@pytest.mark.parametrize("alias", ["crisis_response_shadow", " CRISIS ", "external_crisis"])
def test_mapping_alias_cannot_overwrite_a_normalized_component(alias):
    with pytest.raises(ValueError, match="duplicate_component.*crisis"):
        build_market_regime_control_signal({"crisis": component(), alias: component()})


@pytest.mark.parametrize("version", [None, "", " \t"])
def test_component_missing_schema_has_an_explanatory_rejection(version):
    signal = component()
    signal["schema_version"] = version
    with pytest.raises(ValueError, match="crisis.*missing_schema_version"):
        build_market_regime_control_signal({"crisis": signal})


def test_component_schema_key_is_required_without_defaulting():
    signal = component()
    del signal["schema_version"]
    with pytest.raises(ValueError, match="crisis.*missing_schema_version"):
        build_market_regime_control_signal({"crisis": signal})


@pytest.mark.parametrize("version", ["foreign.v1", "macro_risk_governor.v1", "crisis_response_shadow.v9", 1, True])
def test_component_schema_must_match_its_existing_contract(version):
    signal = component()
    signal["schema_version"] = version
    with pytest.raises(ValueError, match="crisis.*unsupported_schema_version"):
        build_market_regime_control_signal({"crisis": signal})


def test_canonical_mapping_key_cannot_disguise_a_different_component():
    with pytest.raises(ValueError, match="identity_mismatch"):
        build_market_regime_control_signal({"crisis": component("macro")})


def test_plugin_cannot_hide_a_conflicting_profile():
    signal = component()
    signal["plugin"] = "macro_risk_governor"
    with pytest.raises(ValueError, match="identity_mismatch"):
        build_market_regime_control_signal({"crisis": signal})


def test_matching_plugin_and_profile_remain_valid():
    signal = component(route="true_crisis")
    signal["plugin"] = " CRISIS_RESPONSE_SHADOW "
    assert build_market_regime_control_signal([signal])["canonical_route"] == "risk_off"


def test_identical_duplicate_objects_are_not_implicitly_merged():
    signal = component()
    with pytest.raises(ValueError, match="duplicate_component.*crisis"):
        build_market_regime_control_signal([signal, signal])


@pytest.mark.parametrize("version", [None, "foreign.v1"])
def test_invalid_component_does_not_write_a_replacement_signal(monkeypatch, tmp_path, version):
    from dataclasses import replace

    import pandas as pd

    from quant_strategy_plugins import strategy_plugin_runner as runner

    signal = component(route="true_crisis")
    signal["schema_version"] = version
    writer_calls = []

    def unexpected_writer(*args, **kwargs):
        writer_calls.append(True)
        raise AssertionError("invalid component reached output writer")

    monkeypatch.setattr(runner, "read_table", lambda path: pd.DataFrame())
    monkeypatch.setattr(runner, "_build_crisis_response_payload", lambda prices, config: signal)
    monkeypatch.setattr(
        runner, "MARKET_REGIME_CONTROL_SPEC",
        replace(runner.MARKET_REGIME_CONTROL_SPEC, write_outputs=unexpected_writer),
    )
    with pytest.raises(ValueError, match="crisis.*schema_version"):
        runner.run_market_regime_control_plugin(
            {
                "strategy": "tqqq_growth_income",
                "prices": "synthetic-test-input.csv",
                "output_dir": str(tmp_path / "out"),
                "crisis_enabled": True,
                "macro_enabled": False,
                "taco_enabled": False,
                "panic_reversal_enabled": False,
            },
            "shadow",
        )
    assert writer_calls == []
    assert not (tmp_path / "out" / "latest_signal.json").exists()


@pytest.mark.parametrize("identity", [None, "", "made_up_crisis_response_shadow"])
def test_unknown_or_missing_identity_is_not_silently_ignored(identity):
    signal = component()
    signal["profile"] = identity
    with pytest.raises(ValueError, match="invalid_component"):
        build_market_regime_control_signal([signal])


@pytest.mark.parametrize("signals", [None, "crisis", b"crisis", [None], {"crisis": None}])
def test_explicit_malformed_input_is_rejected(signals):
    with pytest.raises(ValueError, match="invalid_component"):
        build_market_regime_control_signal(signals)


@pytest.mark.parametrize("kind", CONTRACTS)
def test_existing_versions_and_optional_components_preserve_no_action(kind):
    signal = component(kind)
    original = deepcopy(signal)
    output = build_market_regime_control_signal({kind: signal}, as_of="2026-10-16")
    assert output["canonical_route"] == "no_action"
    assert output["as_of"] == "2026-10-16"
    assert output["execution_controls"]["broker_order_allowed"] is False
    assert output["execution_controls"]["position_control_shadow_only"] is True
    assert signal == original


def test_alias_and_plugin_only_inputs_preserve_existing_normalization():
    signal = component(route="true_crisis")
    signal["plugin"] = " CRISIS_RESPONSE_SHADOW "
    del signal["profile"]
    alias = build_market_regime_control_signal({"external_crisis": signal}, as_of="2026-10-16")
    sequence = build_market_regime_control_signal([signal], as_of="2026-10-16")
    assert without_generated_at(alias) == without_generated_at(sequence)
    assert alias["canonical_route"] == "risk_off"
    assert alias["position_control"]["risk_asset_scalar"] == 0.0


def test_valid_set_order_does_not_change_routing_or_scalars():
    signals = [component("macro"), component(route="true_crisis")]
    forward = build_market_regime_control_signal(signals)
    reverse = build_market_regime_control_signal(list(reversed(signals)))
    assert without_generated_at(forward) == without_generated_at(reverse)


@pytest.mark.parametrize("signals", [{}, []])
def test_empty_collection_is_still_valid(signals):
    assert build_market_regime_control_signal(signals, as_of="2026-10-16")["canonical_route"] == "no_action"


def test_mixed_component_dates_remain_descriptive_pending_a_time_contract():
    old = component(route="true_crisis")
    old["as_of"] = "2020-01-01"
    output = build_market_regime_control_signal({"crisis": old, "macro": component("macro")})
    assert output["as_of"] == "2026-10-16"
    assert output["canonical_route"] == "risk_off"
    assert output["component_signals"]["crisis"]["as_of"] == "2020-01-01"
