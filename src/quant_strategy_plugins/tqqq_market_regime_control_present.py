from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from datetime import date
from pathlib import Path
from typing import Any, Callable, Mapping


INPUT_INVALID = "T2B2_PRODUCER_INPUT_INVALID"
IDENTITY_INVALID = "T2B2_PRODUCER_IDENTITY_INVALID"
EXECUTION_FAILED = "T2B2_PRODUCER_EXECUTION_FAILED"
ARTIFACT_INVALID = "T2B2_PRODUCER_ARTIFACT_INVALID"
PUBLISH_FAILED = "T2B2_PRODUCER_PUBLISH_FAILED"
UNEXPECTED = "T2B2_PRODUCER_UNEXPECTED"
SCHEMA = "qsl.tqqq_market_regime_control_present.v1"
ENTRYPOINT = "quant_strategy_plugins.strategy_plugin_runner:run_market_regime_control_plugin"
REPOSITORY = "QuantStrategyLab/QuantStrategyPlugins"
STRATEGY = "tqqq_growth_income"
PLUGIN = "market_regime_control"
MODE = "shadow"

REQUIRED_INPUTS = frozenset(
    {
        "attack_symbol", "benchmark_symbol", "credit_pairs", "crisis_enabled", "delever_risk_asset_scalar",
        "event_set", "external_stress_actionable", "financial_symbols", "macro_enabled", "panic_reversal_enabled",
        "prices", "rate_symbols", "realized_vol_requires_confirmation", "realized_vol_threshold", "strategy_policy",
        "taco_enabled", "taco_opportunity_size_scalar", "vix3m_symbols", "vix_symbols",
    }
)
OPTIONAL_INPUTS = frozenset({"external_context"})
RUNNER_KEYS = frozenset({"strategy", "plugin", "enabled", "mode", "as_of", "output_dir"}) | REQUIRED_INPUTS | OPTIONAL_INPUTS
PACKAGE_KEYS = frozenset({"strategy", "plugin", "enabled", "mode", "as_of"}) | REQUIRED_INPUTS | OPTIONAL_INPUTS
SYMBOL_RE = re.compile(r"[A-Z0-9.^_-]{1,24}\Z")
EVENT_SETS = frozenset(
    {
        "first-term", "biden", "second-term", "geopolitical-conflict", "geopolitical-deescalation",
        "geopolitical-conflict-and-deescalation", "full-plus-geopolitical-deescalation",
        "full-plus-geopolitical-conflict-and-deescalation", "full",
    }
)
SENSITIVE_NAMES = (
    "aiaudit", "token", "secret", "password", "passwd", "cookie", "jwt", "apikey", "privatekey",
    "accesskey", "credential", "credentials", "clientsecret", "bearer",
)
PAYLOAD_KEYS = frozenset(
    {
        "as_of", "audit_summary", "arbiter", "canonical_route", "component_signals", "configured_mode",
        "consumption_policy", "effective_mode", "execution_controls", "generated_at", "localized_messages",
        "log_record", "mode", "notification", "plugin", "position_control", "profile", "schema_version",
        "strategy", "strategy_policy", "suggested_action", "target_type", "would_trade_if_enabled",
    }
)


class PresentError(Exception):
    def __init__(self, code: str, exit_code: int) -> None:
        self.code = code
        self.exit_code = exit_code
        super().__init__(code)


