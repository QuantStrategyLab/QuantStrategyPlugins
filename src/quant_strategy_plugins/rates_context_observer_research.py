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
