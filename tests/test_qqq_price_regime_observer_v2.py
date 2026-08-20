from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta

import pytest

from quant_strategy_plugins.plugin_signal_envelope_v2 import validate_signal_envelope
from quant_strategy_plugins.qqq_price_regime_observer_v2 import (
    DEFAULT_CONFIG,
    ENTRYPOINT,
    OBSERVATION_SCHEMA_VERSION,
    PLUGIN_ID,
    QqqPriceRegimeObserverError,
    REPOSITORY,
    build_qqq_price_regime_observation,
    build_qqq_price_regime_signal_v2,
    qqq_price_regime_observer_config_sha256,
)


def _bars(*, count: int = 260, final_multiplier: float = 1.0) -> list[dict[str, object]]:
    start = date(2025, 1, 1)
    values: list[dict[str, object]] = []
    for index in range(count):
        # Deterministic variation gives non-zero short and long realized volatility.
        close = (100.0 + index * 0.15) * (1.0 + ((index % 7) - 3) * 0.002)
        if index == count - 1:
            close *= final_multiplier
        values.append({"date": (start + timedelta(days=index)).isoformat(), "close": close})
    return values


def _producer(config: dict[str, object]) -> dict[str, object]:
    return {
        "repo": REPOSITORY,
        "revision": "a" * 40,
        "entrypoint": ENTRYPOINT,
        "code_sha256": "b" * 64,
        "config_sha256": qqq_price_regime_observer_config_sha256(config),
    }


def _input(as_of: str) -> dict[str, object]:
    return {
        "p1_manifest_sha256": "c" * 64,
        "input_root_sha256": "d" * 64,
        "date_cutoff": as_of,
    }


def test_builds_a_close_only_deterministic_observation_with_no_action_fields() -> None:
    bars = _bars()
    observation = build_qqq_price_regime_observation(
        qqq_bars=bars,
        as_of=str(bars[-1]["date"]),
    )

    assert observation["schema_version"] == OBSERVATION_SCHEMA_VERSION
    assert observation["symbol"] == "QQQ"
    assert observation["quality"] == {
        "observed_sessions": 260,
        "minimum_required_sessions": 253,
        "last_session_matches_as_of": True,
    }
    assert observation["facts"]["trend_state"] == "AT_OR_ABOVE_TREND_MEAN"
    assert observation["facts"]["short_realized_volatility_annualized"] >= 0.0
    assert observation["facts"]["long_realized_volatility_annualized"] >= 0.0
    assert "target_weight" not in str(observation)
    assert "order" not in str(observation)


def test_same_bars_and_config_create_one_valid_v2_envelope() -> None:
    bars = _bars()
    as_of = str(bars[-1]["date"])
    envelope = build_qqq_price_regime_signal_v2(
        qqq_bars=bars,
        as_of=as_of,
        config=DEFAULT_CONFIG,
        producer=_producer(DEFAULT_CONFIG),
        input_provenance=_input(as_of),
    )

    assert validate_signal_envelope(envelope) == envelope
    assert envelope["plugin_id"] == PLUGIN_ID
    assert envelope["payload"]["as_of"] == as_of
    assert envelope["payload"]["reason_codes"] == build_qqq_price_regime_signal_v2(
        qqq_bars=bars,
        as_of=as_of,
        config=DEFAULT_CONFIG,
        producer=_producer(DEFAULT_CONFIG),
        input_provenance=_input(as_of),
    )["payload"]["reason_codes"]


@pytest.mark.parametrize(
    ("mutator", "code"),
    [
        (lambda bars: bars.pop(), "as_of_mismatch"),
        (lambda bars: bars.__setitem__(20, {"date": bars[19]["date"], "close": 101.0}), "invalid_bars"),
        (lambda bars: bars.__setitem__(-1, {"date": bars[-1]["date"], "close": 0.0}), "invalid_bars"),
    ],
)
def test_rejects_missing_unsorted_or_invalid_close_history(mutator, code: str) -> None:
    bars = _bars()
    as_of = str(bars[-1]["date"])
    mutator(bars)

    with pytest.raises(QqqPriceRegimeObserverError, match=code):
        build_qqq_price_regime_observation(qqq_bars=bars, as_of=as_of)


def test_rejects_hidden_config_knobs_and_insufficient_history() -> None:
    unsafe_config = dict(DEFAULT_CONFIG)
    unsafe_config["target_weight"] = 0.5

    with pytest.raises(QqqPriceRegimeObserverError, match="invalid_config"):
        build_qqq_price_regime_observation(qqq_bars=_bars(), as_of="2025-09-17", config=unsafe_config)
    with pytest.raises(QqqPriceRegimeObserverError, match="insufficient_history"):
        short = _bars(count=252)
        build_qqq_price_regime_observation(qqq_bars=short, as_of=str(short[-1]["date"]))


def test_rejects_producer_or_p1_cutoff_that_cannot_describe_this_signal() -> None:
    bars = _bars()
    as_of = str(bars[-1]["date"])
    bad_producer = _producer(DEFAULT_CONFIG)
    bad_producer["config_sha256"] = "0" * 64

    with pytest.raises(QqqPriceRegimeObserverError, match="producer_config_mismatch"):
        build_qqq_price_regime_signal_v2(
            qqq_bars=bars,
            as_of=as_of,
            config=DEFAULT_CONFIG,
            producer=bad_producer,
            input_provenance=_input(as_of),
        )
    with pytest.raises(QqqPriceRegimeObserverError, match="input_cutoff_mismatch"):
        build_qqq_price_regime_signal_v2(
            qqq_bars=bars,
            as_of=as_of,
            config=DEFAULT_CONFIG,
            producer=_producer(DEFAULT_CONFIG),
            input_provenance=_input("2025-09-16"),
        )


def test_a_lower_final_close_changes_only_observation_facts_not_its_authority_boundary() -> None:
    baseline = _bars()
    lower_final_close = deepcopy(baseline)
    lower_final_close[-1]["close"] = float(lower_final_close[-1]["close"]) * 0.8
    as_of = str(baseline[-1]["date"])

    baseline_observation = build_qqq_price_regime_observation(qqq_bars=baseline, as_of=as_of)
    lower_observation = build_qqq_price_regime_observation(qqq_bars=lower_final_close, as_of=as_of)

    assert baseline_observation["facts"]["trend_state"] == "AT_OR_ABOVE_TREND_MEAN"
    assert lower_observation["facts"]["trend_state"] == "BELOW_TREND_MEAN"
    assert set(lower_observation) == set(baseline_observation)
