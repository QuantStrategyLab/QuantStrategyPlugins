from __future__ import annotations

import base64
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pandas as pd
import pytest

import quant_strategy_plugins.tqqq_market_regime_control_present as present_module
from quant_strategy_plugins.strategy_plugin_runner import run_market_regime_control_plugin


AS_OF = "2025-12-31"
EXPECTED_COMMIT = subprocess.check_output(
    ["git", "rev-parse", "HEAD"], text=True, cwd=Path(__file__).resolve().parents[1]
).strip()


def _market_regime_prices() -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=260)
    qqq = pd.Series([100.0 + index * 0.10 for index in range(len(dates))], index=dates)
    qqq.iloc[-30:] = pd.Series([125.0 - index * (45.0 / 29.0) for index in range(30)], index=dates[-30:])
    vix = pd.Series(15.0, index=dates)
    vix.iloc[-6:] = [24.0, 27.0, 31.0, 34.0, 38.0, 41.0]
    hyg = pd.Series(100.0, index=dates)
    hyg.iloc[-22:] = pd.Series([100.0 - index * (9.0 / 21.0) for index in range(22)], index=dates[-22:])
    ief = pd.Series(100.0, index=dates)
    ief.iloc[-22:] = pd.Series([100.0 + index * (3.0 / 21.0) for index in range(22)], index=dates[-22:])
    rows: list[dict[str, object]] = []
    for symbol, series in {"QQQ": qqq, "TQQQ": qqq * 3.0, "VIX": vix, "HYG": hyg, "IEF": ief}.items():
        for as_of, close in series.items():
            rows.append({"symbol": symbol, "as_of": as_of, "close": close, "volume": 1_000_000})
    return pd.DataFrame(rows)


def _config(tmp_path: Path) -> Path:
    prices_path = tmp_path / "prices.csv"
    _market_regime_prices().to_csv(prices_path, index=False)
    config_path = tmp_path / "strategy_plugins.toml"
    config_path.write_text(
        f"""
default_mode = "shadow"

[[strategy_plugins]]
strategy = "tqqq_growth_income"
plugin = "market_regime_control"
enabled = true
mode = "shadow"

[strategy_plugins.inputs]
prices = "{prices_path}"
as_of = "{AS_OF}"
vix_symbols = ["VIX"]
credit_pairs = ["HYG:IEF"]
crisis_enabled = false
taco_enabled = false
crisis_score_threshold = 99.0

[strategy_plugins.outputs]
output_dir = "{tmp_path / 'writer-output'}"
""".strip(),
        encoding="utf-8",
    )
    return config_path


def _capture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, output_dir: Path | None = None):
    source_checks: list[Path | None] = []
    monkeypatch.setattr(
        present_module,
        "_verify_source_identity",
        lambda _expected, private_stage=None: source_checks.append(private_stage),
    )
    calls: list[dict[str, object]] = []

    def run_once(config: dict[str, object], mode: str):
        calls.append(dict(config))
        return run_market_regime_control_plugin(config, mode)

    monkeypatch.setattr(present_module, "run_market_regime_control_plugin", run_once)
    package = present_module.capture_tqqq_market_regime_control_present(
        config_path=_config(tmp_path),
        output_dir=output_dir or tmp_path / "packages",
        expected_qsp_commit_sha=EXPECTED_COMMIT,
        as_of=AS_OF,
        session_id=f"XNAS:{AS_OF}",
    )
    return package, calls, source_checks


