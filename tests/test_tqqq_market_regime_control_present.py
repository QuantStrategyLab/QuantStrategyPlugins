from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from quant_strategy_plugins.tqqq_market_regime_control_present import (
    PresentError,
    _admit_output_root,
    _revalidate_output_root,
)


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=False)


def _checkout(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    root.mkdir()
    _git("init", "-q", cwd=root)
    (root / ".gitignore").write_text("data/output/\n", encoding="utf-8")
    (root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    _git("add", ".", cwd=root)
    _git("-c", "user.email=t@example.invalid", "-c", "user.name=Test", "commit", "-qm", "base", cwd=root)
    return root


def _identity_error(callable_) -> None:
    with pytest.raises(PresentError) as raised:
        callable_()
    assert raised.value.code == "T2B2_PRODUCER_IDENTITY_INVALID"
    assert raised.value.exit_code == 2


def _input_error(callable_) -> None:
    with pytest.raises(PresentError) as raised:
        callable_()
    assert raised.value.code == "T2B2_PRODUCER_INPUT_INVALID"
    assert raised.value.exit_code == 2


def _payload(as_of: str) -> bytes:
    value = {
        "as_of": as_of, "audit_summary": {}, "arbiter": {}, "canonical_route": "no_action", "component_signals": {},
        "configured_mode": "shadow", "consumption_policy": {"plugin": "market_regime_control", "strategy": "tqqq_growth_income", "position_control_allowed": True, "evidence_status": "automation_approved"},
        "effective_mode": "shadow", "execution_controls": {}, "generated_at": "2026-01-01T00:00:00Z", "localized_messages": {},
        "log_record": {}, "mode": "shadow", "notification": {}, "plugin": "market_regime_control", "position_control": {},
        "profile": "market_regime_control", "schema_version": "market_regime_control.v1", "strategy": "tqqq_growth_income",
        "strategy_policy": "levered_growth_income_v1", "suggested_action": "no_action", "target_type": "strategy", "would_trade_if_enabled": False,
    }
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


def _capture_checkout(
    tmp_path: Path,
    *,
    inside_checkout: bool = False,
    output_dir: object | None = None,
    extra_config: str = "",
) -> tuple[Path, Path, str, Path]:
    checkout = _checkout(tmp_path)
    expected_output_dir = checkout / "data" / "output" / "packages" if inside_checkout else tmp_path / "external" / "packages"
    configured_output_dir = expected_output_dir if output_dir is None else output_dir
    (checkout / "src" / "quant_strategy_plugins").mkdir(parents=True)
    (checkout / "src" / "quant_strategy_plugins" / "tqqq_market_regime_control_present.py").write_text("# tracked\n", encoding="utf-8")
    prices = checkout / "prices.csv"
    prices.write_text("symbol,as_of,close\nQQQ,2026-01-02,1\n", encoding="utf-8")
    config = checkout / "config.toml"
    config.write_text(
        "[[strategy_plugins]]\nstrategy = 'tqqq_growth_income'\nplugin = 'market_regime_control'\nenabled = true\nmode = 'shadow'\n"
        f"[strategy_plugins.inputs]\nprices = {json.dumps(str(prices))}\n[strategy_plugins.outputs]\n"
        f"output_dir = {json.dumps(str(configured_output_dir)) if isinstance(configured_output_dir, Path) else json.dumps(configured_output_dir)}\n{extra_config}",
        encoding="utf-8",
    )
    _git("add", ".", cwd=checkout)
    _git("-c", "user.email=t@example.invalid", "-c", "user.name=Test", "commit", "-qm", "capture", cwd=checkout)
    return checkout, config, _git("rev-parse", "HEAD", cwd=checkout).stdout.strip(), expected_output_dir


def _fake_producer(counter: list[int]):
    def run(config: dict[str, object], default_mode: str) -> None:
        counter.append(1)
        assert default_mode == "shadow"
        output = Path(str(config["output_dir"]))
        (output / "signals").mkdir(parents=True)
        payload = _payload(str(config["as_of"]))
        (output / "signals" / f"{config['as_of']}.json").write_bytes(payload)
        (output / "latest_signal.json").write_bytes(payload)

    return run


def _capture(subject, checkout: Path, config: Path, expected: str, monkeypatch: pytest.MonkeyPatch, as_of: str = "2026-01-02"):
    monkeypatch.chdir(checkout)
    monkeypatch.setattr(subject, "__file__", checkout / "src" / "quant_strategy_plugins" / "tqqq_market_regime_control_present.py")
    return subject.capture_tqqq_market_regime_control_present(
        config_path=config, as_of=as_of, session_id=f"XNAS:{as_of}", expected_qsp_commit_sha=expected
    )


def test_outside_checkout_root_is_admitted_without_creation(tmp_path: Path) -> None:
    checkout = _checkout(tmp_path)
    destination = tmp_path / "external" / "packages"

    admitted = _admit_output_root(checkout, destination)

    assert admitted.canonical == destination.resolve()
    assert admitted.inside_checkout is False
    assert not destination.exists()


def test_ignored_in_checkout_root_is_admitted_without_creation(tmp_path: Path) -> None:
    checkout = _checkout(tmp_path)
    destination = checkout / "data" / "output" / "unique" / "packages"
    relative = destination.relative_to(checkout).as_posix() + "/"
    assert _git("check-ignore", "--quiet", "--no-index", "--", relative, cwd=checkout).returncode == 0

    admitted = _admit_output_root(checkout, destination)

    assert admitted.canonical == destination.resolve()
    assert admitted.inside_checkout is True
    assert not destination.exists()


def test_unignored_in_checkout_root_fails_before_side_effects(tmp_path: Path) -> None:
    checkout = _checkout(tmp_path)
    destination = checkout / "unignored" / "packages"
    before = _git("status", "--porcelain=v1", "-z", "--untracked-files=all", cwd=checkout).stdout

    _identity_error(lambda: _admit_output_root(checkout, destination))

    assert not destination.exists()
    assert _git("status", "--porcelain=v1", "-z", "--untracked-files=all", cwd=checkout).stdout == before


def test_existing_unignored_directory_is_unchanged(tmp_path: Path) -> None:
    checkout = _checkout(tmp_path)
    destination = checkout / "unignored"
    destination.mkdir()
    marker = destination / "marker.txt"
    marker.write_bytes(b"unchanged")

    _identity_error(lambda: _admit_output_root(checkout, destination))

    assert marker.read_bytes() == b"unchanged"


def test_direct_symlink_and_alias_to_unignored_root_are_rejected(tmp_path: Path) -> None:
    checkout = _checkout(tmp_path)
    target = checkout / "unignored-target"
    target.mkdir()
    direct = tmp_path / "direct"
    direct.symlink_to(target, target_is_directory=True)
    alias = tmp_path / "alias-parent"
    alias.symlink_to(checkout, target_is_directory=True)

    _identity_error(lambda: _admit_output_root(checkout, direct))
    _identity_error(lambda: _admit_output_root(checkout, alias / "unignored-target"))


def test_non_directory_and_git_ignore_error_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    checkout = _checkout(tmp_path)
    file_root = tmp_path / "file-root"
    file_root.write_text("x", encoding="utf-8")
    _identity_error(lambda: _admit_output_root(checkout, file_root))

    import quant_strategy_plugins.tqqq_market_regime_control_present as subject

    monkeypatch.setattr(subject, "_git_returncode", lambda *args, **kwargs: 128)
    _identity_error(lambda: _admit_output_root(checkout, checkout / "data" / "output" / "x"))


def test_prepublication_root_drift_fails_without_publication(tmp_path: Path) -> None:
    checkout = _checkout(tmp_path)
    destination = tmp_path / "external"
    destination.mkdir()
    admitted = _admit_output_root(checkout, destination)
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    destination.rmdir()
    destination.symlink_to(replacement, target_is_directory=True)

    _identity_error(lambda: _revalidate_output_root(admitted))


@pytest.mark.parametrize("inside_checkout", [False, True])
def test_capture_succeeds_once_with_clean_source_and_admitted_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, inside_checkout: bool
) -> None:
    import quant_strategy_plugins.tqqq_market_regime_control_present as subject

    checkout, config, expected, _ = _capture_checkout(tmp_path, inside_checkout=inside_checkout)
    calls: list[int] = []
    monkeypatch.setattr(subject, "run_market_regime_control_plugin", _fake_producer(calls))

    package, digest = _capture(subject, checkout, config, expected, monkeypatch)

    assert calls == [1]
    assert package.is_file()
    assert package.name.endswith(f"-{digest}.json")
    assert _git("status", "--porcelain=v1", "-z", "--untracked-files=all", cwd=checkout).stdout == ""


def test_second_nonconflicting_package_keeps_strict_source_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import quant_strategy_plugins.tqqq_market_regime_control_present as subject

    checkout, config, expected, _ = _capture_checkout(tmp_path, inside_checkout=True)
    calls: list[int] = []
    monkeypatch.setattr(subject, "run_market_regime_control_plugin", _fake_producer(calls))
    first, _ = _capture(subject, checkout, config, expected, monkeypatch)
    second, _ = _capture(subject, checkout, config, expected, monkeypatch, as_of="2026-01-03")

    assert first != second
    assert first.is_file()
    assert second.is_file()
    assert calls == [1, 1]
    assert _git("status", "--porcelain=v1", "-z", "--untracked-files=all", cwd=checkout).stdout == ""


@pytest.mark.parametrize("dirt", ["tracked", "untracked"])
def test_unrelated_dirt_fails_before_output_admission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dirt: str) -> None:
    import quant_strategy_plugins.tqqq_market_regime_control_present as subject

    checkout, config, expected, checkout_output = _capture_checkout(tmp_path)
    if dirt == "tracked":
        (checkout / "tracked.txt").write_text("changed\n", encoding="utf-8")
    else:
        (checkout / "untracked.txt").write_text("dirt\n", encoding="utf-8")
    calls: list[int] = []
    monkeypatch.setattr(subject, "run_market_regime_control_plugin", _fake_producer(calls))

    _identity_error(lambda: _capture(subject, checkout, config, expected, monkeypatch))

    assert calls == []
    assert not checkout_output.exists()


def test_nested_sensitive_config_key_fails_before_producer_or_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import quant_strategy_plugins.tqqq_market_regime_control_present as subject

    sensitive_value = "do-not-package-this"
    checkout, config, expected, checkout_output = _capture_checkout(
        tmp_path,
        extra_config=f"[strategy_plugins.settings.audit]\napi_token = {sensitive_value!r}\n",
    )
    calls: list[int] = []
    monkeypatch.setattr(subject, "run_market_regime_control_plugin", _fake_producer(calls))

    _input_error(lambda: _capture(subject, checkout, config, expected, monkeypatch))

    captured = capsys.readouterr()
    assert calls == []
    assert not checkout_output.exists()
    assert sensitive_value not in captured.out
    assert sensitive_value not in captured.err


def test_non_string_output_dir_fails_as_input_before_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import quant_strategy_plugins.tqqq_market_regime_control_present as subject

    checkout, config, expected, checkout_output = _capture_checkout(tmp_path, output_dir=7)
    calls: list[int] = []
    monkeypatch.setattr(subject, "run_market_regime_control_plugin", _fake_producer(calls))

    _input_error(lambda: _capture(subject, checkout, config, expected, monkeypatch))

    assert calls == []
    assert not checkout_output.exists()
