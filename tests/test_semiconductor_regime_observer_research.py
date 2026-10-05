"""Standard-library synthetic contract tests, never market-performance tests."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
import unittest

from quant_strategy_plugins.semiconductor_regime_observer_research import (
    CONFIG_VERSION,
    INPUT_VERSION,
    ContractError,
    build_semiconductor_regime_observation as build_observation,
    build_semiconductor_regime_signal_v2 as build_qsp_signal,
    semiconductor_regime_observer_config_sha256 as config_sha256,
    semiconductor_regime_observation_usable_at as usable_at,
    ENTRYPOINT,
    REPOSITORY,
)


from quant_strategy_plugins import semiconductor_regime_observer_research as candidate
from quant_strategy_plugins import qqq_price_regime_observer_v2 as qqq_observer
from quant_strategy_plugins.plugin_signal_envelope_v2 import validate_signal_envelope


HERE = Path(__file__).resolve().parent


def config(*, classify: bool = False) -> dict:
    """These small values are test fixtures; none is an operational default."""
    value = {
        "schema_version": CONFIG_VERSION,
        "sma_window_sessions": 3,
        "sma_slope_lag_sessions": 2,
        "path_window_returns": 5,
        "short_vol_window_returns": 2,
        "long_vol_window_returns": 5,
        "drawdown_window_sessions": 6,
        "annualization_sessions": 252,
        "ttl_seconds": 86400,
        "classification": None,
    }
    if classify:
        value["classification"] = {
            "hypothesis_id": "SYNTHETIC_FIXTURE_ONLY",
            "status": "UNVALIDATED_RESEARCH_HYPOTHESIS",
            "direction": {"price_distance_min": 0.001, "sma_slope_min": 0.001},
            "trendiness": {"range_efficiency_max": 0.2, "trend_efficiency_min": 0.8},
            "pressure": {
                "drawdown_normal_max": 0.03,
                "drawdown_stress_min": 0.1,
                "volatility_ratio_normal_max": 1.1,
                "volatility_ratio_stress_min": 1.5,
            },
        }
    return value


def stamp(session: str, hour: int = 20, minute: int = 1) -> str:
    return f"{session}T{hour:02}:{minute:02}:00Z"


def snapshot(prices=None, *, symbol="SOXX") -> dict:
    prices = prices if prices is not None else [100, 102, 104, 107, 109, 112]
    start = date(2026, 9, 21)
    sessions = [(start + timedelta(days=i)).isoformat() for i in (0, 1, 2, 3, 4, 7)]
    as_of = sessions[-1]
    availability = stamp(as_of)
    adjustment_availability = stamp(sessions[0], 12, 0)
    return {
        "schema_version": INPUT_VERSION,
        "symbol": symbol,
        "series_role": "SIGNAL_PROXY" if symbol == "SOXX" else "EXECUTION_BENCHMARK",
        "as_of": as_of,
        "available_at": availability,
        "decision_at": stamp(as_of, 21, 0),
        "calendar": {
            "id": "SYNTHETIC_XNYS",
            "version": "synthetic-calendar-v1",
            "available_at": stamp(sessions[0], 12, 0),
            "sessions": [{"date": d, "close_at": stamp(d, 20, 0), "complete": True} for d in sessions],
        },
        "adjustment": {
            "basis": "split_and_distribution_adjusted",
            "version": "synthetic-adjustment-v1",
            "available_at": adjustment_availability,
            "point_in_time_attested": True,
        },
        "components": {
            name: {"as_of": as_of, "available_at": available, "version": version}
            for name, available, version in (
                ("prices", availability, "synthetic-prices-producer-v1"),
                ("calendar", stamp(sessions[0], 12, 0), "synthetic-calendar-v1"),
                ("adjustment", adjustment_availability, "synthetic-adjustment-v1"),
            )
        },
        "bars": [
            {
                "symbol": symbol,
                "date": d,
                "close": p,
                "closed": True,
                "available_at": stamp(d),
                "adjustment_available_at": adjustment_availability,
                "adjustment_version": "synthetic-adjustment-v1",
            }
            for d, p in zip(sessions, prices)
        ],
    }


class ContractTests(unittest.TestCase):
    def assert_unknown_quality(self, data, reason):
        observed = build_observation(data, config(classify=True))
        self.assertEqual(observed["quality"]["status"], "unknown")
        self.assertIn(reason, observed["quality"]["reason_codes"])
        self.assertTrue(all(axis["state"] == "unknown" for axis in observed["axes"].values()))
        self.assertTrue(all(v is None for v in observed["features"].values()))
        self.assertNotIn("risk_off", json.dumps(observed))
        return observed

    def test_no_classification_is_the_normal_feature_only_mode(self):
        observed = build_observation(snapshot(), config())
        self.assertEqual(observed["quality"]["status"], "qualified_by_declaration")
        self.assertGreater(observed["features"]["sma_slope_per_session"], 0)
        self.assertEqual(observed["features"]["path_efficiency"], 1)
        for axis in observed["axes"].values():
            self.assertEqual(axis, {"state": "unknown", "reason_codes": ["CLASSIFICATION_NOT_CONFIGURED"]})

    def test_synthetic_direction_and_trendiness_are_independent_axes(self):
        up = build_observation(snapshot(), config(classify=True))
        down = build_observation(snapshot([112, 109, 107, 104, 102, 100]), config(classify=True))
        self.assertEqual(up["axes"]["direction"]["state"], "up")
        self.assertEqual(down["axes"]["direction"]["state"], "down")
        self.assertEqual(up["axes"]["trendiness"]["state"], "trend_like")
        alternating = build_observation(snapshot([100, 103, 100, 103, 100, 101]), config(classify=True))
        self.assertEqual(alternating["axes"]["trendiness"]["state"], "range_like")

    def test_market_pressure_classifications_use_only_market_features(self):
        normal = build_observation(snapshot([100, 100, 103, 103, 103, 103]), config(classify=True))
        stressed = build_observation(snapshot([100, 100, 100, 100, 130, 80]), config(classify=True))
        self.assertEqual(normal["axes"]["pressure"]["state"], "normal")
        self.assertEqual(stressed["axes"]["pressure"]["state"], "stressed")
        self.assertEqual(stressed["quality"]["status"], "qualified_by_declaration")

    def test_future_append_with_unusable_payload_is_completely_invisible(self):
        data = snapshot()
        before = build_observation(data, config(classify=True))
        after_data = copy.deepcopy(data)
        future_date = "2026-09-29"
        after_data["bars"].extend([
            {"date": future_date, "available_at": stamp(future_date), "close": float("nan"), "order": "ignored"},
            {"date": "2030-01-01", "available_at": "malformed", "close": object()},
        ])
        after_data["calendar"]["sessions"].append({"date": future_date, "close_at": "not-a-time"})
        after = build_observation(after_data, config(classify=True))
        self.assertEqual(before, after)
        self.assertEqual(before["input_sha256"], after["input_sha256"])

    def test_unavailable_historical_correction_does_not_change_identity(self):
        data = snapshot()
        before = build_observation(data, config())
        correction = copy.deepcopy(data["bars"][-1])
        correction["available_at"] = "2026-09-29T20:01:00Z"
        correction["close"] = 1e9
        data["bars"].append(correction)
        self.assertEqual(before, build_observation(data, config()))
        # Even absent/unrelated columns on that hidden revision must not leak.
        data["bars"].append({"date": data["as_of"], "available_at": "2030-01-01T00:00:00Z", "garbage": object()})
        self.assertEqual(before, build_observation(data, config()))

    def test_observation_availability_is_not_backdated_to_raw_input(self):
        observed = build_observation(snapshot(), config())
        self.assertEqual(observed["input_available_at"], "2026-09-28T20:01:00Z")
        self.assertEqual(observed["available_at"], observed["decision_at"])
        self.assertFalse(usable_at(observed, "2026-09-28T20:01:00Z"))
        self.assertTrue(usable_at(observed, observed["available_at"]))

    def test_late_required_bar_is_missing_at_historical_decision(self):
        data = snapshot()
        data["bars"][-1]["available_at"] = "2026-09-29T20:01:00Z"
        self.assert_unknown_quality(data, "SESSION_COVERAGE_INCOMPLETE")

    def test_snapshot_itself_not_available_at_decision(self):
        data = snapshot()
        data["available_at"] = "2026-09-29T20:01:00Z"
        self.assert_unknown_quality(data, "SNAPSHOT_UNAVAILABLE_AT_DECISION")

    def test_unclosed_and_incomplete_sessions_are_not_market_pressure(self):
        data = snapshot()
        data["bars"][-1]["closed"] = False
        self.assert_unknown_quality(data, "BAR_NOT_CLOSED")
        data = snapshot()
        data["calendar"]["sessions"][-1]["complete"] = False
        self.assert_unknown_quality(data, "SESSION_NOT_COMPLETE")
        data = snapshot()
        data["decision_at"] = "2026-09-28T19:00:00Z"
        self.assert_unknown_quality(data, "SESSION_NOT_CLOSED_AT_DECISION")

    def test_required_calendar_gap_and_missing_bar(self):
        data = snapshot()
        del data["bars"][2]
        self.assert_unknown_quality(data, "SESSION_COVERAGE_INCOMPLETE")
        data = snapshot()
        del data["calendar"]["sessions"][2]
        self.assert_unknown_quality(data, "INSUFFICIENT_CALENDAR_HISTORY")

    def test_adjustment_attestation_and_availability_are_required(self):
        for field, value, reason in (
            ("point_in_time_attested", False, "ADJUSTMENT_PIT_NOT_ATTESTED"),
            ("basis", "unspecified", "ADJUSTMENT_BASIS_UNSUPPORTED"),
            ("available_at", "2026-09-29T00:00:00Z", "ADJUSTMENT_UNAVAILABLE_AT_DECISION"),
        ):
            data = snapshot()
            data["adjustment"][field] = value
            self.assert_unknown_quality(data, reason)
        data = snapshot()
        data["bars"][-1]["adjustment_available_at"] = "2026-09-29T00:00:00Z"
        self.assert_unknown_quality(data, "SESSION_COVERAGE_INCOMPLETE")

    def test_component_dates_and_versions_must_bind(self):
        data = snapshot()
        data["components"]["prices"]["as_of"] = "2026-09-25"
        self.assert_unknown_quality(data, "COMPONENT_AS_OF_MISMATCH")
        data = snapshot()
        data["components"]["calendar"]["version"] = "different-calendar"
        self.assert_unknown_quality(data, "COMPONENT_VERSION_MISMATCH")
        data = snapshot()
        data["components"]["adjustment"]["available_at"] = "2026-09-29T00:00:00Z"
        self.assert_unknown_quality(data, "COMPONENT_UNAVAILABLE_AT_DECISION")

    def test_nonfinite_nonpositive_bool_and_missing_values_fail_closed(self):
        for value in (float("nan"), float("inf"), -float("inf"), 0, -1, True, None, "100"):
            with self.subTest(value=repr(value)):
                data = snapshot()
                data["bars"][2]["close"] = value
                self.assert_unknown_quality(data, "CLOSE_INVALID")

    def test_duplicate_unsorted_dates_and_symbol_mismatch_fail_closed(self):
        data = snapshot()
        data["bars"].insert(2, copy.deepcopy(data["bars"][1]))
        self.assert_unknown_quality(data, "BAR_DATES_NOT_STRICTLY_INCREASING")
        data = snapshot()
        data["bars"][1], data["bars"][2] = data["bars"][2], data["bars"][1]
        self.assert_unknown_quality(data, "BAR_DATES_NOT_STRICTLY_INCREASING")
        data = snapshot()
        data["bars"][0]["symbol"] = "QQQ"
        self.assert_unknown_quality(data, "BAR_SYMBOL_MISMATCH")

    def test_calendar_duplicates_and_disordered_dates_fail_closed(self):
        data = snapshot()
        data["calendar"]["sessions"].insert(1, copy.deepcopy(data["calendar"]["sessions"][0]))
        self.assert_unknown_quality(data, "CALENDAR_DATES_NOT_STRICTLY_INCREASING")
        data = snapshot()
        data["calendar"]["sessions"].reverse()
        self.assert_unknown_quality(data, "CALENDAR_DATES_NOT_STRICTLY_INCREASING")

    def test_calendar_identity_and_explicit_timezone_are_required(self):
        data = snapshot()
        data["calendar"]["version"] = "latest"
        self.assert_unknown_quality(data, "CALENDAR_ID_VERSION_REQUIRED")
        data = snapshot()
        data["decision_at"] = "2026-09-28T21:00:00"
        self.assert_unknown_quality(data, "OBSERVATION_TIMES_INVALID")

    def test_snapshot_cannot_claim_availability_before_a_used_component(self):
        data = snapshot()
        data["available_at"] = "2026-09-28T20:00:00Z"
        self.assert_unknown_quality(data, "SNAPSHOT_AVAILABILITY_PRECEDES_INPUT")
        data = snapshot()
        data["bars"][-1]["available_at"] = "2026-09-28T19:00:00Z"
        self.assert_unknown_quality(data, "BAR_AVAILABLE_BEFORE_CLOSE")

    def test_missing_nonnumeric_identity_does_not_crash_unknown_path(self):
        self.assert_unknown_quality(None, "INPUT_FIELDS_INVALID")
        for value in (None, [], {}, True):
            data = snapshot()
            data["symbol"] = value
            self.assert_unknown_quality(data, "SYMBOL_ROLE_UNSUPPORTED")
        self.assertFalse(usable_at({"quality": None}, "2026-09-28T21:00:00Z"))

    def test_finite_extreme_prices_cannot_emit_nonfinite_features(self):
        self.assert_unknown_quality(snapshot([1e-300, 1e308, 1e-300, 1e308, 1e-300, 1e308]), "FEATURE_COMPUTATION_UNDEFINED")

    def test_zero_variation_is_qualified_data_with_undefined_market_features(self):
        observed = build_observation(snapshot([100] * 6), config(classify=True))
        self.assertEqual(observed["quality"]["status"], "qualified_by_declaration")
        self.assertEqual(observed["features"]["long_realized_volatility_annualized"], 0)
        self.assertIsNone(observed["features"]["volatility_ratio"])
        self.assertIsNone(observed["features"]["path_efficiency"])
        self.assertEqual(observed["axes"]["pressure"]["reason_codes"], ["ZERO_LONG_VOLATILITY"])
        self.assertEqual(observed["axes"]["trendiness"]["reason_codes"], ["ZERO_PATH_VARIATION"])

    def test_conflicting_direction_features_return_unknown_not_a_vote(self):
        observed = build_observation(snapshot([100, 120, 120, 110, 110, 115]), config(classify=True))
        self.assertGreater(observed["features"]["close_to_sma_ratio"], 0)
        self.assertLess(observed["features"]["sma_slope_per_session"], 0)
        self.assertEqual(observed["axes"]["direction"], {"state": "unknown", "reason_codes": ["DIRECTION_FEATURE_CONFLICT"]})

    def test_conflicting_pressure_features_return_unknown_without_data_failure(self):
        observed = build_observation(snapshot([120, 115, 100, 100, 100, 100]), config(classify=True))
        self.assertEqual(observed["quality"]["status"], "qualified_by_declaration")
        self.assertEqual(observed["axes"]["pressure"], {"state": "unknown", "reason_codes": ["PRESSURE_FEATURE_CONFLICT"]})

    def test_ttl_boundary_and_late_replay_never_refresh_old_signal(self):
        observed = build_observation(snapshot(), config(classify=True))
        self.assertEqual(observed["valid_until"], "2026-09-29T20:00:00Z")
        self.assertTrue(usable_at(observed, "2026-09-29T19:59:59Z"))
        self.assertFalse(usable_at(observed, "2026-09-29T20:00:00Z"))
        data = snapshot()
        data["decision_at"] = "2026-10-01T20:00:00Z"
        replayed = self.assert_unknown_quality(data, "OBSERVATION_EXPIRED")
        self.assertEqual(replayed["valid_until"], observed["valid_until"])

    def test_no_lookback_or_classifier_production_defaults(self):
        with self.assertRaises(ContractError):
            build_observation(snapshot(), {})
        bad = config(classify=True)
        bad["classification"]["status"] = "CALIBRATED"
        with self.assertRaises(ContractError):
            build_observation(snapshot(), bad)
        bad = config()
        bad["target_weight"] = 1.0
        with self.assertRaises(ContractError):
            build_observation(snapshot(), bad)
        for invalid in (float("nan"), float("inf"), True, "0.1"):
            bad = config(classify=True)
            bad["classification"]["direction"]["sma_slope_min"] = invalid
            with self.assertRaises(ContractError):
                build_observation(snapshot(), bad)

    def test_missing_input_evidence_and_unknown_control_fields_fail_closed(self):
        for key in ("calendar", "adjustment", "available_at", "components", "decision_at"):
            data = snapshot()
            del data[key]
            self.assert_unknown_quality(data, "INPUT_FIELDS_INVALID")
        data = snapshot()
        data["authorization"] = True
        self.assert_unknown_quality(data, "INPUT_FIELDS_INVALID")

    def test_qqq_cannot_substitute_for_semiconductor_signal(self):
        self.assert_unknown_quality(snapshot(symbol="QQQ"), "SYMBOL_ROLE_UNSUPPORTED")
        soxl = build_observation(snapshot(symbol="SOXL"), config())
        self.assertEqual(soxl["series_role"], "EXECUTION_BENCHMARK")
        data = snapshot(symbol="SOXX")
        data["series_role"] = "EXECUTION_BENCHMARK"
        self.assert_unknown_quality(data, "SYMBOL_ROLE_UNSUPPORTED")

    def test_feature_calculation_matches_existing_qqq_observer_facts(self):
        observer = qqq_observer
        data = snapshot()
        existing = observer.build_qqq_price_regime_observation(
            qqq_bars=[{"date": b["date"], "close": b["close"]} for b in data["bars"]],
            as_of=data["as_of"],
            config={
                "schema_version": observer.CONFIG_SCHEMA_VERSION, "symbol": "QQQ",
                "trend_window_sessions": 3, "short_realized_volatility_window_sessions": 2,
                "long_realized_volatility_window_sessions": 5, "drawdown_window_sessions": 6,
                "annualization_sessions": 252,
            },
        )
        features = build_observation(data, config())["features"]
        for ours, theirs in (
            ("close_to_sma_ratio", "close_to_trend_mean_ratio"),
            ("short_realized_volatility_annualized", "short_realized_volatility_annualized"),
            ("long_realized_volatility_annualized", "long_realized_volatility_annualized"),
            ("trailing_drawdown_ratio", "trailing_drawdown_ratio"),
        ):
            self.assertAlmostEqual(features[ours], existing["facts"][theirs], places=11)

    def test_existing_qsp_v2_builder_accepts_observation_without_control_fields(self):
        observed = build_observation(snapshot(), config())
        producer = {
            "repo": REPOSITORY,
            # Synthetic immutable fixture, not a published candidate revision.
            "revision": "a" * 40,
            "entrypoint": ENTRYPOINT,
            "code_sha256": hashlib.sha256(Path(candidate.__file__).read_bytes()).hexdigest(),
            "config_sha256": config_sha256(config()),
        }
        provenance = {"p1_manifest_sha256": "b" * 64, "input_root_sha256": observed["input_sha256"], "date_cutoff": observed["as_of"]}
        envelope = build_qsp_signal(snapshot=snapshot(), config=config(), producer=producer, input_provenance=provenance)
        self.assertEqual(validate_signal_envelope(envelope), envelope)
        self.assertEqual(envelope["input"]["input_root_sha256"], observed["input_sha256"])
        serialized = json.dumps(envelope)
        for forbidden in ("target_weight", "capital", "order", "authorization", "existingV2"):
            self.assertNotIn(forbidden, serialized)
        bad_producer = {**producer, "config_sha256": "0" * 64}
        with self.assertRaises(ContractError):
            build_qsp_signal(snapshot=snapshot(), config=config(), producer=bad_producer, input_provenance=provenance)


    def test_research_entrypoint_rejects_wrong_producer_or_causal_root(self):
        observed = build_observation(snapshot(), config())
        producer = {
            "repo": REPOSITORY, "revision": "a" * 40, "entrypoint": ENTRYPOINT,
            "code_sha256": "c" * 64, "config_sha256": config_sha256(config()),
        }
        provenance = {"p1_manifest_sha256": "b" * 64, "input_root_sha256": observed["input_sha256"], "date_cutoff": observed["as_of"]}
        for field, value in (("repo", "Example/OtherRepo"), ("entrypoint", "other_module:build_signal")):
            with self.subTest(field=field), self.assertRaises(ContractError):
                build_qsp_signal(snapshot=snapshot(), config=config(), producer={**producer, field: value}, input_provenance=provenance)
        for field, value in (("input_root_sha256", "0" * 64), ("date_cutoff", "2026-09-25"), ("p1_manifest_sha256", "")):
            with self.subTest(field=field), self.assertRaises(ContractError):
                build_qsp_signal(snapshot=snapshot(), config=config(), producer=producer, input_provenance={**provenance, field: value})
        with self.assertRaises(ContractError):
            build_qsp_signal(snapshot=snapshot(), config=config(), producer=producer, input_provenance={**provenance, "authorization": True})

    def test_pure_repeatability_and_no_input_mutation(self):
        data, cfg = snapshot(), config(classify=True)
        original = copy.deepcopy((data, cfg))
        first = build_observation(data, cfg)
        self.assertEqual(first, build_observation(data, cfg))
        self.assertEqual((data, cfg), original)
        json.dumps(first, allow_nan=False)

    def test_price_scale_changes_input_identity_but_not_dimensionless_evidence(self):
        original = snapshot()
        observed = build_observation(original, config(classify=True))
        for multiplier in (0.1, 10.0, 1000.0):
            data = copy.deepcopy(original)
            for bar in data["bars"]:
                bar["close"] *= multiplier
            scaled = build_observation(data, config(classify=True))
            self.assertEqual(observed["features"], scaled["features"])
            self.assertEqual(observed["axes"], scaled["axes"])
            self.assertNotEqual(observed["input_sha256"], scaled["input_sha256"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