def test_capture_publishes_one_canonical_package_after_one_current_producer_call(tmp_path, monkeypatch) -> None:
    package, calls, source_checks = _capture(tmp_path, monkeypatch)

    package_bytes = package.path.read_bytes()
    decoded = json.loads(package_bytes)
    payload_bytes = base64.b64decode(decoded["payload"]["bytes_b64"], validate=True)

    assert len(calls) == 1
    assert source_checks[0] is None
    assert source_checks[1] is not None
    assert package.path.parent == tmp_path / "packages"
    assert package.path.name == f"tqqq-market-regime-control-present-{AS_OF}-{package.sha256}.json"
    assert package.sha256 == hashlib.sha256(package_bytes).hexdigest()
    assert package_bytes == json.dumps(
        decoded, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    assert decoded["schema"] == "qsl.tqqq_market_regime_control_present.v1"
    assert decoded["session_id"] == f"XNAS:{AS_OF}"
    assert set(decoded["inputs"]["prices"]) == {"format", "sha256", "size_bytes"}
    assert decoded["inputs"]["prices"]["format"] == "csv"
    assert decoded["inputs"]["external_context"] == {"status": "ABSENT"}
    assert "output_dir" not in decoded["config"]["value"]
    assert decoded["config"]["value"]["mode"] == "shadow"
    assert decoded["payload"]["sha256"] == hashlib.sha256(payload_bytes).hexdigest()
    assert list((tmp_path / "packages").iterdir()) == [package.path]


def test_capture_allows_unignored_in_repository_output_and_removes_private_stage(tmp_path, monkeypatch) -> None:
    output_dir = Path.cwd() / f"tqqq-present-output-{tmp_path.name}"
    try:
        package, _, source_checks = _capture(tmp_path, monkeypatch, output_dir=output_dir)

        assert package.path.parent == output_dir
        assert source_checks[0] is None
        assert source_checks[1] is not None
        assert source_checks[1].parent == output_dir
        assert not list(output_dir.glob(".tqqq-market-regime-control-present-*"))
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


def test_capture_rejects_staged_input_mutation_without_a_final_package(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(present_module, "_verify_source_identity", lambda _expected: None)

    def mutate_after_run(config: dict[str, object], mode: str):
        result = run_market_regime_control_plugin(config, mode)
        Path(str(config["prices"])).write_bytes(b"changed")
        return result

    monkeypatch.setattr(present_module, "run_market_regime_control_plugin", mutate_after_run)
    destination = tmp_path / "packages"

    with pytest.raises(present_module.PresentPackageError, match="T2B2_PRODUCER_INPUT_INVALID"):
        present_module.capture_tqqq_market_regime_control_present(
            config_path=_config(tmp_path),
            output_dir=destination,
            expected_qsp_commit_sha=EXPECTED_COMMIT,
            as_of=AS_OF,
            session_id=f"XNAS:{AS_OF}",
        )

    assert not list(destination.glob("*.json"))


def test_capture_rejects_dated_latest_mismatch_without_a_final_package(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(present_module, "_verify_source_identity", lambda _expected: None)

    def corrupt_latest(config: dict[str, object], mode: str):
        result = run_market_regime_control_plugin(config, mode)
        Path(str(config["output_dir"])).joinpath("latest_signal.json").write_text("{}", encoding="utf-8")
        return result

    monkeypatch.setattr(present_module, "run_market_regime_control_plugin", corrupt_latest)
    destination = tmp_path / "packages"

    with pytest.raises(present_module.PresentPackageError, match="T2B2_PRODUCER_ARTIFACT_INVALID"):
        present_module.capture_tqqq_market_regime_control_present(
            config_path=_config(tmp_path),
            output_dir=destination,
            expected_qsp_commit_sha=EXPECTED_COMMIT,
            as_of=AS_OF,
            session_id=f"XNAS:{AS_OF}",
        )

    assert not list(destination.glob("*.json"))


def test_source_identity_rejects_a_wrong_expected_commit(monkeypatch) -> None:
    monkeypatch.setattr(present_module, "_git", lambda *_args: str(Path.cwd()))

    with pytest.raises(present_module.PresentPackageError, match="T2B2_PRODUCER_IDENTITY_INVALID"):
        present_module._verify_source_identity("0" * 40)


def _source_identity_git(monkeypatch, status: str) -> tuple[Path, list[tuple[str, ...]]]:
    root = Path.cwd().resolve()
    relative_module = Path(present_module.__file__).resolve().relative_to(root)
    calls: list[tuple[str, ...]] = []

    def fake_git(*args: str) -> str:
        calls.append(args)
        if args == ("rev-parse", "--show-toplevel"):
            return str(root)
        if args == ("ls-files", "--error-unmatch", str(relative_module)):
            return str(relative_module)
        if args and args[0] == "status":
            return status
        if args == ("rev-parse", "HEAD"):
            return EXPECTED_COMMIT
        raise AssertionError(args)

    monkeypatch.setattr(present_module, "_git", fake_git)
    return root, calls


def test_second_source_identity_check_allows_only_its_private_stage(monkeypatch) -> None:
    root = Path.cwd().resolve()
    private_stage = root / "unignored-output" / ".tqqq-market-regime-control-present-test"
    relative_stage = private_stage.relative_to(root).as_posix()
    _, calls = _source_identity_git(monkeypatch, f"?? {relative_stage}/\0")

    present_module._verify_source_identity(EXPECTED_COMMIT, private_stage=private_stage)

    assert ("status", "--porcelain=v1", "-z", "--untracked-files=all") in calls

    with pytest.raises(present_module.PresentPackageError, match="T2B2_PRODUCER_IDENTITY_INVALID"):
        present_module._verify_source_identity(EXPECTED_COMMIT)


@pytest.mark.parametrize("status", [" M src/unrelated.py\0", "?? unrelated.txt\0"])
def test_second_source_identity_check_rejects_unrelated_tracked_or_untracked_dirt(monkeypatch, status: str) -> None:
    root = Path.cwd().resolve()
    private_stage = root / "unignored-output" / ".tqqq-market-regime-control-present-test"
    _source_identity_git(monkeypatch, f"?? {private_stage.relative_to(root).as_posix()}/\0{status}")

    with pytest.raises(present_module.PresentPackageError, match="T2B2_PRODUCER_IDENTITY_INVALID"):
        present_module._verify_source_identity(EXPECTED_COMMIT, private_stage=private_stage)


def test_identity_failure_does_not_create_a_final_package(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        present_module,
        "_verify_source_identity",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(present_module.PresentPackageError("T2B2_PRODUCER_IDENTITY_INVALID", 2)),
    )
    destination = tmp_path / "packages"

    with pytest.raises(present_module.PresentPackageError, match="T2B2_PRODUCER_IDENTITY_INVALID"):
        present_module.capture_tqqq_market_regime_control_present(
            config_path=_config(tmp_path),
            output_dir=destination,
            expected_qsp_commit_sha=EXPECTED_COMMIT,
            as_of=AS_OF,
            session_id=f"XNAS:{AS_OF}",
        )

    assert not destination.exists()


def test_strict_readback_rejects_an_unknown_package_field(tmp_path, monkeypatch) -> None:
    package, _, _ = _capture(tmp_path, monkeypatch)
    decoded = json.loads(package.path.read_bytes())
    decoded["unknown"] = "rejected"

    with pytest.raises(present_module.PresentPackageError, match="T2B2_PRODUCER_PUBLISH_FAILED"):
        present_module._verify_present_package(
            json.dumps(decoded, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            expected_qsp_commit_sha=EXPECTED_COMMIT,
        )
