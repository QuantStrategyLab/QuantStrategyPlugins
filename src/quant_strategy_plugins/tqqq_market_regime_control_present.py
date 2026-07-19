from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import tomllib
from typing import Mapping

from .strategy_plugin_runner import run_market_regime_control_plugin


ERROR_IDENTITY = "T2B2_PRODUCER_IDENTITY_INVALID"
ERROR_INPUT = "T2B2_PRODUCER_INPUT_INVALID"
ERROR_ARTIFACT = "T2B2_PRODUCER_ARTIFACT_INVALID"
ERROR_PUBLISH = "T2B2_PRODUCER_PUBLISH_FAILED"
SCHEMA = "qsl.tqqq_market_regime_control_present.v1"
ENTRYPOINT = "quant_strategy_plugins.strategy_plugin_runner:run_market_regime_control_plugin"
REPOSITORY = "QuantStrategyLab/QuantStrategyPlugins"
SUBJECT = {"strategy": "tqqq_growth_income", "plugin": "market_regime_control", "mode": "shadow"}
PAYLOAD_KEYS = {
    "as_of", "audit_summary", "arbiter", "canonical_route", "component_signals", "configured_mode",
    "consumption_policy", "effective_mode", "execution_controls", "generated_at", "localized_messages",
    "log_record", "mode", "notification", "plugin", "position_control", "profile", "schema_version",
    "strategy", "strategy_policy", "suggested_action", "target_type", "would_trade_if_enabled",
}
SENSITIVE_KEY_PARTS = ("token", "secret", "password", "cookie", "jwt", "api_key")


class PresentError(RuntimeError):
    def __init__(self, code: str, exit_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.exit_code = exit_code


@dataclass(frozen=True)
class OutputRoot:
    checkout: Path
    canonical: Path
    inside_checkout: bool


def _fail(code: str, exit_code: int) -> None:
    raise PresentError(code, exit_code)


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _no_nonfinite(value: str) -> object:
    raise ValueError(f"non-finite JSON constant: {value}")


def _strict_json(raw: bytes) -> object:
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_no_nonfinite)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid JSON") from exc


