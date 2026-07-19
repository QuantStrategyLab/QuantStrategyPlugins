from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from datetime import date
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Mapping

from .strategy_plugin_runner import _flatten_strategy_plugin_entry, load_plugin_config, run_market_regime_control_plugin


SCHEMA = "qsl.tqqq_market_regime_control_present.v1"
PRODUCER_ENTRYPOINT = "quant_strategy_plugins.strategy_plugin_runner:run_market_regime_control_plugin"
PRODUCER_REPOSITORY = "QuantStrategyLab/QuantStrategyPlugins"
STRATEGY = "tqqq_growth_income"
PLUGIN = "market_regime_control"
MODE = "shadow"
_COMMIT_HEX = frozenset("0123456789abcdef")
_FORBIDDEN_KEY_PARTS = ("token", "secret", "password", "cookie", "jwt", "api_key")
_PAYLOAD_KEYS = {
    "as_of",
    "audit_summary",
    "arbiter",
    "canonical_route",
    "component_signals",
    "configured_mode",
    "consumption_policy",
    "effective_mode",
    "execution_controls",
    "generated_at",
    "localized_messages",
    "log_record",
    "mode",
    "notification",
    "plugin",
    "position_control",
    "profile",
    "schema_version",
    "strategy",
    "strategy_policy",
    "suggested_action",
    "target_type",
    "would_trade_if_enabled",
}


class PresentPackageError(RuntimeError):
    def __init__(self, code: str, exit_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.exit_code = exit_code


@dataclass(frozen=True)
class PublishedPackage:
    path: Path
    sha256: str


def _fail(code: str, exit_code: int) -> None:
    raise PresentPackageError(code, exit_code)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _strict_json(raw: bytes, *, code: str, exit_code: int) -> Any:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                _fail(code, exit_code)
            result[key] = value
        return result

    try:
        text = raw.decode("utf-8")
        return json.loads(
            text,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=lambda _value: _fail(code, exit_code),
        )
    except (UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError):
        _fail(code, exit_code)


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _COMMIT_HEX


def _is_commit_sha(value: object) -> bool:
    return isinstance(value, str) and len(value) == 40 and set(value) <= _COMMIT_HEX


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _require_mapping(value: object, *, code: str, exit_code: int) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        _fail(code, exit_code)
    return value


def _require_exact_keys(value: object, keys: set[str], *, code: str, exit_code: int) -> dict[str, Any]:
    mapping = _require_mapping(value, code=code, exit_code=exit_code)
    if set(mapping) != keys:
        _fail(code, exit_code)
    return mapping


def _validate_json_value(value: Any, *, code: str, exit_code: int) -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if _is_int(value):
        return
    if isinstance(value, float):
        if math.isfinite(value):
            return
        _fail(code, exit_code)
    if isinstance(value, list):
        for child in value:
            _validate_json_value(child, code=code, exit_code=exit_code)
        return
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                _fail(code, exit_code)
            _validate_json_value(child, code=code, exit_code=exit_code)
        return
    _fail(code, exit_code)


def _reject_sensitive_keys(value: Any, *, code: str, exit_code: int) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = key.lower()
            if lowered.startswith("ai_audit_") or any(part in lowered for part in _FORBIDDEN_KEY_PARTS):
                _fail(code, exit_code)
            _reject_sensitive_keys(child, code=code, exit_code=exit_code)
    elif isinstance(value, list):
        for child in value:
            _reject_sensitive_keys(child, code=code, exit_code=exit_code)


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL).strip()


def _only_private_stage_is_dirty(root: Path, status: str, private_stage: Path) -> bool:
    try:
        relative_stage = private_stage.resolve().relative_to(root).as_posix()
    except ValueError:
        return False
    if not private_stage.name.startswith(".tqqq-market-regime-control-present-"):
        return False
    for record in filter(None, status.split("\0")):
        if len(record) < 4 or record[:2] != "??":
            return False
        path = record[3:]
        if path != relative_stage and not path.startswith(f"{relative_stage}/"):
            return False
    return bool(status)


