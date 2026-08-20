"""Pure close-only QQQ observation signal for the V2 plugin envelope.

This module deliberately has no data-provider, file, cloud, scheduler, broker,
strategy, or runtime dependency.  A caller supplies an already verified QQQ
bar sequence plus immutable P1 provenance.  The result describes deterministic
market facts only; it cannot select targets, trades, capital, or authority.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

from .plugin_signal_envelope_v2 import build_signal_envelope, canonical_json_bytes


PLUGIN_ID = "qqq_price_regime_observer"
REPOSITORY = "QuantStrategyLab/QuantStrategyPlugins"
ENTRYPOINT = "quant_strategy_plugins.qqq_price_regime_observer_v2:build_qqq_price_regime_signal_v2"
OBSERVATION_SCHEMA_VERSION = "qsl.qqq-price-regime-observation.v1"
CONFIG_SCHEMA_VERSION = "qsl.qqq-price-regime-observer-config.v1"

DEFAULT_CONFIG: dict[str, object] = {
    "schema_version": CONFIG_SCHEMA_VERSION,
    "symbol": "QQQ",
    "trend_window_sessions": 200,
    "short_realized_volatility_window_sessions": 5,
    "long_realized_volatility_window_sessions": 252,
    "drawdown_window_sessions": 252,
    "annualization_sessions": 252,
}

_CONFIG_FIELDS = frozenset(DEFAULT_CONFIG)
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")


class QqqPriceRegimeObserverError(ValueError):
    """Raised for an invalid observation input without exposing the input."""


def _fail(code: str) -> None:
    raise QqqPriceRegimeObserverError(code)


def _exact_date(value: object) -> str:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        _fail("invalid_date")
    try:
        if date.fromisoformat(value).isoformat() != value:
            _fail("invalid_date")
    except ValueError:
        _fail("invalid_date")
    return value


def _positive_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        _fail("invalid_config")
    return value


def validate_qqq_price_regime_observer_config(value: Mapping[str, object]) -> dict[str, object]:
    """Return the exact calculation configuration, rejecting hidden knobs."""

    if not isinstance(value, Mapping) or set(value) != _CONFIG_FIELDS:
        _fail("invalid_config")
    if value["schema_version"] != CONFIG_SCHEMA_VERSION or value["symbol"] != "QQQ":
        _fail("invalid_config")
    normalized = {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "symbol": "QQQ",
        "trend_window_sessions": _positive_int(value["trend_window_sessions"]),
        "short_realized_volatility_window_sessions": _positive_int(
            value["short_realized_volatility_window_sessions"]
        ),
        "long_realized_volatility_window_sessions": _positive_int(
            value["long_realized_volatility_window_sessions"]
        ),
        "drawdown_window_sessions": _positive_int(value["drawdown_window_sessions"]),
        "annualization_sessions": _positive_int(value["annualization_sessions"]),
    }
    if normalized["short_realized_volatility_window_sessions"] > normalized[
        "long_realized_volatility_window_sessions"
    ]:
        _fail("invalid_config")
    return normalized


def qqq_price_regime_observer_config_sha256(value: Mapping[str, object]) -> str:
    """Return the canonical digest that a P2 record must pin for this signal."""

    return hashlib.sha256(canonical_json_bytes(validate_qqq_price_regime_observer_config(value))).hexdigest()


def qqq_price_regime_observer_code_sha256() -> str:
    """Return the installed module bytes digest for a future independent P3 check."""

    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError as exc:  # pragma: no cover - only a damaged package install can reach this.
        raise QqqPriceRegimeObserverError("unavailable_module_source") from exc


def _normalized_bars(value: object, *, as_of: str) -> list[tuple[str, float]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        _fail("invalid_bars")
    normalized: list[tuple[str, float]] = []
    previous: str | None = None
    for bar in value:
        if not isinstance(bar, Mapping):
            _fail("invalid_bars")
        session = _exact_date(bar.get("date"))
        close = bar.get("close")
        if not isinstance(close, (int, float)) or isinstance(close, bool):
            _fail("invalid_bars")
        close = float(close)
        if not math.isfinite(close) or close <= 0.0 or (previous is not None and session <= previous):
            _fail("invalid_bars")
        normalized.append((session, close))
        previous = session
    if not normalized or normalized[-1][0] != as_of:
        _fail("as_of_mismatch")
    return normalized


def _rounded(value: float) -> float:
    result = round(value, 12)
    return 0.0 if result == 0.0 else result


def _annualized_volatility(returns: Sequence[float], annualization_sessions: int) -> float:
    mean = math.fsum(returns) / len(returns)
    variance = math.fsum((item - mean) ** 2 for item in returns) / len(returns)
    return math.sqrt(variance * annualization_sessions)


def build_qqq_price_regime_observation(
    *,
    qqq_bars: Sequence[Mapping[str, object]],
    as_of: str,
    config: Mapping[str, object] = DEFAULT_CONFIG,
) -> dict[str, object]:
    """Compute deterministic QQQ close-only facts from bars ending exactly at ``as_of``.

    It uses no forward rows: every statistic ends at the supplied completed
    session.  The output intentionally contains only derived ratios/states and
    reason codes, never close rows, portfolio targets, or trade instructions.
    """

    cutoff = _exact_date(as_of)
    frozen_config = validate_qqq_price_regime_observer_config(config)
    bars = _normalized_bars(qqq_bars, as_of=cutoff)
    close = [item[1] for item in bars]
    trend_window = int(frozen_config["trend_window_sessions"])
    short_window = int(frozen_config["short_realized_volatility_window_sessions"])
    long_window = int(frozen_config["long_realized_volatility_window_sessions"])
    drawdown_window = int(frozen_config["drawdown_window_sessions"])
    annualization = int(frozen_config["annualization_sessions"])
    required_sessions = max(trend_window, short_window + 1, long_window + 1, drawdown_window)
    if len(close) < required_sessions:
        _fail("insufficient_history")

    trend_mean = math.fsum(close[-trend_window:]) / trend_window
    close_to_trend_mean_ratio = close[-1] / trend_mean - 1.0
    returns = [later / earlier - 1.0 for earlier, later in zip(close, close[1:])]
    short_volatility = _annualized_volatility(returns[-short_window:], annualization)
    long_volatility = _annualized_volatility(returns[-long_window:], annualization)
    trailing_peak = max(close[-drawdown_window:])
    trailing_drawdown_ratio = close[-1] / trailing_peak - 1.0
    trend_state = "AT_OR_ABOVE_TREND_MEAN" if close_to_trend_mean_ratio >= 0.0 else "BELOW_TREND_MEAN"
    volatility_state = (
        "SHORT_AT_OR_ABOVE_LONG" if short_volatility >= long_volatility else "SHORT_BELOW_LONG"
    )
    reason_codes = [f"QQQ_TREND_{trend_state}", f"QQQ_VOLATILITY_{volatility_state}"]
    if trailing_drawdown_ratio < 0.0:
        reason_codes.append("QQQ_TRAILING_DRAWDOWN_PRESENT")
    return {
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "as_of": cutoff,
        "symbol": "QQQ",
        "method": "CLOSE_ONLY_TRAILING_FACTS",
        "lookbacks": {
            "trend_window_sessions": trend_window,
            "short_realized_volatility_window_sessions": short_window,
            "long_realized_volatility_window_sessions": long_window,
            "drawdown_window_sessions": drawdown_window,
            "annualization_sessions": annualization,
        },
        "facts": {
            "close_to_trend_mean_ratio": _rounded(close_to_trend_mean_ratio),
            "trend_state": trend_state,
            "short_realized_volatility_annualized": _rounded(short_volatility),
            "long_realized_volatility_annualized": _rounded(long_volatility),
            "volatility_state": volatility_state,
            "trailing_drawdown_ratio": _rounded(trailing_drawdown_ratio),
        },
        "quality": {
            "observed_sessions": len(close),
            "minimum_required_sessions": required_sessions,
            "last_session_matches_as_of": True,
        },
        "reason_codes": reason_codes,
    }


def build_qqq_price_regime_signal_v2(
    *,
    qqq_bars: Sequence[Mapping[str, object]],
    as_of: str,
    config: Mapping[str, object],
    producer: Mapping[str, object],
    input_provenance: Mapping[str, object],
) -> dict[str, object]:
    """Build a validated V2 envelope for one immutable P1-bound observation."""

    cutoff = _exact_date(as_of)
    frozen_config = validate_qqq_price_regime_observer_config(config)
    if not isinstance(producer, Mapping) or producer.get("repo") != REPOSITORY:
        _fail("invalid_producer")
    if producer.get("entrypoint") != ENTRYPOINT:
        _fail("invalid_producer")
    if producer.get("config_sha256") != qqq_price_regime_observer_config_sha256(frozen_config):
        _fail("producer_config_mismatch")
    if not isinstance(input_provenance, Mapping) or input_provenance.get("date_cutoff") != cutoff:
        _fail("input_cutoff_mismatch")
    return build_signal_envelope(
        plugin_id=PLUGIN_ID,
        producer=producer,
        input_provenance=input_provenance,
        payload=build_qqq_price_regime_observation(
            qqq_bars=qqq_bars,
            as_of=cutoff,
            config=frozen_config,
        ),
    )
