from __future__ import annotations

from pathlib import Path
import json
import re
import subprocess

import pytest

from quant_strategy_plugins import tqqq_market_regime_control_present as present


def _config(tmp_path: Path, *, extra: str = "") -> Path:
    prices = tmp_path / "prices.csv"
    prices.write_text("date,close\n2026-01-02,100\n", encoding="utf-8")
    config = tmp_path / "plugins.toml"
    override = re.match(r"^([a-z_]+) = .+$", extra)
    override_key = override.group(1) if override else None
    known_input_keys = {
        "attack_symbol", "benchmark_symbol", "credit_pairs", "crisis_enabled", "delever_risk_asset_scalar",
        "event_set", "external_stress_actionable", "financial_symbols", "macro_enabled", "panic_reversal_enabled",
        "prices", "rate_symbols", "realized_vol_requires_confirmation", "realized_vol_threshold", "strategy_policy",
        "taco_enabled", "taco_opportunity_size_scalar", "vix3m_symbols", "vix_symbols",
    }
    extra_line = "" if override_key in known_input_keys else extra
    contents = "\n".join(
            [
                'default_mode = "shadow"',
                "[[strategy_plugins]]",
                'strategy = "tqqq_growth_income"',
                'plugin = "market_regime_control"',
                "enabled = true",
                "[strategy_plugins.inputs]",
                f'prices = "{prices}"',
                'event_set = "full"',
                'benchmark_symbol = "QQQ"',
                'attack_symbol = "TQQQ"',
                'vix_symbols = ["VIX"]',
                'vix3m_symbols = ["VIX3M"]',
                'credit_pairs = ["HYG:IEF"]',
                'financial_symbols = ["XLF"]',
                'rate_symbols = ["IEF"]',
                'strategy_policy = "levered_growth_income_v1"',
                "realized_vol_threshold = 0.3",
                "realized_vol_requires_confirmation = true",
                "external_stress_actionable = false",
                "delever_risk_asset_scalar = 0.0",
                "taco_opportunity_size_scalar = 0.0",
                "crisis_enabled = true",
                "macro_enabled = true",
                "taco_enabled = true",
                "panic_reversal_enabled = false",
                extra_line,
                "[strategy_plugins.outputs]",
                f'output_dir = "{tmp_path / "output"}"',
                "",
            ]
        )
    if override_key in known_input_keys:
        contents = re.sub(rf"^{re.escape(override_key)} = .+$", extra, contents, flags=re.MULTILINE)
    config.write_text(contents, encoding="utf-8")
    return config


@pytest.fixture
def source_gate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(present, "_source_identity", lambda expected: tmp_path / "checkout")


def _run(config: Path, producer) -> Path:
    return present.run_present(
        config,
        as_of="2026-01-02",
        session_id="XNAS:2026-01-02",
        expected_commit="a" * 40,
        producer=producer,
    )


def test_safe_projection_is_fresh_and_only_safe_fields_reach_producer(
    tmp_path: Path, source_gate: None
) -> None:
    calls: list[dict[str, object]] = []

    def producer(config: dict[str, object], default_mode: str) -> object:
        calls.append(config)
        raise AssertionError("test seam must not reach a producer before validation is implemented")

    with pytest.raises(present.PresentError) as error:
        _run(_config(tmp_path), producer)

    assert error.value.code == "T2B2_PRODUCER_EXECUTION_FAILED"
    assert len(calls) == 1
    assert set(calls[0]) == set(present.RUNNER_KEYS - {"external_context"})
    assert calls[0]["mode"] == "shadow"
    assert calls[0]["as_of"] == "2026-01-02"


def _sensitive_name(*parts: str) -> str:
    return "_".join(parts)


