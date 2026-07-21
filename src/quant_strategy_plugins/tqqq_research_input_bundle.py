"""Build an immutable, research-only QQQ input bundle.

The bundle binds canonical multi-symbol raw prices to a pure QQQ
``session_date,close`` projection.  It is evidence-only: this module neither
creates strategy decisions nor reaches any broker, order, capital, or position
path.  ``QUARANTINED`` failures are logical classifications; failed staging is
removed best-effort and no retry, repair, alias, or watcher is created.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Callable, Iterable, Mapping

from quant_strategy_plugins.yfinance_prices import download_price_history


IDENTITY_INVALID = "T2B3_BUNDLE_IDENTITY_INVALID"
INPUT_INVALID = "T2B3_BUNDLE_INPUT_INVALID"
PROVIDER_FAILED = "T2B3_BUNDLE_PROVIDER_FAILED"
PROVIDER_DATA_INVALID = "T2B3_BUNDLE_PROVIDER_DATA_INVALID"
READBACK_FAILED = "T2B3_BUNDLE_READBACK_FAILED"
PUBLISH_FAILED = "T2B3_BUNDLE_PUBLISH_FAILED"
UNEXPECTED = "T2B3_BUNDLE_UNEXPECTED"

SCHEMA = "qsl.t2b3.qqq_price_projection_bundle.v1"
ENTRYPOINT = "quant_strategy_plugins.tqqq_research_input_bundle"
REPOSITORY = "QuantStrategyLab/QuantStrategyPlugins"
TRANSFORM_ID = "qsp.t2b3.qqq_session_date_close_csv"
TRANSFORM_VERSION = "1"
RAW_FORMAT = "qsp.t2b3.long_price_csv.v1"
REQUESTED_SYMBOLS = ("QQQ", "TQQQ", "^VIX", "^VIX3M", "HYG", "IEF", "LQD", "XLF", "KRE", "TLT")
SORTED_SYMBOLS = tuple(sorted(REQUESTED_SYMBOLS))
RAW_HEADER = b"symbol,as_of,open,high,low,close,volume\n"
MIN_AS_OF = "2026-07-21"
CONFIG_BYTES = b'''default_mode = "shadow"

[[strategy_plugins]]
strategy = "tqqq_growth_income"
plugin = "market_regime_control"
enabled = true

[strategy_plugins.inputs]
prices = "prices.csv"
event_set = "geopolitical-deescalation"
benchmark_symbol = "QQQ"
attack_symbol = "TQQQ"
vix_symbols = ["VIX", "^VIX", "VIXCLS"]
vix3m_symbols = ["VIX3M", "^VIX3M", "VXV", "^VXV"]
credit_pairs = ["HYG:IEF", "LQD:IEF"]
financial_symbols = ["XLF", "KRE"]
rate_symbols = ["IEF", "TLT"]
strategy_policy = "levered_growth_income_v1"
realized_vol_threshold = 0.30
realized_vol_requires_confirmation = true
external_stress_actionable = false
delever_risk_asset_scalar = 0.0
taco_opportunity_size_scalar = 0.0
crisis_enabled = true
macro_enabled = true
taco_enabled = true
panic_reversal_enabled = false

[strategy_plugins.outputs]
output_dir = "data/output/tqqq_growth_income/plugins/market_regime_control"
'''


class BundleError(Exception):
    """A bounded, sanitized bundle-builder failure."""

    def __init__(self, code: str, exit_code: int) -> None:
        self.code = code
        self.exit_code = exit_code
        super().__init__(code)


def _fail(code: str, exit_code: int) -> None:
    raise BundleError(code, exit_code)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _date_text(value: object) -> str:
    if isinstance(value, str):
        text = value
    elif isinstance(value, date):
        text = value.isoformat()
    elif hasattr(value, "date") and callable(value.date):
        candidate = value.date()
        text = candidate.isoformat() if isinstance(candidate, date) else ""
    else:
        text = ""
    try:
        parsed = date.fromisoformat(text)
    except (TypeError, ValueError):
        _fail(PROVIDER_DATA_INVALID, 3)
    if text != parsed.isoformat():
        _fail(PROVIDER_DATA_INVALID, 3)
    return text


def _end_exclusive(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        _fail(INPUT_INVALID, 2)
    if value != parsed.isoformat():
        _fail(INPUT_INVALID, 2)
    return value


def _number_token(value: object, *, positive: bool, optional: bool) -> str:
    if value is None:
        if optional:
            return ""
        _fail(PROVIDER_DATA_INVALID, 3)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(PROVIDER_DATA_INVALID, 3)
    numeric = float(value)
    if math.isnan(numeric):
        if optional:
            return ""
        _fail(PROVIDER_DATA_INVALID, 3)
    if not math.isfinite(numeric) or math.copysign(1.0, numeric) < 0 and numeric == 0:
        _fail(PROVIDER_DATA_INVALID, 3)
    if positive and numeric <= 0:
        _fail(PROVIDER_DATA_INVALID, 3)
    if not positive and numeric < 0:
        _fail(PROVIDER_DATA_INVALID, 3)
    return "0" if numeric == 0 else format(numeric, ".17g")


def _validate_token(token: str, *, positive: bool, optional: bool) -> None:
    if token == "" and optional:
        return
    if token == "" or any(character.isspace() for character in token):
        _fail(PROVIDER_DATA_INVALID, 3)
    try:
        numeric = float(token)
    except ValueError:
        _fail(PROVIDER_DATA_INVALID, 3)
    if not math.isfinite(numeric) or (math.copysign(1.0, numeric) < 0 and numeric == 0):
        _fail(PROVIDER_DATA_INVALID, 3)
    if (positive and numeric <= 0) or (not positive and numeric < 0):
        _fail(PROVIDER_DATA_INVALID, 3)
    canonical = "0" if numeric == 0 else format(numeric, ".17g")
    if token != canonical:
        _fail(PROVIDER_DATA_INVALID, 3)


def _records_from_frame(frame: object) -> Iterable[Mapping[str, object]]:
    if isinstance(frame, list):
        rows = frame
    elif hasattr(frame, "to_dict"):
        try:
            rows = frame.to_dict("records")  # type: ignore[union-attr]
        except (TypeError, ValueError):
            _fail(PROVIDER_DATA_INVALID, 3)
    else:
        _fail(PROVIDER_DATA_INVALID, 3)
    if not isinstance(rows, list):
        _fail(PROVIDER_DATA_INVALID, 3)
    for row in rows:
        if not isinstance(row, Mapping):
            _fail(PROVIDER_DATA_INVALID, 3)
        yield row


def _normalised_rows(records: object, *, end_exclusive: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for record in _records_from_frame(records):
        if set(record) != {"symbol", "as_of", "open", "high", "low", "close", "volume"}:
            _fail(PROVIDER_DATA_INVALID, 3)
        symbol = record["symbol"]
        if not isinstance(symbol, str) or symbol not in REQUESTED_SYMBOLS:
            _fail(PROVIDER_DATA_INVALID, 3)
        as_of = _date_text(record["as_of"])
        if as_of >= end_exclusive:
            _fail(PROVIDER_DATA_INVALID, 3)
        rows.append(
            {
                "symbol": symbol,
                "as_of": as_of,
                "open": _number_token(record["open"], positive=True, optional=True),
                "high": _number_token(record["high"], positive=True, optional=True),
                "low": _number_token(record["low"], positive=True, optional=True),
                "close": _number_token(record["close"], positive=True, optional=False),
                "volume": _number_token(record["volume"], positive=False, optional=True),
            }
        )
    rows.sort(key=lambda row: (row["as_of"], row["symbol"]))
    _validate_rows(rows)
    return rows


def _validate_rows(rows: list[dict[str, str]]) -> tuple[str, dict[str, int]]:
    if not rows:
        _fail(PROVIDER_DATA_INVALID, 3)
    previous: tuple[str, str] | None = None
    counts = {symbol: 0 for symbol in REQUESTED_SYMBOLS}
    for row in rows:
        if set(row) != {"symbol", "as_of", "open", "high", "low", "close", "volume"}:
            _fail(PROVIDER_DATA_INVALID, 3)
        symbol, as_of = row["symbol"], row["as_of"]
        if symbol not in counts or _date_text(as_of) != as_of:
            _fail(PROVIDER_DATA_INVALID, 3)
        current = (as_of, symbol)
        if previous is not None and current <= previous:
            _fail(PROVIDER_DATA_INVALID, 3)
        previous = current
        _validate_token(row["open"], positive=True, optional=True)
        _validate_token(row["high"], positive=True, optional=True)
        _validate_token(row["low"], positive=True, optional=True)
        _validate_token(row["close"], positive=True, optional=False)
        _validate_token(row["volume"], positive=False, optional=True)
        counts[symbol] += 1
    if any(count < 252 for count in counts.values()):
        _fail(PROVIDER_DATA_INVALID, 3)
    qqq_rows = [row for row in rows if row["symbol"] == "QQQ"]
    as_of = qqq_rows[-1]["as_of"]
    if as_of < MIN_AS_OF or any(row["as_of"] > as_of for row in rows):
        _fail(PROVIDER_DATA_INVALID, 3)
    if any(qqq_rows[-1][field] == "" for field in ("open", "high", "low", "close", "volume")):
        _fail(PROVIDER_DATA_INVALID, 3)
    return as_of, counts


def serialize_price_rows(records: object, *, end_exclusive: str) -> bytes:
    """Canonicalize provider-normalized rows into immutable raw bytes ``R``."""
    end = _end_exclusive(end_exclusive)
    rows = _normalised_rows(records, end_exclusive=end)
    raw = RAW_HEADER + b"".join(
        ",".join(row[field] for field in ("symbol", "as_of", "open", "high", "low", "close", "volume")).encode("ascii") + b"\n"
        for row in rows
    )
    if _serialize_parsed_rows(parse_price_rows(raw)) != raw:
        _fail(PROVIDER_DATA_INVALID, 3)
    return raw


def _serialize_parsed_rows(rows: list[dict[str, str]]) -> bytes:
    return RAW_HEADER + b"".join(
        ",".join(row[field] for field in ("symbol", "as_of", "open", "high", "low", "close", "volume")).encode("ascii") + b"\n"
        for row in rows
    )


def parse_price_rows(raw: bytes) -> list[dict[str, str]]:
    """Strictly parse canonical raw bytes without provider or filesystem effects."""
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        _fail(PROVIDER_DATA_INVALID, 3)
    if not text.startswith(RAW_HEADER.decode("ascii")) or "\r" in text or not text.endswith("\n") or text.endswith("\n\n"):
        _fail(PROVIDER_DATA_INVALID, 3)
    lines = text.splitlines()
    if not lines or lines[0] != RAW_HEADER.decode("ascii").rstrip("\n"):
        _fail(PROVIDER_DATA_INVALID, 3)
    rows: list[dict[str, str]] = []
    for line in lines[1:]:
        fields = line.split(",")
        if len(fields) != 7 or any('"' in field for field in fields):
            _fail(PROVIDER_DATA_INVALID, 3)
        rows.append(dict(zip(("symbol", "as_of", "open", "high", "low", "close", "volume"), fields, strict=True)))
    _validate_rows(rows)
    if _serialize_parsed_rows(rows) != raw:
        _fail(PROVIDER_DATA_INVALID, 3)
    return rows


def project_qqq_benchmark_bytes(raw: bytes) -> tuple[bytes, int, str, str]:
    """Purely project canonical raw ``R`` into exact QQQ benchmark bytes ``B``."""
    rows = parse_price_rows(raw)
    qqq_rows = [row for row in rows if row["symbol"] == "QQQ"]
    first_date, last_date = qqq_rows[0]["as_of"], qqq_rows[-1]["as_of"]
    projected = b"session_date,close\n" + b"".join(
        f"{row['as_of']},{row['close']}\n".encode("ascii") for row in qqq_rows
    )
    if len(qqq_rows) < 252 or any(
        later["as_of"] <= earlier["as_of"] for earlier, later in zip(qqq_rows, qqq_rows[1:])
    ):
        _fail(PROVIDER_DATA_INVALID, 3)
    return projected, len(qqq_rows), first_date, last_date


def _manifest(raw: bytes, projected: bytes, count: int, first_date: str, as_of: str, expected_commit: str, end: str) -> dict[str, object]:
    parsed_rows = parse_price_rows(raw)
    return {
        "config": {"filename": "config.toml", "sha256": _sha256(CONFIG_BYTES), "size_bytes": len(CONFIG_BYTES)},
        "external_context": {"status": "ABSENT"},
        "prices": {
            "filename": "prices.csv",
            "first_date": parsed_rows[0]["as_of"],
            "format": RAW_FORMAT,
            "last_date": as_of,
            "row_count": len(parsed_rows),
            "sha256": _sha256(raw),
            "size_bytes": len(raw),
            "symbols": list(SORTED_SYMBOLS),
        },
        "producer": {"commit_sha": expected_commit, "entrypoint": ENTRYPOINT, "repository": REPOSITORY},
        "projection": {
            "benchmark_sha256": _sha256(projected),
            "benchmark_size_bytes": len(projected),
            "first_date": first_date,
            "last_date": as_of,
            "raw_sha256": _sha256(raw),
            "row_count": count,
            "symbol": "QQQ",
            "transform_id": TRANSFORM_ID,
            "transform_version": TRANSFORM_VERSION,
        },
        "provider": {
            "auto_adjust": True,
            "credentials": "ABSENT",
            "end_exclusive": end,
            "path": "quant_strategy_plugins.yfinance_prices:download_price_history",
            "provider_id": "yahoo_yfinance_public",
            "requested_symbols": list(REQUESTED_SYMBOLS),
            "start": "2010-01-01",
        },
        "schema": SCHEMA,
        "session": {
            "as_of": as_of,
            "claim": "PROVIDER_OBSERVED_ONLY_NOT_OFFICIAL_XNAS_PROOF",
            "session_id": f"XNAS:{as_of}",
            "source": "LAST_COMPLETE_QQQ_ROW",
        },
        "status": "READY",
    }


def parse_manifest(value: bytes) -> dict[str, object]:
    """Strictly parse canonical manifest JSON; duplicate and partial shapes fail closed."""
    def no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError
            result[key] = item
        return result

    try:
        parsed = json.loads(value.decode("utf-8"), object_pairs_hook=no_duplicates, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        _fail(READBACK_FAILED, 4)
    if type(parsed) is not dict or value != _canonical_json(parsed):
        _fail(READBACK_FAILED, 4)
    required = {"config", "external_context", "prices", "producer", "projection", "provider", "schema", "session", "status"}
    if set(parsed) != required or parsed.get("schema") != SCHEMA or parsed.get("status") != "READY":
        _fail(READBACK_FAILED, 4)
    return parsed


def _run_git(root: Path, *args: str) -> bytes:
    try:
        completed = subprocess.run(("git", *args), cwd=root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    except OSError:
        _fail(IDENTITY_INVALID, 2)
    if completed.returncode != 0:
        _fail(IDENTITY_INVALID, 2)
    return completed.stdout


def _source_identity(expected_commit: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
        _fail(INPUT_INVALID, 2)
    source_root = Path(__file__).resolve().parents[2]
    root = Path(_run_git(source_root, "rev-parse", "--show-toplevel").decode("utf-8").strip()).resolve()
    head = _run_git(root, "rev-parse", "HEAD").decode("ascii").strip()
    if head != expected_commit or _run_git(root, "status", "--porcelain"):
        _fail(IDENTITY_INVALID, 2)
    _run_git(root, "ls-files", "--error-unmatch", "src/quant_strategy_plugins/tqqq_research_input_bundle.py")
    return root


def _git_common_dir(root: Path) -> Path:
    return Path(_run_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").decode("utf-8").strip()).resolve()


def _admit_output_parent(value: str | Path, root: Path) -> Path:
    parent = Path(value)
    if not parent.is_absolute() or parent.is_symlink() or not parent.is_dir():
        _fail(IDENTITY_INVALID, 2)
    try:
        resolved = parent.resolve(strict=True)
        common = _git_common_dir(root)
        resolved.relative_to(root.resolve())
        _fail(IDENTITY_INVALID, 2)
    except ValueError:
        pass
    try:
        resolved.relative_to(common)
        _fail(IDENTITY_INVALID, 2)
    except ValueError:
        return resolved


def _write_member(path: Path, value: bytes) -> None:
    path.write_bytes(value)


def _read_member(path: Path) -> bytes:
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            _fail(READBACK_FAILED, 4)
        return path.read_bytes()
    except OSError:
        _fail(READBACK_FAILED, 4)


def _readback_bundle(directory: Path, config: bytes, raw: bytes, manifest: bytes) -> None:
    try:
        if directory.is_symlink() or not directory.is_dir() or {path.name for path in directory.iterdir()} != {"config.toml", "prices.csv", "manifest.json"}:
            _fail(READBACK_FAILED, 4)
    except OSError:
        _fail(READBACK_FAILED, 4)
    actual_config = _read_member(directory / "config.toml")
    actual_raw = _read_member(directory / "prices.csv")
    actual_manifest = _read_member(directory / "manifest.json")
    if actual_config != config or actual_raw != raw or actual_manifest != manifest or actual_config != CONFIG_BYTES:
        _fail(READBACK_FAILED, 4)
    parsed = parse_manifest(actual_manifest)
    try:
        projected, count, first_date, last_date = project_qqq_benchmark_bytes(actual_raw)
    except BundleError:
        _fail(READBACK_FAILED, 4)
    expected = _manifest(actual_raw, projected, count, first_date, last_date, str(parsed["producer"].get("commit_sha")), str(parsed["provider"].get("end_exclusive"))) if isinstance(parsed["producer"], dict) and isinstance(parsed["provider"], dict) else None
    if expected is None or parsed != expected or actual_manifest != _canonical_json(expected):
        _fail(READBACK_FAILED, 4)


def strict_readback_bundle(
    directory: str | Path,
    *,
    expected_manifest_sha256: str,
    expected_commit: str,
    expected_end_exclusive: str,
) -> None:
    """Verify a presented bundle against independently trusted lineage values."""
    path = Path(directory)
    if (
        not isinstance(expected_manifest_sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha256)
        or not isinstance(expected_commit, str)
        or not re.fullmatch(r"[0-9a-f]{40}", expected_commit)
    ):
        _fail(READBACK_FAILED, 4)
    try:
        expected_end = _end_exclusive(expected_end_exclusive)
    except BundleError:
        _fail(READBACK_FAILED, 4)
    manifest = _read_member(path / "manifest.json")
    if _sha256(manifest) != expected_manifest_sha256:
        _fail(READBACK_FAILED, 4)
    parsed = parse_manifest(manifest)
    producer = parsed.get("producer")
    provider = parsed.get("provider")
    if (
        not isinstance(producer, dict)
        or not isinstance(provider, dict)
        or producer.get("commit_sha") != expected_commit
        or provider.get("end_exclusive") != expected_end
    ):
        _fail(READBACK_FAILED, 4)
    _readback_bundle(path, CONFIG_BYTES, _read_member(path / "prices.csv"), manifest)


def _cleanup(stage: Path | None) -> None:
    if stage is not None:
        shutil.rmtree(stage, ignore_errors=True)


def build_input_bundle(
    output_parent: str | Path,
    *,
    end_exclusive: str,
    expected_commit: str,
    provider: Callable[..., object] | None = None,
) -> Path:
    """Publish one validated three-member bundle using one atomic directory rename."""
    stage: Path | None = None
    try:
        end = _end_exclusive(end_exclusive)
        root = _source_identity(expected_commit)
        parent = _admit_output_parent(output_parent, root)
        try:
            frame = (provider or download_price_history)(list(REQUESTED_SYMBOLS), start="2010-01-01", end=end)
        except Exception:
            _fail(PROVIDER_FAILED, 3)
        raw = serialize_price_rows(frame, end_exclusive=end)
        projected, count, first_date, as_of = project_qqq_benchmark_bytes(raw)
        manifest = _canonical_json(_manifest(raw, projected, count, first_date, as_of, expected_commit, end))
        destination = parent / f"qsp-t2b3-qqq-input-v1-{as_of}-{_sha256(manifest)}"
        if destination.exists() or destination.is_symlink():
            _fail(INPUT_INVALID, 2)
        try:
            stage = Path(tempfile.mkdtemp(prefix=".t2b3-stage-", dir=parent))
            _write_member(stage / "config.toml", CONFIG_BYTES)
            _write_member(stage / "prices.csv", raw)
            _write_member(stage / "manifest.json", manifest)
        except BundleError:
            raise
        except OSError:
            _fail(PUBLISH_FAILED, 4)
        for _ in range(2):
            try:
                _readback_bundle(stage, CONFIG_BYTES, raw, manifest)
            except BundleError:
                raise
            except Exception:
                _fail(READBACK_FAILED, 4)
        _source_identity(expected_commit)
        _admit_output_parent(parent, root)
        if destination.exists() or destination.is_symlink():
            _fail(INPUT_INVALID, 2)
        try:
            os.replace(stage, destination)
            stage = None
        except OSError:
            _fail(PUBLISH_FAILED, 4)
        return destination
    finally:
        _cleanup(stage)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--output-parent", required=True)
    parser.add_argument("--end-exclusive", required=True)
    parser.add_argument("--expected-commit", required=True)
    try:
        arguments = parser.parse_args(argv)
        destination = build_input_bundle(
            arguments.output_parent,
            end_exclusive=arguments.end_exclusive,
            expected_commit=arguments.expected_commit,
        )
        match = re.fullmatch(r"qsp-t2b3-qqq-input-v1-(\d{4}-\d{2}-\d{2})-([0-9a-f]{64})", destination.name)
        if match is None:
            _fail(UNEXPECTED, 70)
        print(f"{destination} {match.group(2)} {match.group(1)}")
        return 0
    except BundleError as error:
        print(f"ERROR {error.code}", file=sys.stderr)
        return error.exit_code
    except SystemExit:
        print(f"ERROR {INPUT_INVALID}", file=sys.stderr)
        return 2
    except Exception:
        print(f"ERROR {UNEXPECTED}", file=sys.stderr)
        return 70


if __name__ == "__main__":
    raise SystemExit(main())
