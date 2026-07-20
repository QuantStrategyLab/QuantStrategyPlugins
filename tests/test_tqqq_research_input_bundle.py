from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from quant_strategy_plugins import tqqq_research_input_bundle as bundle


def _records(*, days: int = 252) -> list[dict[str, object]]:
    start = date(2026, 7, 21) - timedelta(days=days - 1)
    rows: list[dict[str, object]] = []
    for offset in range(days):
        session = (start + timedelta(days=offset)).isoformat()
        for index, symbol in enumerate(bundle.REQUESTED_SYMBOLS):
            close = 100.0 + index + offset / 10
            rows.append(
                {
                    "symbol": symbol,
                    "as_of": session,
                    "open": close - 1,
                    "high": close + 1,
                    "low": close - 2,
                    "close": close,
                    "volume": 0 if symbol == "QQQ" and offset == 0 else 1000 + offset,
                }
            )
    return rows


def _raw(*, days: int = 252) -> bytes:
    return bundle.serialize_price_rows(_records(days=days), end_exclusive="2026-08-01")


@pytest.fixture
def source_gate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    root.mkdir()
    monkeypatch.setattr(bundle, "_source_identity", lambda expected_commit: root)
    monkeypatch.setattr(bundle, "_git_common_dir", lambda source_root: source_root / ".git")
    return root


def _build(tmp_path: Path, source_gate: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, int]:
    calls = 0

    def provider(symbols: list[str], *, start: str, end: str):
        nonlocal calls
        calls += 1
        assert symbols == list(bundle.REQUESTED_SYMBOLS)
        assert start == "2010-01-01"
        assert end == "2026-08-01"
        return _records()

    output_parent = tmp_path / "published"
    output_parent.mkdir()
    destination = bundle.build_input_bundle(
        output_parent,
        end_exclusive="2026-08-01",
        expected_commit="a" * 40,
        provider=provider,
    )
    return destination, calls


def test_projection_is_pure_exact_qqq_session_date_close_bytes() -> None:
    raw = _raw()

    projected, count, first_date, last_date = bundle.project_qqq_benchmark_bytes(raw)

    qqq = [row for row in bundle.parse_price_rows(raw) if row["symbol"] == "QQQ"]
    assert projected == (
        b"session_date,close\n"
        + b"".join(f"{row['as_of']},{row['close']}\n".encode("ascii") for row in qqq)
    )
    assert (count, first_date, last_date) == (252, "2025-11-12", "2026-07-21")
    assert bundle.TRANSFORM_ID == "qsp.t2b3.qqq_session_date_close_csv"
    assert bundle.TRANSFORM_VERSION == "1"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda raw: raw.replace(b"QQQ,2025-11-12", b"QQQ,2025-11-13", 1),
        lambda raw: raw.replace(b",100,", b",100.0,", 1),
        lambda raw: raw.replace(b"\n", b"\r\n", 1),
        lambda raw: raw[:-1],
    ],
)
def test_raw_parser_rejects_noncanonical_or_nonincreasing_bytes(mutator) -> None:
    with pytest.raises(bundle.BundleError) as error:
        bundle.parse_price_rows(mutator(_raw()))

    assert error.value.code == bundle.PROVIDER_DATA_INVALID


def test_serializer_canonicalizes_equivalent_records_and_rejects_incomplete_last_qqq() -> None:
    records = _records()
    reversed_records = list(reversed(records))
    assert bundle.serialize_price_rows(records, end_exclusive="2026-08-01") == bundle.serialize_price_rows(
        reversed_records, end_exclusive="2026-08-01"
    )
    records[-10]["volume"] = None
    with pytest.raises(bundle.BundleError) as error:
        bundle.serialize_price_rows(records, end_exclusive="2026-08-01")
    assert error.value.code == bundle.PROVIDER_DATA_INVALID