def _verify_source_identity(expected_qsp_commit_sha: str, *, private_stage: Path | None = None) -> None:
    if not _is_commit_sha(expected_qsp_commit_sha):
        _fail("T2B2_PRODUCER_IDENTITY_INVALID", 2)
    try:
        root = Path(_git("rev-parse", "--show-toplevel")).resolve()
        if Path.cwd().resolve() != root:
            _fail("T2B2_PRODUCER_IDENTITY_INVALID", 2)
        module_path = Path(__file__).resolve()
        relative_module = module_path.relative_to(root)
        if _git("ls-files", "--error-unmatch", str(relative_module)) != str(relative_module):
            _fail("T2B2_PRODUCER_IDENTITY_INVALID", 2)
        status = _git("status", "--porcelain=v1", "-z", "--untracked-files=all")
        if status and (private_stage is None or not _only_private_stage_is_dirty(root, status, private_stage)):
            _fail("T2B2_PRODUCER_IDENTITY_INVALID", 2)
        if _git("rev-parse", "HEAD") != expected_qsp_commit_sha:
            _fail("T2B2_PRODUCER_IDENTITY_INVALID", 2)
    except (OSError, subprocess.SubprocessError, ValueError):
        _fail("T2B2_PRODUCER_IDENTITY_INVALID", 2)


def _require_iso_date(value: object, *, code: str, exit_code: int) -> str:
    if not isinstance(value, str):
        _fail(code, exit_code)
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        _fail(code, exit_code)
    if parsed.isoformat() != value:
        _fail(code, exit_code)
    return value


def _resolve_input_path(config_path: Path, value: object, *, code: str, exit_code: int) -> Path:
    if not isinstance(value, str) or not value.strip():
        _fail(code, exit_code)
    path = Path(value)
    if not path.is_absolute():
        path = config_path.parent / path
    return path


def _read_regular_csv(path: Path, *, code: str, exit_code: int) -> bytes:
    try:
        if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".csv":
            _fail(code, exit_code)
        return path.read_bytes()
    except OSError:
        _fail(code, exit_code)


def _copy_staged_csv(source: Path, destination: Path) -> tuple[bytes, dict[str, Any]]:
    raw = _read_regular_csv(source, code="T2B2_PRODUCER_INPUT_INVALID", exit_code=2)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(raw)
    return raw, {"format": "csv", "sha256": _sha256(raw), "size_bytes": len(raw)}


def _select_target(config_path: Path, as_of: str, session_id: str) -> tuple[dict[str, Any], str]:
    try:
        config = load_plugin_config(config_path)
        entries = config.get("strategy_plugins")
        if not isinstance(entries, list):
            _fail("T2B2_PRODUCER_INPUT_INVALID", 2)
        matches = []
        for entry in entries:
            if not isinstance(entry, Mapping):
                _fail("T2B2_PRODUCER_INPUT_INVALID", 2)
            flattened = _flatten_strategy_plugin_entry(entry)
            if flattened.get("strategy") == STRATEGY and flattened.get("plugin") == PLUGIN:
                matches.append(flattened)
        if len(matches) != 1:
            _fail("T2B2_PRODUCER_INPUT_INVALID", 2)
        target = matches[0]
        if target.get("enabled") is not True:
            _fail("T2B2_PRODUCER_INPUT_INVALID", 2)
        mode = target.get("mode", config.get("default_mode"))
        if mode != MODE:
            _fail("T2B2_PRODUCER_INPUT_INVALID", 2)
        if target.get("as_of") != as_of or session_id != f"XNAS:{as_of}":
            _fail("T2B2_PRODUCER_INPUT_INVALID", 2)
        _reject_sensitive_keys(target, code="T2B2_PRODUCER_INPUT_INVALID", exit_code=2)
        _validate_json_value(target, code="T2B2_PRODUCER_INPUT_INVALID", exit_code=2)
        return target, MODE
    except PresentPackageError:
        raise
    except (OSError, TypeError, ValueError):
        _fail("T2B2_PRODUCER_INPUT_INVALID", 2)