def _is_sha(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _is_commit(value: object) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(char in "0123456789abcdef" for char in value)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _git_returncode(*args: str, cwd: Path) -> int:
    return subprocess.run(["git", *args], cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode


def _git_output(*args: str, cwd: Path) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True, stderr=subprocess.DEVNULL).strip()


def _contains(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _git_admin_roots(checkout: Path) -> tuple[Path, Path]:
    try:
        git_dir = Path(_git_output("rev-parse", "--path-format=absolute", "--git-dir", cwd=checkout)).resolve(strict=True)
        common_dir = Path(_git_output("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=checkout)).resolve(strict=True)
    except (OSError, subprocess.CalledProcessError):
        _fail(ERROR_IDENTITY, 2)
    return git_dir, common_dir


def _prove_ignored(checkout: Path, canonical: Path) -> None:
    try:
        relative = canonical.relative_to(checkout).as_posix()
    except ValueError:
        _fail(ERROR_IDENTITY, 2)
    if not relative or relative == ".":
        _fail(ERROR_IDENTITY, 2)
    if _git_returncode("check-ignore", "--quiet", "--no-index", "--", f"{relative}/", cwd=checkout) != 0:
        _fail(ERROR_IDENTITY, 2)


def _admit_output_root(checkout: Path, output_dir: str | Path) -> OutputRoot:
    """Classify the root without creating or mutating it."""
    try:
        resolved_checkout = checkout.resolve(strict=True)
        lexical = Path(output_dir)
        if not lexical.is_absolute():
            lexical = resolved_checkout / lexical
        if lexical.is_symlink():
            _fail(ERROR_IDENTITY, 2)
        canonical = lexical.resolve(strict=False)
    except (OSError, RuntimeError):
        _fail(ERROR_IDENTITY, 2)
    if canonical == resolved_checkout:
        _fail(ERROR_IDENTITY, 2)
    git_dir, common_dir = _git_admin_roots(resolved_checkout)
    if _contains(git_dir, canonical) or _contains(common_dir, canonical):
        _fail(ERROR_IDENTITY, 2)
    if canonical.exists() and (canonical.is_symlink() or not canonical.is_dir()):
        _fail(ERROR_IDENTITY, 2)
    inside = _contains(resolved_checkout, canonical)
    if inside:
        _prove_ignored(resolved_checkout, canonical)
    return OutputRoot(checkout=resolved_checkout, canonical=canonical, inside_checkout=inside)


def _revalidate_output_root(root: OutputRoot) -> None:
    try:
        if root.canonical.is_symlink() or not root.canonical.is_dir():
            _fail(ERROR_IDENTITY, 2)
        if root.canonical.resolve(strict=True) != root.canonical:
            _fail(ERROR_IDENTITY, 2)
    except (OSError, RuntimeError):
        _fail(ERROR_IDENTITY, 2)
    if root.inside_checkout:
        _prove_ignored(root.checkout, root.canonical)


def _source_identity(expected_qsp_commit_sha: str) -> Path:
    if not _is_commit(expected_qsp_commit_sha):
        _fail(ERROR_IDENTITY, 2)
    try:
        checkout = Path(_git_output("rev-parse", "--show-toplevel", cwd=Path.cwd())).resolve(strict=True)
        if Path.cwd().resolve(strict=True) != checkout:
            _fail(ERROR_IDENTITY, 2)
        module = Path(__file__).resolve(strict=True).relative_to(checkout).as_posix()
        if _git_returncode("ls-files", "--error-unmatch", "--", module, cwd=checkout) != 0:
            _fail(ERROR_IDENTITY, 2)
        status = subprocess.check_output(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"], cwd=checkout
        )
        if status or _git_output("rev-parse", "HEAD", cwd=checkout) != expected_qsp_commit_sha:
            _fail(ERROR_IDENTITY, 2)
        return checkout
    except (OSError, RuntimeError, subprocess.CalledProcessError):
        _fail(ERROR_IDENTITY, 2)


def _regular_csv(path_value: object) -> Path:
    try:
        path = Path(str(path_value)).resolve(strict=True)
        if path.is_symlink() or path.suffix.lower() != ".csv" or not stat.S_ISREG(path.stat().st_mode):
            _fail(ERROR_INPUT, 2)
        return path
    except (OSError, RuntimeError):
        _fail(ERROR_INPUT, 2)


def _flatten(entry: Mapping[str, object]) -> dict[str, object]:
    flattened = {key: value for key, value in entry.items() if key not in {"inputs", "outputs", "settings"}}
    for section in ("inputs", "outputs", "settings"):
        nested = entry.get(section, {})
        if nested is None:
            continue
        if not isinstance(nested, Mapping) or set(flattened).intersection(nested):
            _fail(ERROR_INPUT, 2)
        flattened.update(nested)
    return flattened


def _sensitive_key(key: object) -> bool:
    lowered = str(key).lower()
    return lowered.startswith("ai_audit_") or any(part in lowered for part in SENSITIVE_KEY_PARTS)


def _contains_sensitive_key(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(_sensitive_key(key) or _contains_sensitive_key(child) for key, child in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_sensitive_key(child) for child in value)
    return False


def _select_config(config_path: Path, as_of: str) -> tuple[dict[str, object], Path, Path | None, str | Path]:
    try:
        document = tomllib.loads(config_path.read_text(encoding="utf-8"))
        entries = document["strategy_plugins"]
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, KeyError):
        _fail(ERROR_INPUT, 2)
    if not isinstance(entries, list):
        _fail(ERROR_INPUT, 2)
    candidates: list[dict[str, object]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        flattened = _flatten(entry)
        if flattened.get("strategy") == SUBJECT["strategy"] and flattened.get("plugin") == SUBJECT["plugin"]:
            candidates.append(flattened)
    if len(candidates) != 1:
        _fail(ERROR_INPUT, 2)
    selected = candidates[0]
    if selected.get("enabled") is not True or selected.get("mode", document.get("default_mode")) != "shadow":
        _fail(ERROR_INPUT, 2)
    if _contains_sensitive_key(selected):
        _fail(ERROR_INPUT, 2)
    configured_as_of = selected.get("as_of")
    if configured_as_of is not None and configured_as_of != as_of:
        _fail(ERROR_INPUT, 2)
    if "prices" not in selected or not isinstance(selected.get("output_dir"), str):
        _fail(ERROR_INPUT, 2)
    prices = _regular_csv(selected["prices"])
    external = None if not selected.get("external_context") else _regular_csv(selected["external_context"])
    return selected, prices, external, selected["output_dir"]


def _input_identity(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    return {"format": "csv", "sha256": _sha256(raw), "size_bytes": len(raw)}


def _validate_payload(raw: bytes, as_of: str) -> dict[str, object]:
    try:
        payload = _strict_json(raw)
    except ValueError:
        _fail(ERROR_ARTIFACT, 3)
    if not isinstance(payload, dict) or set(payload) != PAYLOAD_KEYS:
        _fail(ERROR_ARTIFACT, 3)
    fixed = {
        "schema_version": "market_regime_control.v1", "profile": "market_regime_control", "strategy": SUBJECT["strategy"],
        "plugin": SUBJECT["plugin"], "target_type": "strategy", "mode": "shadow", "configured_mode": "shadow",
        "effective_mode": "shadow", "as_of": as_of,
    }
    if any(payload.get(key) != value for key, value in fixed.items()):
        _fail(ERROR_ARTIFACT, 3)
    policy = payload.get("consumption_policy")
    if not isinstance(policy, dict) or policy.get("plugin") != SUBJECT["plugin"] or policy.get("strategy") != SUBJECT["strategy"]:
        _fail(ERROR_ARTIFACT, 3)
    if policy.get("position_control_allowed") is not True or policy.get("evidence_status") != "automation_approved":
        _fail(ERROR_ARTIFACT, 3)
    return payload


def _package_config(selected: Mapping[str, object], as_of: str) -> dict[str, object]:
    value = dict(selected)
    value.update({"strategy": SUBJECT["strategy"], "plugin": SUBJECT["plugin"], "enabled": True, "mode": "shadow", "as_of": as_of})
    value.pop("output_dir", None)
    value["prices"] = "@input:prices"
    if "external_context" in value:
        value["external_context"] = "@input:external_context"
    try:
        canonical = _canonical_json(value)
    except (TypeError, ValueError):
        _fail(ERROR_INPUT, 2)
    return {"sha256": _sha256(canonical), "value": value}


def _build_package(
    *, selected: Mapping[str, object], prices: Path, external: Path | None, payload_raw: bytes, as_of: str, session_id: str,
    expected_qsp_commit_sha: str,
) -> bytes:
    inputs: dict[str, object] = {"prices": _input_identity(prices)}
    inputs["external_context"] = {"status": "ABSENT"} if external is None else {"status": "PRESENT", **_input_identity(external)}
    package = {
        "as_of": as_of, "config": _package_config(selected, as_of), "inputs": inputs,
        "payload": {"bytes_b64": base64.b64encode(payload_raw).decode("ascii"), "schema_version": "market_regime_control.v1", "sha256": _sha256(payload_raw), "size_bytes": len(payload_raw)},
        "producer": {"commit_sha": expected_qsp_commit_sha, "entrypoint": ENTRYPOINT, "repository": REPOSITORY},
        "schema": SCHEMA, "session_id": session_id, "status": "PRESENT", "subject": SUBJECT,
    }
    return _canonical_json(package)


def _readback_package(path: Path, expected_qsp_commit_sha: str) -> None:
    try:
        if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
            _fail(ERROR_PUBLISH, 4)
        raw = path.read_bytes()
        package = _strict_json(raw)
        if not isinstance(package, dict) or set(package) != {"as_of", "config", "inputs", "payload", "producer", "schema", "session_id", "status", "subject"}:
            _fail(ERROR_PUBLISH, 4)
        if _canonical_json(package) != raw or package.get("schema") != SCHEMA or package.get("status") != "PRESENT":
            _fail(ERROR_PUBLISH, 4)
        if package.get("subject") != SUBJECT or package.get("session_id") != f"XNAS:{package.get('as_of')}":
            _fail(ERROR_PUBLISH, 4)
        producer = package.get("producer")
        config = package.get("config")
        inputs = package.get("inputs")
        payload = package.get("payload")
        if not isinstance(producer, dict) or producer != {"commit_sha": expected_qsp_commit_sha, "entrypoint": ENTRYPOINT, "repository": REPOSITORY}:
            _fail(ERROR_PUBLISH, 4)
        if not isinstance(config, dict) or set(config) != {"sha256", "value"} or _sha256(_canonical_json(config["value"])) != config["sha256"]:
            _fail(ERROR_PUBLISH, 4)
        if not isinstance(inputs, dict) or set(inputs) != {"prices", "external_context"} or not isinstance(payload, dict):
            _fail(ERROR_PUBLISH, 4)
        encoded = payload.get("bytes_b64")
        if not isinstance(encoded, str):
            _fail(ERROR_PUBLISH, 4)
        decoded = base64.b64decode(encoded.encode("ascii"), validate=True)
        if payload.get("sha256") != _sha256(decoded) or payload.get("size_bytes") != len(decoded):
            _fail(ERROR_PUBLISH, 4)
        _validate_payload(decoded, str(package["as_of"]))
    except (OSError, ValueError, TypeError, KeyError):
        _fail(ERROR_PUBLISH, 4)


def capture_tqqq_market_regime_control_present(
    *, config_path: str | Path, as_of: str, session_id: str, expected_qsp_commit_sha: str,
) -> tuple[Path, str]:
    try:
        date.fromisoformat(as_of)
    except (TypeError, ValueError):
        _fail(ERROR_INPUT, 2)
    if session_id != f"XNAS:{as_of}":
        _fail(ERROR_INPUT, 2)
    checkout = _source_identity(expected_qsp_commit_sha)
    selected, prices, external, output_dir = _select_config(Path(config_path), as_of)
    root = _admit_output_root(checkout, output_dir)
    try:
        root.canonical.mkdir(parents=True, exist_ok=True)
        _revalidate_output_root(root)
        stage = Path(tempfile.mkdtemp(prefix=".tqqq-market-regime-control-present-", dir=root.canonical))
    except (OSError, RuntimeError):
        _fail(ERROR_PUBLISH, 4)
    published = False
    try:
        staged_prices = stage / "prices.csv"
        shutil.copyfile(prices, staged_prices)
        staged_external = None
        if external is not None:
            staged_external = stage / "external_context.csv"
            shutil.copyfile(external, staged_external)
        runner_config = dict(selected)
        runner_config.update({"prices": str(staged_prices), "output_dir": str(stage / "producer-output"), "as_of": as_of})
        if staged_external is not None:
            runner_config["external_context"] = str(staged_external)
        run_market_regime_control_plugin(runner_config, "shadow")
        dated = stage / "producer-output" / "signals" / f"{as_of}.json"
        latest = stage / "producer-output" / "latest_signal.json"
        if not dated.is_file() or dated.is_symlink() or not latest.is_file() or latest.is_symlink():
            _fail(ERROR_ARTIFACT, 3)
        payload_raw = dated.read_bytes()
        if payload_raw != latest.read_bytes():
            _fail(ERROR_ARTIFACT, 3)
        _validate_payload(payload_raw, as_of)
        package_raw = _build_package(selected=selected, prices=staged_prices, external=staged_external, payload_raw=payload_raw, as_of=as_of, session_id=session_id, expected_qsp_commit_sha=expected_qsp_commit_sha)
        digest = _sha256(package_raw)
        final = root.canonical / f"tqqq-market-regime-control-present-{as_of}-{digest}.json"
        if final.exists() or final.is_symlink():
            _fail(ERROR_PUBLISH, 4)
        staged_package = stage / "package.json"
        staged_package.write_bytes(package_raw)
        _readback_package(staged_package, expected_qsp_commit_sha)
        _readback_package(staged_package, expected_qsp_commit_sha)
        _revalidate_output_root(root)
        _source_identity(expected_qsp_commit_sha)
        shutil.rmtree(stage / "producer-output")
        if (stage / "producer-output").exists():
            _fail(ERROR_PUBLISH, 4)
        os.replace(staged_package, final)
        published = True
        return final, digest
    except PresentError:
        raise
    except (OSError, ValueError, subprocess.SubprocessError):
        _fail(ERROR_PUBLISH, 4)
    finally:
        if not published:
            shutil.rmtree(stage, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--expected-qsp-commit-sha", required=True)
    try:
        args = parser.parse_args(argv)
        package, digest = capture_tqqq_market_regime_control_present(
            config_path=args.config, as_of=args.as_of, session_id=args.session_id,
            expected_qsp_commit_sha=args.expected_qsp_commit_sha,
        )
    except PresentError as exc:
        print(f"ERROR {exc.code}", file=os.sys.stderr)
        return exc.exit_code
    print(f"{package} {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