def test_build_publishes_exact_three_member_bundle_with_full_lineage(
    tmp_path: Path, source_gate: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination, calls = _build(tmp_path, source_gate, monkeypatch)

    assert calls == 1
    assert sorted(path.name for path in destination.iterdir()) == ["config.toml", "manifest.json", "prices.csv"]
    manifest_bytes = (destination / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    raw = (destination / "prices.csv").read_bytes()
    projected, count, first_date, last_date = bundle.project_qqq_benchmark_bytes(raw)
    assert destination.name == f"qsp-t2b3-qqq-input-v1-{last_date}-{hashlib.sha256(manifest_bytes).hexdigest()}"
    assert (destination / "config.toml").read_bytes() == bundle.CONFIG_BYTES
    assert manifest["external_context"] == {"status": "ABSENT"}
    assert manifest["prices"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert manifest["projection"] == {
        "benchmark_sha256": hashlib.sha256(projected).hexdigest(),
        "benchmark_size_bytes": len(projected),
        "first_date": first_date,
        "last_date": last_date,
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "row_count": count,
        "symbol": "QQQ",
        "transform_id": bundle.TRANSFORM_ID,
        "transform_version": "1",
    }
    bundle.strict_readback_bundle(destination, expected_manifest=manifest_bytes)


@pytest.mark.parametrize("member", ["prices.csv", "config.toml", "manifest.json"])
def test_readback_rejects_member_tampering_before_publication(
    tmp_path: Path, source_gate: Path, monkeypatch: pytest.MonkeyPatch, member: str
) -> None:
    destination, _ = _build(tmp_path, source_gate, monkeypatch)
    expected = (destination / "manifest.json").read_bytes()
    path = destination / member
    path.write_bytes(path.read_bytes() + b"x")

    with pytest.raises(bundle.BundleError) as error:
        bundle.strict_readback_bundle(destination, expected_manifest=expected)
    assert error.value.code == bundle.READBACK_FAILED


def test_build_fails_closed_for_external_parent_and_never_calls_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    monkeypatch.setattr(bundle, "_source_identity", lambda expected_commit: root)
    monkeypatch.setattr(bundle, "_git_common_dir", lambda source_root: source_root / ".git")
    calls = 0

    def provider(*args, **kwargs):
        nonlocal calls
        calls += 1
        return _records()

    with pytest.raises(bundle.BundleError) as error:
        bundle.build_input_bundle(root / "inside", end_exclusive="2026-08-01", expected_commit="a" * 40, provider=provider)
    assert error.value.code == bundle.IDENTITY_INVALID
    assert calls == 0


@pytest.mark.parametrize("fault_name, expected_code", [("_write_member", bundle.PUBLISH_FAILED), ("_readback_bundle", bundle.READBACK_FAILED)])
def test_stage_faults_publish_nothing(
    tmp_path: Path, source_gate: Path, monkeypatch: pytest.MonkeyPatch, fault_name: str, expected_code: str
) -> None:
    original = getattr(bundle, fault_name)

    def fail(*args, **kwargs):
        raise OSError("private implementation failure")

    monkeypatch.setattr(bundle, fault_name, fail)
    with pytest.raises(bundle.BundleError) as error:
        _build(tmp_path, source_gate, monkeypatch)
    assert error.value.code == expected_code
    assert not list((tmp_path / "published").glob("qsp-t2b3-qqq-input-v1-*"))
    monkeypatch.setattr(bundle, fault_name, original)


def test_main_sanitizes_provider_failure_and_does_not_disclose_exception(
    tmp_path: Path, source_gate: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    output_parent = tmp_path / "published"
    output_parent.mkdir()
    monkeypatch.setattr(bundle, "download_price_history", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("SECRET=never-print")))

    assert bundle.main(["--output-parent", str(output_parent), "--end-exclusive", "2026-08-01", "--expected-commit", "a" * 40]) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "ERROR T2B3_BUNDLE_PROVIDER_FAILED\n"
    assert "SECRET" not in captured.err


def test_manifest_parser_rejects_duplicate_keys_and_wrong_schema() -> None:
    with pytest.raises(bundle.BundleError) as duplicate:
        bundle.parse_manifest(b'{"schema":"x","schema":"x"}')
    with pytest.raises(bundle.BundleError) as invalid:
        bundle.parse_manifest(b'{"schema":"x"}')
    assert duplicate.value.code == bundle.READBACK_FAILED
    assert invalid.value.code == bundle.READBACK_FAILED
