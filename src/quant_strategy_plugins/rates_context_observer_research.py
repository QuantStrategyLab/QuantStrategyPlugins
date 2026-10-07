"""Pure ten-year rates observations from caller-frozen, source-agnostic records.

No provider, clock, I/O, registration, thresholds, votes, or trading authority.
Availability and source identities are declarations, never historical PIT proof.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
import math


INPUT_VERSION = "qsl.rates-context-input.research.v1"
CONFIG_VERSION = "qsl.rates-context-config.research.v1"
OBSERVATION_VERSION = "qsl.rates-context-observation.research.v1"
ROLES = ("nominal_10y", "real_10y", "breakeven_10y")
_CONFIG_KEYS = {"schema_version", "window_start", "window_end", "max_observation_age_days"}
_SERIES_KEYS = {"source_id", "series_id", "basis", "unit", "rows"}
_ROW_KEYS = {"observation_date", "value", "available_at", "received_at", "revision_id"}
_YIELD_BASES = {"treasury_par_yield", "treasury_constant_maturity_yield"}


class ContractError(ValueError):
    """Invalid configuration without echoing caller data."""


def _date(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
        return parsed if parsed.isoformat() == value else None
    except ValueError:
        return None


def _time(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def _stamp(value):
    return value.isoformat().replace("+00:00", "Z") if value is not None else None


def _text(value):
    return value if isinstance(value, str) and value.strip() == value and 0 < len(value) <= 256 else None


def _number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, OverflowError):
        return None


def _rounded(value):
    if not math.isfinite(value):
        return None
    rounded = round(value, 12)
    return 0.0 if rounded == 0 else rounded


def _config(value):
    if not isinstance(value, Mapping) or set(value) != _CONFIG_KEYS or value.get("schema_version") != CONFIG_VERSION:
        raise ContractError("invalid_config")
    start, end, age = _date(value["window_start"]), _date(value["window_end"]), value["max_observation_age_days"]
    if start is None or end is None or start >= end or not isinstance(age, int) or isinstance(age, bool) or age < 0:
        raise ContractError("invalid_config")
    return start, end, age


def _endpoint(row):
    if row is None:
        return None
    return {"observation_date": row["observation_date"],
            "available_at": _stamp(_time(row.get("available_at"))),
            "received_at": _stamp(_time(row.get("received_at"))),
            "revision_id": _text(row.get("revision_id"))}


def _observe_series(series, role, start, end, decision, max_age, top_valid):
    series = series if isinstance(series, Mapping) else {}
    result = {"status": "unknown", "reason_codes": [], "source_id": _text(series.get("source_id")),
              "series_id": _text(series.get("series_id")), "basis": _text(series.get("basis")),
              "declared_unit": _text(series.get("unit")), "unit": "percent", "start_percent": None,
              "end_percent": None, "change_bp": None, "start_observation": None, "end_observation": None,
              "latest_observation_date": None, "observation_age_days": None,
              "availability_delay_calendar_days": None, "receipt_lag_seconds": None,
              "visible_observations": 0}
    reasons = result["reason_codes"]
    if not top_valid:
        reasons.append("INPUT_INVALID")
        return result
    if not series:
        reasons.append("SERIES_MISSING")
        return result
    if set(series) != _SERIES_KEYS or result["source_id"] is None or result["series_id"] is None:
        reasons.append("SOURCE_IDENTITY_INVALID")
    allowed_basis = {"reported_breakeven"} if role == "breakeven_10y" else _YIELD_BASES
    if result["basis"] not in allowed_basis:
        reasons.append("BASIS_INVALID")
    if series.get("unit") != "percent":
        reasons.append("UNIT_NOT_PERCENT")
    rows = series.get("rows")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        reasons.append("ROWS_INVALID")
        return result
    visible = []
    previous = None
    for row in rows:
        if not isinstance(row, Mapping) or (observed := _date(row.get("observation_date"))) is None:
            reasons.append("ROW_DATE_INVALID")
            continue
        # Historical projection precedes all other fields: no future values,
        # delayed revisions, or dates outside the exact interval can affect it.
        if observed < start or observed > end:
            continue
        available = _time(row.get("available_at"))
        if available is not None and available > decision:
            continue
        received = _time(row.get("received_at"))
        if received is not None and received > decision:
            continue
        if previous is not None and observed <= previous:
            reasons.append("ROW_ORDER_OR_REVISION_AMBIGUOUS")
        previous = observed
        visible.append(row)
        if set(row) != _ROW_KEYS:
            reasons.append("ROW_FIELDS_INVALID")
        if available is None:
            reasons.append("AVAILABILITY_UNKNOWN")
        elif available.date() < observed:
            reasons.append("AVAILABILITY_BEFORE_OBSERVATION")
        if received is None:
            reasons.append("RECEIPT_UNKNOWN")
        elif available is not None and received < available:
            reasons.append("RECEIPT_BEFORE_AVAILABILITY")
        if _text(row.get("revision_id")) is None or row.get("revision_id") == "latest":
            reasons.append("REVISION_IDENTITY_INVALID")
        if _number(row.get("value")) is None:
            reasons.append("VALUE_INVALID")
    result["visible_observations"] = len(visible)
    by_date = {row["observation_date"]: row for row in visible}
    first, last = by_date.get(start.isoformat()), by_date.get(end.isoformat())
    result["start_observation"], result["end_observation"] = _endpoint(first), _endpoint(last)
    if first is None or last is None:
        reasons.append("WINDOW_ENDPOINT_UNAVAILABLE")
    if visible:
        latest = max(_date(row["observation_date"]) for row in visible)
        result["latest_observation_date"] = latest.isoformat()
        result["observation_age_days"] = (decision.date() - latest).days
        if result["observation_age_days"] > max_age:
            reasons.append("OBSERVATION_STALE")
        if latest > decision.date():
            reasons.append("OBSERVATION_AFTER_DECISION")
    if last is not None:
        available, received = _time(last.get("available_at")), _time(last.get("received_at"))
        if available is not None:
            result["availability_delay_calendar_days"] = (available.date() - end).days
        if available is not None and received is not None:
            result["receipt_lag_seconds"] = (received - available).total_seconds()
    if not reasons:
        first_value, last_value = _number(first["value"]), _number(last["value"])
        change = _rounded(100 * (last_value - first_value))
        if change is None:
            reasons.append("CHANGE_NONFINITE")
        else:
            result.update(status="declared_available", start_percent=first_value,
                          end_percent=last_value, change_bp=change)
    result["reason_codes"] = sorted(set(reasons))
    return result


def build_rates_context_observation(snapshot: Mapping, config: Mapping) -> dict:
    """Observe exact common endpoint changes, never a release-time guess.

    Explicit timezone-aware available_at and received_at are required for both
    endpoints. A receipt today cannot prove a historical publication time.
    The result checks declarations only and remains unvalidated research.
    """
    start, end, max_age = _config(config)
    snapshot = snapshot if isinstance(snapshot, Mapping) else {}
    decision = _time(snapshot.get("decision_at"))
    series = snapshot.get("series")
    top_valid = (set(snapshot) == {"schema_version", "decision_at", "series"}
                 and snapshot.get("schema_version") == INPUT_VERSION and decision is not None
                 and isinstance(series, Mapping) and not set(series).difference(ROLES))
    series = series if isinstance(series, Mapping) else {}
    observations = {role: _observe_series(series.get(role), role, start, end, decision, max_age, top_valid)
                    for role in ROLES}
    identities = {}
    for role, item in observations.items():
        if item["source_id"] is not None and item["series_id"] is not None:
            identities.setdefault((item["source_id"], item["series_id"]), []).append(role)
    for repeated_roles in identities.values():
        if len(repeated_roles) > 1:
            for role in repeated_roles:
                item = observations[role]
                item.update(status="unknown", start_percent=None, end_percent=None, change_bp=None)
                item["reason_codes"] = sorted(set(item["reason_codes"] + ["ROLE_SOURCE_IDENTITY_AMBIGUOUS"]))
    spread = {"status": "unknown", "reason_codes": [], "measurement": "APPROXIMATE_NOMINAL_MINUS_REAL_YIELD_SPREAD",
              "source_id": None, "basis": None, "input_series_ids": [], "unit": "percent",
              "start_percent": None, "end_percent": None, "change_bp": None}
    nominal, real = observations["nominal_10y"], observations["real_10y"]
    if any(item["status"] != "declared_available" for item in (nominal, real)):
        spread["reason_codes"] = ["COMMON_WINDOW_UNAVAILABLE"]
    elif nominal["source_id"] != real["source_id"] or nominal["basis"] != real["basis"]:
        spread["reason_codes"] = ["SOURCE_OR_BASIS_MISMATCH"]
    else:
        first = _rounded(nominal["start_percent"] - real["start_percent"])
        last = _rounded(nominal["end_percent"] - real["end_percent"])
        change = None if first is None or last is None else _rounded(100 * (last - first))
        if change is None:
            spread["reason_codes"] = ["SPREAD_NONFINITE"]
        else:
            spread.update(status="declared_available", source_id=nominal["source_id"], basis=nominal["basis"],
                          input_series_ids=[nominal["series_id"], real["series_id"]],
                          start_percent=first, end_percent=last, change_bp=change)
    return {"schema_version": OBSERVATION_VERSION, "research_status": "UNVALIDATED_RESEARCH",
            "assurance": "CALLER_DECLARATIONS_AND_CONSISTENCY_ONLY", "historical_pit_verified": False,
            "backtest_eligible": False, "position_control_allowed": False,
            "decision_at": _stamp(decision), "window_start": start.isoformat(), "window_end": end.isoformat(),
            "window_method": "EXACT_ENDPOINT_DIFFERENCE", "coverage": "ENDPOINTS_ONLY_NOT_SESSION_COVERAGE",
            "max_observation_age_days": max_age, "series": observations, "approximate_yield_spread": spread,
            "quality": {"status": "declared_available" if all(item["status"] == "declared_available"
                         for item in observations.values()) and spread["status"] == "declared_available" else "unknown"}}


# V2 is explicit and separate: v1's entry point, constants and semantics above
# remain unchanged. These fields describe collector knowledge, not publication.
FORWARD_INPUT_VERSION = "qsl.rates-context-input.research.v2"
FORWARD_OBSERVATION_VERSION = "qsl.rates-context-observation.research.v2"
_FORWARD_BASIS = "collector_first_seen"
_FORWARD_ROOT_KEYS = {"schema_version", "availability_basis", "collector_id", "decision_at", "series"}
_FORWARD_ROW_KEYS = {"observation_date", "value", "revision_id", "source_published_at",
                     "first_seen_at", "received_at", "capture_sha256", "row_sha256"}


def _forward_time(value):
    # datetime.fromisoformat truncates excessive precision and normalizes some
    # invalid offsets. V2 accepts an exact microsecond-representable grammar.
    if not isinstance(value, str):
        return None
    if value.endswith("Z"):
        body = value[:-1]
    elif len(value) >= 6 and value[-6] in "+-" and value[-3] == ":":
        offset = value[-5:-3] + value[-2:]
        if not offset.isascii() or not offset.isdigit() or int(offset[:2]) > 23 or int(offset[2:]) > 59:
            return None
        body = value[:-6]
    else:
        return None
    whole, separator, fraction = body.partition(".")
    if len(whole) != 19 or (whole[4], whole[7], whole[10], whole[13], whole[16]) != ("-", "-", "T", ":", ":"):
        return None
    digits = whole[:4] + whole[5:7] + whole[8:10] + whole[11:13] + whole[14:16] + whole[17:19]
    if not digits.isascii() or not digits.isdigit():
        return None
    if separator and (not 1 <= len(fraction) <= 6 or not fraction.isascii() or not fraction.isdigit()):
        return None
    return _time(value)


def _forward_digest(value):
    return value if isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value) else None


def _forward_endpoint(row):
    if row is None:
        return None
    first_seen, received = _forward_time(row.get("first_seen_at")), _forward_time(row.get("received_at"))
    known = received if first_seen is not None and received is not None and received >= first_seen else None
    return {"observation_date": row["observation_date"], "source_published_at": None,
            "first_seen_at": _stamp(first_seen), "received_at": _stamp(received), "known_at": _stamp(known),
            "revision_id": _text(row.get("revision_id")), "capture_sha256": _forward_digest(row.get("capture_sha256")),
            "row_sha256": _forward_digest(row.get("row_sha256"))}


def _observe_forward_series(series, role, start, end, decision, max_age, top_valid):
    series = series if isinstance(series, Mapping) else {}
    result = {"status": "unknown", "reason_codes": [], "source_id": _text(series.get("source_id")),
              "series_id": _text(series.get("series_id")), "basis": _text(series.get("basis")),
              "declared_unit": _text(series.get("unit")), "unit": "percent", "start_percent": None,
              "end_percent": None, "change_bp": None, "start_observation": None, "end_observation": None,
              "latest_observation_date": None, "observation_age_days": None,
              "first_seen_delay_calendar_days": None, "consumer_receipt_lag_seconds": None,
              "visible_observations": 0}
    reasons = result["reason_codes"]
    if not top_valid:
        reasons.append("INPUT_INVALID")
        return result
    if not series:
        reasons.append("SERIES_MISSING")
        return result
    if set(series) != _SERIES_KEYS or result["source_id"] is None or result["series_id"] is None:
        reasons.append("SOURCE_IDENTITY_INVALID")
    allowed_basis = {"reported_breakeven"} if role == "breakeven_10y" else _YIELD_BASES
    if result["basis"] not in allowed_basis:
        reasons.append("BASIS_INVALID")
    if series.get("unit") != "percent":
        reasons.append("UNIT_NOT_PERCENT")
    rows = series.get("rows")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        reasons.append("ROWS_INVALID")
        return result
    visible, revisions, content_ids = [], {}, {}
    previous = None
    for row in rows:
        if not isinstance(row, Mapping) or (observed := _date(row.get("observation_date"))) is None:
            reasons.append("ROW_DATE_INVALID")
            continue
        if observed < start or observed > end or observed > decision.date():
            continue
        first_seen = _forward_time(row.get("first_seen_at"))
        if first_seen is not None and first_seen > decision:
            continue
        received = _forward_time(row.get("received_at"))
        if received is not None and received > decision:
            continue
        # Only selected rows can affect validation, counts, identity or output.
        if previous is not None and observed <= previous:
            reasons.append("ROW_ORDER_OR_REVISION_AMBIGUOUS")
        previous = observed
        visible.append(row)
        if set(row) != _FORWARD_ROW_KEYS:
            reasons.append("ROW_FIELDS_INVALID")
        if "source_published_at" not in row or row.get("source_published_at") is not None:
            reasons.append("SOURCE_PUBLICATION_MUST_BE_UNKNOWN")
        if first_seen is None:
            reasons.append("FIRST_SEEN_UNKNOWN")
        elif first_seen.date() < observed:
            reasons.append("FIRST_SEEN_BEFORE_OBSERVATION")
        if received is None:
            reasons.append("RECEIPT_UNKNOWN")
        elif first_seen is not None and received < first_seen:
            reasons.append("RECEIPT_BEFORE_FIRST_SEEN")
        revision = _text(row.get("revision_id"))
        if revision is None or revision == "latest":
            reasons.append("REVISION_IDENTITY_INVALID")
        capture_hash, row_hash = _forward_digest(row.get("capture_sha256")), _forward_digest(row.get("row_sha256"))
        if capture_hash is None:
            reasons.append("CAPTURE_IDENTITY_INVALID")
        if row_hash is None:
            reasons.append("ROW_CONTENT_IDENTITY_INVALID")
        value = _number(row.get("value"))
        if value is None:
            reasons.append("VALUE_INVALID")
        if revision is not None:
            identity = (observed.isoformat(), revision)
            content = (value, _stamp(first_seen), _stamp(received), capture_hash, row_hash)
            if identity in revisions and revisions[identity] != content:
                reasons.append("ROW_IDENTITY_CONFLICT")
            revisions[identity] = content
        if row_hash is not None:
            content = (observed.isoformat(), value)
            if row_hash in content_ids and content_ids[row_hash] != content:
                reasons.append("ROW_IDENTITY_CONFLICT")
            content_ids[row_hash] = content
    result["visible_observations"] = len(visible)
    first_rows = [row for row in visible if row["observation_date"] == start.isoformat()]
    last_rows = [row for row in visible if row["observation_date"] == end.isoformat()]
    # Ambiguity never selects first/last writer even for provenance display.
    first = first_rows[0] if len(first_rows) == 1 else None
    last = last_rows[0] if len(last_rows) == 1 else None
    result["start_observation"], result["end_observation"] = _forward_endpoint(first), _forward_endpoint(last)
    if not first_rows or not last_rows:
        reasons.append("WINDOW_ENDPOINT_UNAVAILABLE")
    if visible:
        latest = max(_date(row["observation_date"]) for row in visible)
        result["latest_observation_date"] = latest.isoformat()
        result["observation_age_days"] = (decision.date() - latest).days
        if result["observation_age_days"] > max_age:
            reasons.append("OBSERVATION_STALE")
    if last is not None:
        first_seen, received = _forward_time(last.get("first_seen_at")), _forward_time(last.get("received_at"))
        if first_seen is not None:
            result["first_seen_delay_calendar_days"] = (first_seen.date() - end).days
        if first_seen is not None and received is not None:
            result["consumer_receipt_lag_seconds"] = (received - first_seen).total_seconds()
    if not reasons:
        first_value, last_value = _number(first["value"]), _number(last["value"])
        change = _rounded(100 * (last_value - first_value))
        if change is None:
            reasons.append("CHANGE_NONFINITE")
        else:
            result.update(status="declared_available", start_percent=first_value,
                          end_percent=last_value, change_bp=change)
    result["reason_codes"] = sorted(set(reasons))
    return result


def build_rates_context_observation_v2(snapshot: Mapping, config: Mapping) -> dict:
    """Observe explicit collector-known inputs without asserting publication.

    The collector and per-row first-capture/content hashes are caller
    declarations. This stateless function does not authenticate timestamps,
    verify retained bytes, establish the earliest capture, or enforce stable
    first-seen records across calls. First-seen never becomes v1 available_at.
    """
    start, end, max_age = _config(config)
    snapshot = snapshot if isinstance(snapshot, Mapping) else {}
    decision = _forward_time(snapshot.get("decision_at"))
    collector = _text(snapshot.get("collector_id"))
    series = snapshot.get("series")
    top_valid = (set(snapshot) == _FORWARD_ROOT_KEYS and snapshot.get("schema_version") == FORWARD_INPUT_VERSION
                 and snapshot.get("availability_basis") == _FORWARD_BASIS and collector is not None
                 and decision is not None and isinstance(series, Mapping) and not set(series).difference(ROLES))
    series = series if isinstance(series, Mapping) else {}
    observations = {role: _observe_forward_series(series.get(role), role, start, end, decision, max_age, top_valid)
                    for role in ROLES}
    identities = {}
    for role, item in observations.items():
        if item["source_id"] is not None and item["series_id"] is not None:
            identities.setdefault((item["source_id"], item["series_id"]), []).append(role)
    for repeated_roles in identities.values():
        if len(repeated_roles) > 1:
            for role in repeated_roles:
                item = observations[role]
                item.update(status="unknown", start_percent=None, end_percent=None, change_bp=None)
                item["reason_codes"] = sorted(set(item["reason_codes"] + ["ROLE_SOURCE_IDENTITY_AMBIGUOUS"]))
    spread = {"status": "unknown", "reason_codes": [], "measurement": "APPROXIMATE_NOMINAL_MINUS_REAL_YIELD_SPREAD",
              "source_id": None, "basis": None, "input_series_ids": [], "unit": "percent",
              "start_percent": None, "end_percent": None, "change_bp": None}
    nominal, real = observations["nominal_10y"], observations["real_10y"]
    if any(item["status"] != "declared_available" for item in (nominal, real)):
        spread["reason_codes"] = ["COMMON_WINDOW_UNAVAILABLE"]
    elif nominal["source_id"] != real["source_id"] or nominal["basis"] != real["basis"]:
        spread["reason_codes"] = ["SOURCE_OR_BASIS_MISMATCH"]
    else:
        first = _rounded(nominal["start_percent"] - real["start_percent"])
        last = _rounded(nominal["end_percent"] - real["end_percent"])
        change = None if first is None or last is None else _rounded(100 * (last - first))
        if change is None:
            spread["reason_codes"] = ["SPREAD_NONFINITE"]
        else:
            spread.update(status="declared_available", source_id=nominal["source_id"], basis=nominal["basis"],
                          input_series_ids=[nominal["series_id"], real["series_id"]],
                          start_percent=first, end_percent=last, change_bp=change)
    return {"schema_version": FORWARD_OBSERVATION_VERSION, "availability_basis": _FORWARD_BASIS,
            "collector_id": collector, "research_status": "UNVALIDATED_RESEARCH",
            "assurance": "CALLER_DECLARATIONS_AND_CONSISTENCY_ONLY", "historical_pit_verified": False,
            "backtest_eligible": False, "position_control_allowed": False,
            "decision_at": _stamp(decision), "window_start": start.isoformat(), "window_end": end.isoformat(),
            "window_method": "EXACT_ENDPOINT_DIFFERENCE", "coverage": "ENDPOINTS_ONLY_NOT_SESSION_COVERAGE",
            "max_observation_age_days": max_age, "series": observations, "approximate_yield_spread": spread,
            "quality": {"status": "declared_available" if all(item["status"] == "declared_available"
                         for item in observations.values()) and spread["status"] == "declared_available" else "unknown"}}