@pytest.mark.parametrize("parts", [("private", "key"), ("access", "key"), ("credential",)])
def test_credentials_fail_closed_before_producer_or_output_mutation(
    tmp_path: Path, source_gate: None, parts: tuple[str, ...]
) -> None:
    field = _sensitive_name(*parts)
    sentinel = f"UNIQUE_{field}_SENTINEL"
    config = _config(tmp_path, extra=f'{field} = "{sentinel}"')
    calls = 0

    def producer(*args: object) -> object:
        nonlocal calls
        calls += 1
        return None

    with pytest.raises(present.PresentError) as error:
        _run(config, producer)

    assert error.value.code == "T2B2_PRODUCER_INPUT_INVALID"
    assert error.value.exit_code == 2
    assert calls == 0
    assert not (tmp_path / "output").exists()
    assert sentinel not in str(error.value)
    assert field not in str(error.value)


@pytest.mark.parametrize(
    "extra",
    [
        "taco_opportunity_size_scalar = []",
        "taco_opportunity_size_scalar = { nested = 1 }",
        'vix_symbols = [["VIX"]]',
    ],
)
def test_non_scalar_toml_is_input_invalid_without_traceback_or_producer(
    tmp_path: Path, source_gate: None, extra: str, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _config(tmp_path, extra=extra)
    assert present.main(
        [
            "--config",
            str(config),
            "--as-of",
            "2026-01-02",
            "--session-id",
            "XNAS:2026-01-02",
            "--expected-commit",
            "a" * 40,
        ]
    ) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "ERROR T2B2_PRODUCER_INPUT_INVALID\n"
    assert "Traceback" not in captured.err
    assert not (tmp_path / "output").exists()


def test_unknown_key_is_rejected_by_closed_schema_not_only_secret_denylist(tmp_path: Path, source_gate: None) -> None:
    config = _config(tmp_path, extra='innocent_unknown_name = "safe-looking"')

    with pytest.raises(present.PresentError) as error:
        _run(config, lambda *args: None)

    assert error.value.code == "T2B2_PRODUCER_INPUT_INVALID"
    assert not (tmp_path / "output").exists()


def test_invalid_schema_preserves_an_existing_output_tree(tmp_path: Path, source_gate: None) -> None:
    output = tmp_path / "output"
    output.mkdir()
    existing = output / "tqqq-market-regime-control-present-existing.json"
    existing.write_bytes(b"preserve")
    before = {path.relative_to(output): path.read_bytes() for path in output.rglob("*") if path.is_file()}

    with pytest.raises(present.PresentError) as error:
        _run(_config(tmp_path, extra=f'{_sensitive_name("private", "key")} = "UNIQUE_SECRET"'), lambda *args: None)

    after = {path.relative_to(output): path.read_bytes() for path in output.rglob("*") if path.is_file()}
    assert error.value.code == "T2B2_PRODUCER_INPUT_INVALID"
    assert before == after


def _valid_payload(as_of: str) -> bytes:
    value = {key: {} for key in present.PAYLOAD_KEYS}
    value.update(
        {
            "as_of": as_of,
            "schema_version": "market_regime_control.v1",
            "profile": "market_regime_control",
            "strategy": "tqqq_growth_income",
            "plugin": "market_regime_control",
            "target_type": "strategy",
            "mode": "shadow",
            "configured_mode": "shadow",
            "effective_mode": "shadow",
        }
    )
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def test_valid_capture_publishes_only_safe_canonical_package(tmp_path: Path, source_gate: None) -> None:
    config = _config(tmp_path)
    payload = _valid_payload("2026-01-02")

    def producer(projection: dict[str, object], default_mode: str) -> None:
        writer_root = Path(str(projection["output_dir"]))
        (writer_root / "signals").mkdir(parents=True)
        (writer_root / "signals" / "2026-01-02.json").write_bytes(payload)
        (writer_root / "latest_signal.json").write_bytes(payload)

    destination = _run(config, producer)
    package = json.loads(destination.read_text(encoding="utf-8"))
    config_value = package["config"]["value"]
    assert destination.parent == tmp_path / "output"
    assert set(config_value) == set(present.PACKAGE_KEYS - {"external_context"})
    assert config_value["prices"] == "@input:prices"
    assert "output_dir" not in config_value
    assert all(not isinstance(value, dict) for value in config_value.values())
    assert list((tmp_path / "output").iterdir()) == [destination]


def test_producer_type_error_is_execution_failure_without_final_package(tmp_path: Path, source_gate: None) -> None:
    with pytest.raises(present.PresentError) as error:
        _run(_config(tmp_path), lambda *_: (_ for _ in ()).throw(TypeError("producer-only")))

    assert error.value.code == "T2B2_PRODUCER_EXECUTION_FAILED"
    assert not list((tmp_path / "output").glob("tqqq-market-regime-control-present-*.json"))


def test_missing_producer_artifact_is_artifact_failure_without_final_package(tmp_path: Path, source_gate: None) -> None:
    with pytest.raises(present.PresentError) as error:
        _run(_config(tmp_path), lambda *_: None)

    assert error.value.code == "T2B2_PRODUCER_ARTIFACT_INVALID"
    assert not list((tmp_path / "output").glob("tqqq-market-regime-control-present-*.json"))


@pytest.mark.parametrize(
    "extra",
    [
        f'[strategy_plugins.settings.broker]\n{_sensitive_name("private", "key")} = "UNIQUE_NESTED"',
        f'attack_symbol = {{ {_sensitive_name("access", "key")} = "UNIQUE_INLINE" }}',
        f'vix_symbols = [{{ {_sensitive_name("credential")} = "UNIQUE_ARRAY" }}]',
    ],
)
def test_nested_credential_names_fail_closed_without_disclosure(tmp_path: Path, source_gate: None, extra: str) -> None:
    config = _config(tmp_path, extra=extra)
    sentinel = "UNIQUE_NESTED" if "NESTED" in extra else "UNIQUE_INLINE" if "INLINE" in extra else "UNIQUE_ARRAY"

    with pytest.raises(present.PresentError) as error:
        _run(config, lambda *_: None)

    assert error.value.code == "T2B2_PRODUCER_INPUT_INVALID"
    assert sentinel not in str(error.value)
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize(
    "extra",
    [
        "realized_vol_threshold = 1",
        "realized_vol_threshold = nan",
        "realized_vol_threshold = inf",
        "taco_opportunity_size_scalar = 1.1",
        'event_set = "not-an-event"',
        'benchmark_symbol = "bad symbol"',
        'credit_pairs = ["BAD"]',
        "vix_symbols = []",
        'vix_symbols = ["VIX", "VIX"]',
        "vix_symbols = [\"VIX\", \"VIX3M\", \"A\", \"B\", \"C\", \"D\", \"E\", \"F\", \"G\", \"H\", \"I\", \"J\", \"K\", \"L\", \"M\", \"N\", \"O\"]",
    ],
)
def test_illegal_scalar_and_collection_values_fail_before_producer(tmp_path: Path, source_gate: None, extra: str) -> None:
    with pytest.raises(present.PresentError) as error:
        _run(_config(tmp_path, extra=extra), lambda *_: None)

    assert error.value.code == "T2B2_PRODUCER_INPUT_INVALID"
    assert not (tmp_path / "output").exists()


def test_unignored_in_checkout_output_root_is_rejected_before_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    subprocess.run(("git", "init", "-q", str(tmp_path)), check=True)
    monkeypatch.setattr(present, "_source_identity", lambda expected: tmp_path)
    config = _config(tmp_path)

    with pytest.raises(present.PresentError) as error:
        _run(config, lambda *_: None)

    assert error.value.code == "T2B2_PRODUCER_IDENTITY_INVALID"
    assert not (tmp_path / "output").exists()


def test_ignored_in_checkout_output_root_is_admitted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    subprocess.run(("git", "init", "-q", str(tmp_path)), check=True)
    (tmp_path / ".gitignore").write_text("output/\n", encoding="utf-8")
    monkeypatch.setattr(present, "_source_identity", lambda expected: tmp_path)
    config = _config(tmp_path)

    with pytest.raises(present.PresentError) as error:
        _run(config, lambda *_: None)

    assert error.value.code == "T2B2_PRODUCER_ARTIFACT_INVALID"
    assert (tmp_path / "output").is_dir()