def _validate_payload(raw: bytes, *, as_of: str, code: str, exit_code: int) -> None:
    payload = _require_exact_keys(_strict_json(raw, code=code, exit_code=exit_code), _PAYLOAD_KEYS, code=code, exit_code=exit_code)
    _validate_json_value(payload, code=code, exit_code=exit_code)
    if (
        payload["schema_version"] != "market_regime_control.v1"
        or payload["profile"] != "market_regime_control"
        or payload["strategy"] != STRATEGY
        or payload["plugin"] != PLUGIN
        or payload["target_type"] != "strategy"
        or payload["mode"] != MODE
        or payload["configured_mode"] != MODE
        or payload["effective_mode"] != MODE
        or payload["as_of"] != as_of
    ):
        _fail(code, exit_code)
    consumption_policy = _require_mapping(payload["consumption_policy"], code=code, exit_code=exit_code)
    if (
        consumption_policy.get("plugin") != PLUGIN
        or consumption_policy.get("strategy") != STRATEGY
        or consumption_policy.get("position_control_allowed") is not True
        or consumption_policy.get("evidence_status") != "automation_approved"
    ):
        _fail(code, exit_code)


def _verify_prices_identity(value: object, *, code: str, exit_code: int) -> None:
    mapping = _require_mapping(value, code=code, exit_code=exit_code)
    if set(mapping) != {"format", "sha256", "size_bytes"}:
        _fail(code, exit_code)
    if mapping.get("format") != "csv" or not _is_sha256(mapping.get("sha256")):
        _fail(code, exit_code)
    if not _is_int(mapping.get("size_bytes")) or mapping["size_bytes"] < 0:
        _fail(code, exit_code)


def _verify_external_context_identity(value: object, *, code: str, exit_code: int) -> None:
    mapping = _require_mapping(value, code=code, exit_code=exit_code)
    if mapping.get("status") == "ABSENT":
        if set(mapping) != {"status"}:
            _fail(code, exit_code)
        return
    if set(mapping) != {"status", "format", "sha256", "size_bytes"}:
        _fail(code, exit_code)
    if mapping.get("status") != "PRESENT" or mapping.get("format") != "csv" or not _is_sha256(mapping.get("sha256")):
        _fail(code, exit_code)
    if not _is_int(mapping.get("size_bytes")) or mapping["size_bytes"] < 0:
        _fail(code, exit_code)


def _verify_present_package(raw: bytes, *, expected_qsp_commit_sha: str | None = None) -> dict[str, Any]:
    code = "T2B2_PRODUCER_PUBLISH_FAILED"
    package = _require_exact_keys(
        _strict_json(raw, code=code, exit_code=4),
        {"as_of", "config", "inputs", "payload", "producer", "schema", "session_id", "status", "subject"},
        code=code,
        exit_code=4,
    )
    _validate_json_value(package, code=code, exit_code=4)
    if raw != _canonical_json(package):
        _fail(code, 4)
    as_of = _require_iso_date(package["as_of"], code=code, exit_code=4)
    if package["schema"] != SCHEMA or package["status"] != "PRESENT" or package["session_id"] != f"XNAS:{as_of}":
        _fail(code, 4)
    subject = _require_exact_keys(package["subject"], {"mode", "plugin", "strategy"}, code=code, exit_code=4)
    if subject != {"mode": MODE, "plugin": PLUGIN, "strategy": STRATEGY}:
        _fail(code, 4)
    producer = _require_exact_keys(package["producer"], {"commit_sha", "entrypoint", "repository"}, code=code, exit_code=4)
    if (
        not _is_commit_sha(producer["commit_sha"])
        or producer["entrypoint"] != PRODUCER_ENTRYPOINT
        or producer["repository"] != PRODUCER_REPOSITORY
        or (expected_qsp_commit_sha is not None and producer["commit_sha"] != expected_qsp_commit_sha)
    ):
        _fail(code, 4)
    config = _require_exact_keys(package["config"], {"sha256", "value"}, code=code, exit_code=4)
    value = _require_mapping(config["value"], code=code, exit_code=4)
    _reject_sensitive_keys(value, code=code, exit_code=4)
    if (
        not _is_sha256(config["sha256"])
        or config["sha256"] != _sha256(_canonical_json(value))
        or value.get("strategy") != STRATEGY
        or value.get("plugin") != PLUGIN
        or value.get("enabled") is not True
        or value.get("mode") != MODE
        or value.get("as_of") != as_of
        or value.get("prices") != "@input:prices"
    ):
        _fail(code, 4)
    inputs = _require_exact_keys(package["inputs"], {"external_context", "prices"}, code=code, exit_code=4)
    _verify_prices_identity(inputs["prices"], code=code, exit_code=4)
    _verify_external_context_identity(inputs["external_context"], code=code, exit_code=4)
    payload = _require_exact_keys(package["payload"], {"bytes_b64", "schema_version", "sha256", "size_bytes"}, code=code, exit_code=4)
    if (
        not isinstance(payload["bytes_b64"], str)
        or payload["schema_version"] != "market_regime_control.v1"
        or not _is_sha256(payload["sha256"])
        or not _is_int(payload["size_bytes"])
        or payload["size_bytes"] < 0
    ):
        _fail(code, 4)
    try:
        payload_bytes = base64.b64decode(payload["bytes_b64"], validate=True)
    except (ValueError, TypeError):
        _fail(code, 4)
    if _sha256(payload_bytes) != payload["sha256"] or len(payload_bytes) != payload["size_bytes"]:
        _fail(code, 4)
    _validate_payload(payload_bytes, as_of=as_of, code=code, exit_code=4)
    return package


