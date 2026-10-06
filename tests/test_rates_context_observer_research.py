"""SYNTHETIC_FIXTURE_ONLY: no downloaded values or provider calls."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import unittest


_SOURCE = Path(__file__).parents[1] / "src/quant_strategy_plugins/rates_context_observer_research.py"
_SPEC = importlib.util.spec_from_file_location("rates_context_observer_research", _SOURCE)
observer = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(observer)


def fixture():
    # Arbitrary synthetic percentages, deliberately unrelated to provider data.
    series = {}
    for role, values in (("nominal_10y", (4.0, 4.2)), ("real_10y", (1.0, 1.1)),
                         ("breakeven_10y", (2.8, 2.9))):
        rows = []
        for day, value, published in (("2024-01-02", values[0], "2024-01-03T13:00:00Z"),
                                     ("2024-01-03", values[1], "2024-01-04T13:00:00Z")):
            rows.append({"observation_date": day, "value": value, "available_at": published,
                         "received_at": published.replace(":00:00", ":01:00"), "revision_id": "synthetic-v1"})
        series[role] = {"source_id": "SYNTHETIC_FIXTURE_ONLY:rates", "series_id": role,
                        "basis": "reported_breakeven" if role == "breakeven_10y" else "treasury_par_yield",
                        "unit": "percent", "rows": rows}
    return {"schema_version": observer.INPUT_VERSION, "decision_at": "2024-01-04T15:00:00Z",
            "series": series}


def config():
    return {"schema_version": observer.CONFIG_VERSION, "window_start": "2024-01-02",
            "window_end": "2024-01-03", "max_observation_age_days": 2}


class RatesContextObserverTests(unittest.TestCase):
    def build(self, snapshot=None, policy=None):
        return observer.build_rates_context_observation(fixture() if snapshot is None else snapshot,
                                                        config() if policy is None else policy)

    def assert_unknown(self, snapshot, role="nominal_10y"):
        result = self.build(snapshot)
        self.assertEqual(result["series"][role]["status"], "unknown")
        self.assertIsNone(result["series"][role]["change_bp"])
        return result

    def test_percent_change_is_basis_points_not_relative_return(self):
        result = self.build()
        self.assertEqual(result["series"]["nominal_10y"]["change_bp"], 20.0)
        self.assertEqual(result["series"]["real_10y"]["change_bp"], 10.0)
        self.assertEqual(result["approximate_yield_spread"]["end_percent"], 3.1)
        self.assertEqual(result["approximate_yield_spread"]["change_bp"], 10.0)

    def test_independent_reported_breakeven_is_not_replaced_by_difference(self):
        result = self.build()
        self.assertEqual(result["series"]["breakeven_10y"]["end_percent"], 2.9)
        self.assertEqual(result["approximate_yield_spread"]["end_percent"], 3.1)
        self.assertEqual(result["research_status"], "UNVALIDATED_RESEARCH")
        self.assertFalse(result["historical_pit_verified"])

    def test_source_dates_and_per_series_update_lag_preserved(self):
        snapshot = fixture()
        snapshot["series"]["real_10y"]["rows"][-1]["available_at"] = "2024-01-03T17:00:00Z"
        result = self.build(snapshot)
        nominal, real = (result["series"][role] for role in ("nominal_10y", "real_10y"))
        self.assertEqual(nominal["observation_age_days"], 1)
        self.assertEqual(nominal["availability_delay_calendar_days"], 1)
        self.assertEqual(real["availability_delay_calendar_days"], 0)
        self.assertEqual(nominal["end_observation"]["observation_date"], "2024-01-03")
        self.assertEqual(nominal["end_observation"]["revision_id"], "synthetic-v1")

    def test_negative_real_rates_are_valid(self):
        snapshot = fixture()
        snapshot["series"]["real_10y"]["rows"][0]["value"] = -1.0
        snapshot["series"]["real_10y"]["rows"][1]["value"] = -0.5
        result = self.build(snapshot)
        self.assertEqual(result["series"]["real_10y"]["change_bp"], 50.0)

    def test_missing_series_is_explicit_unknown(self):
        snapshot = fixture()
        del snapshot["series"]["nominal_10y"]
        self.assert_unknown(snapshot)

    def test_missing_available_at_is_not_replaced_by_received_today(self):
        snapshot = fixture()
        snapshot["series"]["nominal_10y"]["rows"][0]["available_at"] = None
        result = self.assert_unknown(snapshot)
        self.assertIn("AVAILABILITY_UNKNOWN", result["series"]["nominal_10y"]["reason_codes"])

    def test_importing_old_history_today_does_not_establish_pit(self):
        snapshot = fixture()
        for row in snapshot["series"]["nominal_10y"]["rows"]:
            row["available_at"] = None
            row["received_at"] = "2024-01-04T14:00:00Z"
        self.assert_unknown(snapshot)

    def test_future_availability_is_invisible_to_historical_decision(self):
        snapshot = fixture()
        snapshot["series"]["nominal_10y"]["rows"][-1]["available_at"] = "2024-01-05T13:00:00Z"
        self.assert_unknown(snapshot)

    def test_future_receipt_is_not_consumable(self):
        snapshot = fixture()
        snapshot["series"]["nominal_10y"]["rows"][-1]["received_at"] = "2024-01-05T13:01:00Z"
        self.assert_unknown(snapshot)

    def test_missing_receipt_is_unknown(self):
        snapshot = fixture()
        snapshot["series"]["nominal_10y"]["rows"][-1]["received_at"] = None
        self.assert_unknown(snapshot)

    def test_receipt_before_publication_is_unknown(self):
        snapshot = fixture()
        snapshot["series"]["nominal_10y"]["rows"][-1]["received_at"] = "2024-01-04T12:00:00Z"
        self.assert_unknown(snapshot)

    def test_timezone_is_required(self):
        snapshot = fixture()
        snapshot["series"]["nominal_10y"]["rows"][-1]["available_at"] = "2024-01-04T13:00:00"
        self.assert_unknown(snapshot)

    def test_inverted_dates_are_not_silently_sorted(self):
        snapshot = fixture()
        snapshot["series"]["nominal_10y"]["rows"].reverse()
        self.assert_unknown(snapshot)

    def test_duplicate_revisions_are_not_latest_wins(self):
        snapshot = fixture()
        duplicate = copy.deepcopy(snapshot["series"]["nominal_10y"]["rows"][-1])
        duplicate["revision_id"] = "synthetic-v2"
        snapshot["series"]["nominal_10y"]["rows"].append(duplicate)
        self.assert_unknown(snapshot)

    def test_unavailable_later_revision_does_not_change_historical_result(self):
        snapshot = fixture()
        expected = self.build(snapshot)
        future = {"observation_date": "2024-01-03", "available_at": "2024-01-05T13:00:00Z",
                  "received_at": "invalid", "value": float("nan"), "revision_id": "synthetic-future"}
        snapshot["series"]["nominal_10y"]["rows"].append(future)
        self.assertEqual(self.build(snapshot), expected)

    def test_future_observation_is_hidden_before_reading_value(self):
        snapshot = fixture()
        expected = self.build(snapshot)
        snapshot["series"]["nominal_10y"]["rows"].append({"observation_date": "2024-01-10", "value": object()})
        self.assertEqual(self.build(snapshot), expected)

    def test_nonfinite_boolean_and_string_values_are_unknown(self):
        for value in (float("nan"), float("inf"), -float("inf"), True, "4.2"):
            with self.subTest(value=repr(value)):
                snapshot = fixture()
                snapshot["series"]["nominal_10y"]["rows"][-1]["value"] = value
                self.assert_unknown(snapshot)

    def test_overflowed_change_is_unknown_not_nonfinite_json(self):
        snapshot = fixture()
        snapshot["series"]["nominal_10y"]["rows"][0]["value"] = -1e308
        snapshot["series"]["nominal_10y"]["rows"][1]["value"] = 1e308
        self.assert_unknown(snapshot)

    def test_unit_fraction_or_bp_is_not_assumed_percent(self):
        for unit in ("fraction", "basis_points", "Percent"):
            with self.subTest(unit=unit):
                snapshot = fixture()
                snapshot["series"]["nominal_10y"]["unit"] = unit
                self.assert_unknown(snapshot)

    def test_mixed_sources_cannot_form_approximate_spread(self):
        snapshot = fixture()
        snapshot["series"]["real_10y"]["source_id"] = "SYNTHETIC_FIXTURE_ONLY:other"
        result = self.build(snapshot)
        self.assertEqual(result["approximate_yield_spread"]["status"], "unknown")
        self.assertIsNone(result["approximate_yield_spread"]["change_bp"])

    def test_same_source_series_in_nominal_and_real_is_ambiguous(self):
        snapshot = fixture()
        snapshot["series"]["real_10y"]["series_id"] = snapshot["series"]["nominal_10y"]["series_id"]
        result = self.build(snapshot)
        for role in ("nominal_10y", "real_10y"):
            self.assertEqual(result["series"][role]["status"], "unknown")
            self.assertIn("ROLE_SOURCE_IDENTITY_AMBIGUOUS", result["series"][role]["reason_codes"])
        self.assertEqual(result["approximate_yield_spread"]["status"], "unknown")

    def test_breakeven_reusing_nominal_source_series_is_ambiguous(self):
        snapshot = fixture()
        snapshot["series"]["breakeven_10y"]["series_id"] = snapshot["series"]["nominal_10y"]["series_id"]
        result = self.build(snapshot)
        for role in ("nominal_10y", "breakeven_10y"):
            self.assertEqual(result["series"][role]["status"], "unknown")

    def test_declarations_cannot_enable_backtest_or_position_control(self):
        result = self.build()
        self.assertIs(result["backtest_eligible"], False)
        self.assertIs(result["position_control_allowed"], False)

    def test_mixed_methodologies_cannot_form_approximate_spread(self):
        snapshot = fixture()
        snapshot["series"]["real_10y"]["basis"] = "treasury_constant_maturity_yield"
        self.assertEqual(self.build(snapshot)["approximate_yield_spread"]["status"], "unknown")

    def test_unknown_basis_is_unknown(self):
        snapshot = fixture()
        snapshot["series"]["nominal_10y"]["basis"] = "intraday_bond_price"
        self.assert_unknown(snapshot)

    def test_source_dates_must_match_exact_common_window(self):
        snapshot = fixture()
        snapshot["series"]["real_10y"]["rows"][-1]["observation_date"] = "2024-01-04"
        result = self.assert_unknown(snapshot, "real_10y")
        self.assertEqual(result["approximate_yield_spread"]["status"], "unknown")

    def test_window_missing_start_is_insufficient_not_forward_filled(self):
        snapshot = fixture()
        snapshot["series"]["nominal_10y"]["rows"].pop(0)
        self.assert_unknown(snapshot)

    def test_stale_observation_stays_stale_even_if_received_now(self):
        snapshot = fixture()
        snapshot["decision_at"] = "2024-01-10T15:00:00Z"
        for row in snapshot["series"]["nominal_10y"]["rows"]:
            row["received_at"] = "2024-01-10T14:00:00Z"
        result = self.assert_unknown(snapshot)
        self.assertIn("OBSERVATION_STALE", result["series"]["nominal_10y"]["reason_codes"])

    def test_independent_series_failure_does_not_erase_valid_nominal(self):
        snapshot = fixture()
        del snapshot["series"]["breakeven_10y"]
        result = self.build(snapshot)
        self.assertEqual(result["series"]["nominal_10y"]["change_bp"], 20.0)
        self.assertEqual(result["quality"]["status"], "unknown")

    def test_malformed_snapshot_is_unknown(self):
        self.assertEqual(self.build({})["quality"]["status"], "unknown")

    def test_invalid_config_raises_without_input_echo(self):
        policy = config()
        policy["window_start"] = "2024-01-04"
        with self.assertRaisesRegex(observer.ContractError, "invalid_config"):
            self.build(policy=policy)

    def test_extra_fields_are_not_hidden_authority(self):
        snapshot = fixture()
        snapshot["target_weight"] = 1.0
        self.assertEqual(self.build(snapshot)["quality"]["status"], "unknown")

    def test_output_is_strict_json_and_has_no_trading_fields(self):
        result = self.build()
        json.dumps(result, allow_nan=False)
        forbidden = {"target_weight", "position_control", "order", "capital", "risk_off", "risk_on", "vote"}
        def walk(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden.intersection(value))
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
        walk(result)

    def test_inputs_are_not_mutated(self):
        snapshot, policy = fixture(), config()
        before = copy.deepcopy((snapshot, policy))
        self.build(snapshot, policy)
        self.assertEqual((snapshot, policy), before)

    def test_invalid_decision_timezone_is_unknown(self):
        snapshot = fixture()
        snapshot["decision_at"] = "2024-01-04T15:00:00"
        self.assert_unknown(snapshot)

    def test_invalid_config_age_or_fields_is_rejected(self):
        for value in (-1, True, 1.5):
            with self.subTest(value=value):
                policy = config()
                policy["max_observation_age_days"] = value
                with self.assertRaises(observer.ContractError):
                    self.build(policy=policy)
        policy = config()
        policy["hidden_threshold"] = 1
        with self.assertRaises(observer.ContractError):
            self.build(policy=policy)

    def test_visible_extra_row_fields_are_invalid(self):
        snapshot = fixture()
        snapshot["series"]["nominal_10y"]["rows"][-1]["unit"] = "basis_points"
        self.assert_unknown(snapshot)

    def test_invalid_date_selector_is_unknown(self):
        snapshot = fixture()
        snapshot["series"]["nominal_10y"]["rows"][-1]["observation_date"] = "20240103"
        self.assert_unknown(snapshot)

    def test_latest_revision_is_not_a_frozen_identity(self):
        snapshot = fixture()
        snapshot["series"]["nominal_10y"]["rows"][-1]["revision_id"] = "latest"
        self.assert_unknown(snapshot)

    def test_outside_start_window_rows_do_not_alter_exact_endpoints(self):
        snapshot = fixture()
        expected = self.build(snapshot)
        snapshot["series"]["nominal_10y"]["rows"].insert(0, {"observation_date": "2024-01-01", "value": object()})
        self.assertEqual(self.build(snapshot), expected)

    def test_freshness_boundary_is_explicit_calendar_days(self):
        snapshot = fixture()
        snapshot["decision_at"] = "2024-01-05T15:00:00Z"
        self.assertEqual(self.build(snapshot)["series"]["nominal_10y"]["status"], "declared_available")
        snapshot["decision_at"] = "2024-01-06T00:00:00Z"
        self.assert_unknown(snapshot)

    def test_times_with_offsets_are_normalized_to_utc(self):
        snapshot = fixture()
        row = snapshot["series"]["nominal_10y"]["rows"][-1]
        row["available_at"], row["received_at"] = "2024-01-04T08:00:00-05:00", "2024-01-04T08:01:00-05:00"
        result = self.build(snapshot)
        self.assertEqual(result["series"]["nominal_10y"]["end_observation"]["available_at"], "2024-01-04T13:00:00Z")

    def test_publication_before_observation_date_is_unknown(self):
        snapshot = fixture()
        snapshot["series"]["nominal_10y"]["rows"][-1]["available_at"] = "2024-01-02T13:00:00Z"
        self.assert_unknown(snapshot)

    def test_unknown_preserves_available_endpoint_metadata(self):
        snapshot = fixture()
        snapshot["series"]["nominal_10y"]["rows"][-1]["available_at"] = None
        result = self.assert_unknown(snapshot)
        end = result["series"]["nominal_10y"]["end_observation"]
        self.assertEqual(end["observation_date"], "2024-01-03")
        self.assertIsNone(end["available_at"])
        self.assertEqual(end["received_at"], "2024-01-04T13:01:00Z")


if __name__ == "__main__":
    unittest.main()