def _fail(code: str, exit_code: int) -> None:
    raise PresentError(code, exit_code)


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(("git", *args), cwd=root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    except OSError:
        _fail(IDENTITY_INVALID, 2)


def _source_identity(expected: str) -> Path:
    root_result = _run_git(Path.cwd(), "rev-parse", "--show-toplevel")
    if root_result.returncode != 0:
        _fail(IDENTITY_INVALID, 2)
    try:
        root = Path(root_result.stdout.decode("utf-8").strip()).resolve(strict=True)
        module = Path(__file__).resolve(strict=True)
    except (OSError, UnicodeError):
        _fail(IDENTITY_INVALID, 2)
    if Path.cwd().resolve() != root or root not in module.parents:
        _fail(IDENTITY_INVALID, 2)
    relative_module = module.relative_to(root).as_posix()
    if _run_git(root, "ls-files", "--error-unmatch", "--", relative_module).returncode != 0:
        _fail(IDENTITY_INVALID, 2)
    head = _run_git(root, "rev-parse", "HEAD")
    status = _run_git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if head.returncode != 0 or head.stdout.decode("ascii", "ignore").strip() != expected or status.returncode or status.stdout:
        _fail(IDENTITY_INVALID, 2)
    return root


def _exact_date(value: object) -> str:
    if type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        _fail(INPUT_INVALID, 2)
    try:
        date.fromisoformat(value)
    except ValueError:
        _fail(INPUT_INVALID, 2)
    return value


def _validate_args(as_of: object, session_id: object, expected_commit: object) -> tuple[str, str]:
    normalized_as_of = _exact_date(as_of)
    if type(session_id) is not str or session_id != f"XNAS:{normalized_as_of}":
        _fail(INPUT_INVALID, 2)
    if type(expected_commit) is not str or not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
        _fail(IDENTITY_INVALID, 2)
    return normalized_as_of, expected_commit


def _plain_string(value: object) -> str:
    if type(value) is not str or not value or value != value.strip() or "\0" in value:
        _fail(INPUT_INVALID, 2)
    return value


def _secret_name_walk(value: object) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if type(key) is not str:
                _fail(INPUT_INVALID, 2)
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            if any(name in normalized for name in SENSITIVE_NAMES):
                _fail(INPUT_INVALID, 2)
            _secret_name_walk(nested)
    elif isinstance(value, list):
        for nested in value:
            _secret_name_walk(nested)


def _symbol(value: object) -> str:
    text = _plain_string(value)
    if not SYMBOL_RE.fullmatch(text):
        _fail(INPUT_INVALID, 2)
    return text


def _symbols(value: object, *, pairs: bool = False) -> list[str]:
    if type(value) is not list or not 1 <= len(value) <= 16:
        _fail(INPUT_INVALID, 2)
    result: list[str] = []
    for item in value:
        text = _plain_string(item)
        if pairs:
            pieces = text.split(":")
            if len(pieces) != 2 or not all(SYMBOL_RE.fullmatch(piece) for piece in pieces):
                _fail(INPUT_INVALID, 2)
        elif not SYMBOL_RE.fullmatch(text):
            _fail(INPUT_INVALID, 2)
        if text in result:
            _fail(INPUT_INVALID, 2)
        result.append(text)
    return result


def _ratio(value: object, *, positive: bool = False) -> float:
    if type(value) is not float or not math.isfinite(value) or (positive and value <= 0.0):
        _fail(INPUT_INVALID, 2)
    if not positive and not 0.0 <= value <= 1.0:
        _fail(INPUT_INVALID, 2)
    return value


def _read_config(path: str | Path) -> Mapping[str, object]:
    config_path = Path(path)
    try:
        if config_path.is_symlink() or not config_path.is_file():
            _fail(INPUT_INVALID, 2)
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        _fail(INPUT_INVALID, 2)
    if type(data) is not dict:
        _fail(INPUT_INVALID, 2)
    return data


def _validated_config(document: Mapping[str, object]) -> tuple[dict[str, object], str]:
    if type(document.get("default_mode")) is not str or document["default_mode"] != MODE:
        _fail(INPUT_INVALID, 2)
    entries = document.get("strategy_plugins")
    if type(entries) is not list:
        _fail(INPUT_INVALID, 2)
    selected = [entry for entry in entries if type(entry) is dict and entry.get("strategy") == STRATEGY and entry.get("plugin") == PLUGIN]
    if len(selected) != 1:
        _fail(INPUT_INVALID, 2)
    raw = selected[0]
    _secret_name_walk(raw)
    if set(raw) != {"enabled", "inputs", "outputs", "plugin", "strategy"}:
        _fail(INPUT_INVALID, 2)
    if raw["strategy"] != STRATEGY or raw["plugin"] != PLUGIN or type(raw["enabled"]) is not bool or raw["enabled"] is not True:
        _fail(INPUT_INVALID, 2)
    inputs, outputs = raw["inputs"], raw["outputs"]
    if type(inputs) is not dict or type(outputs) is not dict or set(inputs) not in (REQUIRED_INPUTS, REQUIRED_INPUTS | OPTIONAL_INPUTS):
        _fail(INPUT_INVALID, 2)
    if set(outputs) != {"output_dir"}:
        _fail(INPUT_INVALID, 2)
    validated: dict[str, object] = {
        "attack_symbol": _symbol(inputs["attack_symbol"]),
        "benchmark_symbol": _symbol(inputs["benchmark_symbol"]),
        "credit_pairs": _symbols(inputs["credit_pairs"], pairs=True),
        "crisis_enabled": _bool(inputs["crisis_enabled"]),
        "delever_risk_asset_scalar": _ratio(inputs["delever_risk_asset_scalar"]),
        "event_set": _event_set(inputs["event_set"]),
        "external_stress_actionable": _bool(inputs["external_stress_actionable"]),
        "financial_symbols": _symbols(inputs["financial_symbols"]),
        "macro_enabled": _bool(inputs["macro_enabled"]),
        "panic_reversal_enabled": _bool(inputs["panic_reversal_enabled"]),
        "prices": _csv_path(inputs["prices"]),
        "rate_symbols": _symbols(inputs["rate_symbols"]),
        "realized_vol_requires_confirmation": _bool(inputs["realized_vol_requires_confirmation"]),
        "realized_vol_threshold": _ratio(inputs["realized_vol_threshold"], positive=True),
        "strategy_policy": _policy(inputs["strategy_policy"]),
        "taco_enabled": _bool(inputs["taco_enabled"]),
        "taco_opportunity_size_scalar": _ratio(inputs["taco_opportunity_size_scalar"]),
        "vix3m_symbols": _symbols(inputs["vix3m_symbols"]),
        "vix_symbols": _symbols(inputs["vix_symbols"]),
    }
    if "external_context" in inputs:
        validated["external_context"] = _csv_path(inputs["external_context"])
    return validated, _plain_string(outputs["output_dir"])


def _bool(value: object) -> bool:
    if type(value) is not bool:
        _fail(INPUT_INVALID, 2)
    return value


def _event_set(value: object) -> str:
    text = _plain_string(value)
    if text not in EVENT_SETS:
        _fail(INPUT_INVALID, 2)
    return text


def _policy(value: object) -> str:
    text = _plain_string(value)
    if text != "levered_growth_income_v1":
        _fail(INPUT_INVALID, 2)
    return text


def _csv_path(value: object) -> str:
    text = _plain_string(value)
    if not text.endswith(".csv"):
        _fail(INPUT_INVALID, 2)
    return text


def _admit_output_root(value: str, root: Path) -> Path:
    lexical = Path(value)
    if not lexical.is_absolute():
        lexical = Path.cwd() / lexical
    try:
        if lexical.is_symlink():
            _fail(IDENTITY_INVALID, 2)
        candidate = lexical.resolve(strict=False)
        if candidate.exists() and (candidate.is_symlink() or not candidate.is_dir()):
            _fail(IDENTITY_INVALID, 2)
    except (OSError, UnicodeError):
        _fail(IDENTITY_INVALID, 2)
    if candidate == root:
        _fail(IDENTITY_INVALID, 2)
    if root.exists():
        try:
            git_dir = Path(_run_git(root, "rev-parse", "--git-dir").stdout.decode("utf-8").strip())
            common_dir = Path(_run_git(root, "rev-parse", "--git-common-dir").stdout.decode("utf-8").strip())
            git_dir = (root / git_dir if not git_dir.is_absolute() else git_dir).resolve(strict=True)
            common_dir = (root / common_dir if not common_dir.is_absolute() else common_dir).resolve(strict=True)
        except (OSError, UnicodeError):
            _fail(IDENTITY_INVALID, 2)
        if any(base == candidate or base in candidate.parents for base in (git_dir, common_dir)):
            _fail(IDENTITY_INVALID, 2)
    if root in candidate.parents:
        try:
            relative = candidate.relative_to(root).as_posix() + "/"
        except ValueError:
            _fail(IDENTITY_INVALID, 2)
        if _run_git(root, "check-ignore", "--quiet", "--no-index", "--", relative).returncode != 0:
            _fail(IDENTITY_INVALID, 2)
    return candidate


def _read_input(raw_path: str, config_path: Path) -> tuple[Path, bytes]:
    path = Path(raw_path)
    if not path.is_absolute():
        path = config_path.parent / path
    try:
        if path.is_symlink() or not path.is_file():
            _fail(INPUT_INVALID, 2)
        return path.resolve(strict=True), path.read_bytes()
    except OSError:
        _fail(INPUT_INVALID, 2)


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError):
        _fail(PUBLISH_FAILED, 4)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_object(value: bytes) -> dict[str, object]:
    def no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError
            result[key] = item
        return result

    try:
        decoded = json.loads(value.decode("utf-8"), object_pairs_hook=no_duplicates, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        _fail(ARTIFACT_INVALID, 3)
    if type(decoded) is not dict:
        _fail(ARTIFACT_INVALID, 3)
    return decoded


def _validate_payload(value: bytes, as_of: str) -> None:
    payload = _json_object(value)
    if set(payload) != PAYLOAD_KEYS or any(
        (
            payload.get("schema_version") != "market_regime_control.v1",
            payload.get("profile") != PLUGIN,
            payload.get("strategy") != STRATEGY,
            payload.get("plugin") != PLUGIN,
            payload.get("target_type") != "strategy",
            payload.get("mode") != MODE,
            payload.get("configured_mode") != MODE,
            payload.get("effective_mode") != MODE,
            payload.get("as_of") != as_of,
        )
    ):
        _fail(ARTIFACT_INVALID, 3)


def _package_projection(validated: Mapping[str, object], as_of: str) -> dict[str, object]:
    projection: dict[str, object] = {"strategy": STRATEGY, "plugin": PLUGIN, "enabled": True, "mode": MODE, "as_of": as_of}
    for key in sorted(REQUIRED_INPUTS | OPTIONAL_INPUTS):
        if key not in validated:
            continue
        if key == "prices":
            projection[key] = "@input:prices"
        elif key == "external_context":
            projection[key] = "@input:external_context"
        elif isinstance(validated[key], list):
            projection[key] = list(validated[key])
        else:
            projection[key] = validated[key]
    if set(projection) != (PACKAGE_KEYS if "external_context" in validated else PACKAGE_KEYS - {"external_context"}):
        _fail(UNEXPECTED, 70)
    return projection


def _runner_projection(validated: Mapping[str, object], as_of: str, staged: Mapping[str, Path], writer_root: Path) -> dict[str, object]:
    projection: dict[str, object] = {"strategy": STRATEGY, "plugin": PLUGIN, "enabled": True, "mode": MODE, "as_of": as_of, "output_dir": str(writer_root)}
    for key in sorted(REQUIRED_INPUTS | OPTIONAL_INPUTS):
        if key not in validated:
            continue
        if key in staged:
            projection[key] = str(staged[key])
        elif isinstance(validated[key], list):
            projection[key] = list(validated[key])
        else:
            projection[key] = validated[key]
    if set(projection) != (RUNNER_KEYS if "external_context" in validated else RUNNER_KEYS - {"external_context"}):
        _fail(UNEXPECTED, 70)
    return projection


def _file_identity(path: Path, status: str = "PRESENT") -> dict[str, object]:
    data = path.read_bytes()
    return {"status": status, "format": "csv", "sha256": _sha256(data), "size_bytes": len(data)}


def _build_package(validated: Mapping[str, object], as_of: str, session_id: str, commit: str, staged: Mapping[str, Path], payload: bytes) -> dict[str, object]:
    config = _package_projection(validated, as_of)
    inputs: dict[str, object] = {"prices": _file_identity(staged["prices"])}
    inputs["external_context"] = _file_identity(staged["external_context"]) if "external_context" in staged else {"status": "ABSENT"}
    return {
        "as_of": as_of,
        "config": {"sha256": _sha256(_canonical_bytes(config)), "value": config},
        "inputs": inputs,
        "payload": {"bytes_b64": base64.b64encode(payload).decode("ascii"), "schema_version": "market_regime_control.v1", "sha256": _sha256(payload), "size_bytes": len(payload)},
        "producer": {"commit_sha": commit, "entrypoint": ENTRYPOINT, "repository": REPOSITORY},
        "schema": SCHEMA,
        "session_id": session_id,
        "status": "PRESENT",
        "subject": {"mode": MODE, "plugin": PLUGIN, "strategy": STRATEGY},
    }


def _strict_package_readback(data: bytes, expected: Mapping[str, object]) -> None:
    package = _json_object(data)
    if data != _canonical_bytes(package) or package != expected:
        _fail(PUBLISH_FAILED, 4)
    try:
        payload = base64.b64decode(str(package["payload"]["bytes_b64"]), validate=True)  # type: ignore[index]
    except (KeyError, TypeError, ValueError):
        _fail(PUBLISH_FAILED, 4)
    if _sha256(payload) != package["payload"].get("sha256") or len(payload) != package["payload"].get("size_bytes"):  # type: ignore[index]
        _fail(PUBLISH_FAILED, 4)
    _validate_payload(payload, str(package["as_of"]))


def _cleanup(path: Path | None) -> None:
    if path is not None:
        shutil.rmtree(path, ignore_errors=True)


def run_present(
    config_path: str | Path,
    *,
    as_of: str,
    session_id: str,
    expected_commit: str,
    producer: Callable[[Mapping[str, object], str], Any] | None = None,
) -> Path:
    stage: Path | None = None
    staged_package: Path | None = None
    try:
        normalized_as_of, commit = _validate_args(as_of, session_id, expected_commit)
        root = _source_identity(commit)
        config = Path(config_path)
        validated, output_dir = _validated_config(_read_config(config))
        output_root = _admit_output_root(output_dir, root)
        inputs = {"prices": _read_input(str(validated["prices"]), config)}
        if "external_context" in validated:
            inputs["external_context"] = _read_input(str(validated["external_context"]), config)
        try:
            output_root.mkdir(parents=True, exist_ok=True)
            stage = Path(tempfile.mkdtemp(prefix=".t2b2-stage-", dir=output_root))
            staged: dict[str, Path] = {}
            for name, (_, content) in inputs.items():
                target = stage / "inputs" / f"{name}.csv"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                if target.read_bytes() != content:
                    _fail(PUBLISH_FAILED, 4)
                staged[name] = target
        except PresentError:
            raise
        except OSError:
            _fail(PUBLISH_FAILED, 4)
        writer_root = stage / "writer"
        runner_config = _runner_projection(validated, normalized_as_of, staged, writer_root)
        if producer is None:
            from .strategy_plugin_runner import run_market_regime_control_plugin

            producer = run_market_regime_control_plugin
        try:
            producer(runner_config, MODE)
        except PresentError:
            raise
        except Exception:
            _fail(EXECUTION_FAILED, 3)
        dated, latest = writer_root / "signals" / f"{normalized_as_of}.json", writer_root / "latest_signal.json"
        try:
            if any(path.is_symlink() or not path.is_file() for path in (dated, latest)):
                _fail(ARTIFACT_INVALID, 3)
            payload = dated.read_bytes()
            if payload != latest.read_bytes():
                _fail(ARTIFACT_INVALID, 3)
            _validate_payload(payload, normalized_as_of)
        except PresentError:
            raise
        except OSError:
            _fail(ARTIFACT_INVALID, 3)
        package = _build_package(validated, normalized_as_of, session_id, commit, staged, payload)
        package_bytes = _canonical_bytes(package)
        try:
            package_fd, package_name = tempfile.mkstemp(prefix=".t2b2-package-", dir=output_root)
            os.close(package_fd)
            staged_package = Path(package_name)
            staged_package.write_bytes(package_bytes)
            _strict_package_readback(staged_package.read_bytes(), package)
            _strict_package_readback(staged_package.read_bytes(), package)
            shutil.rmtree(writer_root)
            if writer_root.exists():
                _fail(PUBLISH_FAILED, 4)
            if _admit_output_root(output_dir, root) != output_root:
                _fail(IDENTITY_INVALID, 2)
            _source_identity(commit)
            destination = output_root / f"tqqq-market-regime-control-present-{normalized_as_of}-{_sha256(package_bytes)}.json"
            if destination.exists() or destination.is_symlink():
                _fail(PUBLISH_FAILED, 4)
            _cleanup(stage)
            stage = None
            os.replace(staged_package, destination)
            staged_package = None
            return destination
        except PresentError:
            raise
        except OSError:
            _fail(PUBLISH_FAILED, 4)
    except PresentError:
        raise
    except Exception:
        _fail(UNEXPECTED, 70)
    finally:
        _cleanup(stage)
        if staged_package is not None:
            try:
                staged_package.unlink(missing_ok=True)
            except OSError:
                pass


def _parse_cli(argv: list[str]) -> dict[str, str]:
    if len(argv) != 8:
        _fail(INPUT_INVALID, 2)
    values: dict[str, str] = {}
    for index in range(0, 8, 2):
        key, value = argv[index : index + 2]
        if key not in {"--config", "--as-of", "--session-id", "--expected-commit"} or key in values:
            _fail(INPUT_INVALID, 2)
        values[key] = value
    if set(values) != {"--config", "--as-of", "--session-id", "--expected-commit"}:
        _fail(INPUT_INVALID, 2)
    return values


def main(argv: list[str] | None = None) -> int:
    try:
        values = _parse_cli(list(sys.argv[1:] if argv is None else argv))
        destination = run_present(values["--config"], as_of=values["--as-of"], session_id=values["--session-id"], expected_commit=values["--expected-commit"])
    except PresentError as error:
        print(f"ERROR {error.code}", file=sys.stderr)
        return error.exit_code
    print(f"{destination} {_sha256(destination.read_bytes())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