def _readback_package(path: Path, *, expected_qsp_commit_sha: str) -> None:
    try:
        if path.is_symlink() or not path.is_file():
            _fail("T2B2_PRODUCER_PUBLISH_FAILED", 4)
        _verify_present_package(path.read_bytes(), expected_qsp_commit_sha=expected_qsp_commit_sha)
    except OSError:
        _fail("T2B2_PRODUCER_PUBLISH_FAILED", 4)


def capture_tqqq_market_regime_control_present(
    *,
    config_path: str | Path,
    output_dir: str | Path,
    expected_qsp_commit_sha: str,
    as_of: str,
    session_id: str,
) -> PublishedPackage:
    as_of = _require_iso_date(as_of, code="T2B2_PRODUCER_INPUT_INVALID", exit_code=2)
    _verify_source_identity(expected_qsp_commit_sha)
    config_path = Path(config_path)
    if config_path.is_symlink() or not config_path.is_file():
        _fail("T2B2_PRODUCER_INPUT_INVALID", 2)
    config_path = config_path.resolve()
    target, default_mode = _select_target(config_path, as_of, session_id)
    prices_source = _resolve_input_path(config_path, target.get("prices"), code="T2B2_PRODUCER_INPUT_INVALID", exit_code=2)
    external_source = (
        _resolve_input_path(config_path, target["external_context"], code="T2B2_PRODUCER_INPUT_INVALID", exit_code=2)
        if "external_context" in target
        else None
    )
    destination_root = Path(output_dir).resolve()
    try:
        destination_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        _fail("T2B2_PRODUCER_PUBLISH_FAILED", 4)

    with tempfile.TemporaryDirectory(prefix=".tqqq-market-regime-control-present-", dir=destination_root) as temporary:
        stage = Path(temporary)
        staged_prices, prices_identity = _copy_staged_csv(prices_source, stage / "inputs" / "prices.csv")
        external_identity: dict[str, Any] = {"status": "ABSENT"}
        staged_external: bytes | None = None
        if external_source is not None:
            staged_external, external_metadata = _copy_staged_csv(external_source, stage / "inputs" / "external_context.csv")
            external_identity = {"status": "PRESENT", **external_metadata}
        staged_config = dict(target)
        staged_config["prices"] = str(stage / "inputs" / "prices.csv")
        if staged_external is not None:
            staged_config["external_context"] = str(stage / "inputs" / "external_context.csv")
        staged_config["output_dir"] = str(stage / "producer-output")
        try:
            run_market_regime_control_plugin(staged_config, default_mode)
        except PresentPackageError:
            raise
        except Exception:
            _fail("T2B2_PRODUCER_ARTIFACT_INVALID", 3)
        if _read_regular_csv(stage / "inputs" / "prices.csv", code="T2B2_PRODUCER_INPUT_INVALID", exit_code=2) != staged_prices:
            _fail("T2B2_PRODUCER_INPUT_INVALID", 2)
        if staged_external is not None and (
            _read_regular_csv(stage / "inputs" / "external_context.csv", code="T2B2_PRODUCER_INPUT_INVALID", exit_code=2)
            != staged_external
        ):
            _fail("T2B2_PRODUCER_INPUT_INVALID", 2)
        try:
            producer_output = stage / "producer-output"
            dated_payload = _read_regular_file(producer_output / "signals" / f"{as_of}.json")
            latest_payload = _read_regular_file(producer_output / "latest_signal.json")
            if dated_payload != latest_payload:
                _fail("T2B2_PRODUCER_ARTIFACT_INVALID", 3)
            _validate_payload(dated_payload, as_of=as_of, code="T2B2_PRODUCER_ARTIFACT_INVALID", exit_code=3)
        except PresentPackageError:
            raise
        except OSError:
            _fail("T2B2_PRODUCER_ARTIFACT_INVALID", 3)
        config_value = dict(target)
        config_value.pop("output_dir", None)
        config_value["mode"] = MODE
        config_value["prices"] = "@input:prices"
        if "external_context" in config_value:
            config_value["external_context"] = "@input:external_context"
        package = {
            "as_of": as_of,
            "config": {"sha256": _sha256(_canonical_json(config_value)), "value": config_value},
            "inputs": {"external_context": external_identity, "prices": prices_identity},
            "payload": {
                "bytes_b64": base64.b64encode(dated_payload).decode("ascii"),
                "schema_version": "market_regime_control.v1",
                "sha256": _sha256(dated_payload),
                "size_bytes": len(dated_payload),
            },
            "producer": {
                "commit_sha": expected_qsp_commit_sha,
                "entrypoint": PRODUCER_ENTRYPOINT,
                "repository": PRODUCER_REPOSITORY,
            },
            "schema": SCHEMA,
            "session_id": session_id,
            "status": "PRESENT",
            "subject": {"mode": MODE, "plugin": PLUGIN, "strategy": STRATEGY},
        }
        package_bytes = _canonical_json(package)
        staged_package = stage / "package.json"
        try:
            staged_package.write_bytes(package_bytes)
            _readback_package(staged_package, expected_qsp_commit_sha=expected_qsp_commit_sha)
            _readback_package(staged_package, expected_qsp_commit_sha=expected_qsp_commit_sha)
            _verify_source_identity(expected_qsp_commit_sha, private_stage=stage)
            shutil.rmtree(stage / "producer-output")
            if (stage / "producer-output").exists():
                _fail("T2B2_PRODUCER_PUBLISH_FAILED", 4)
            digest = _sha256(package_bytes)
            destination = destination_root / f"tqqq-market-regime-control-present-{as_of}-{digest}.json"
            if destination.exists() or destination.is_symlink():
                _fail("T2B2_PRODUCER_PUBLISH_FAILED", 4)
            os.replace(staged_package, destination)
        except PresentPackageError:
            raise
        except OSError:
            _fail("T2B2_PRODUCER_PUBLISH_FAILED", 4)
    return PublishedPackage(path=destination, sha256=digest)


def _read_regular_file(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        _fail("T2B2_PRODUCER_ARTIFACT_INVALID", 3)
    return path.read_bytes()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture one TQQQ market-regime-control PRESENT package.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--expected-qsp-commit-sha", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--session-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        package = capture_tqqq_market_regime_control_present(
            config_path=args.config,
            output_dir=args.output_dir,
            expected_qsp_commit_sha=args.expected_qsp_commit_sha,
            as_of=args.as_of,
            session_id=args.session_id,
        )
    except PresentPackageError as error:
        print(f"ERROR {error.code}", file=sys.stderr)
        return error.exit_code
    except Exception:
        print("ERROR T2B2_PRODUCER_PUBLISH_FAILED", file=sys.stderr)
        return 70
    print(f"{package.path} {package.sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
