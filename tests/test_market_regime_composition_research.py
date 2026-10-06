"""Synthetic, offline characterizations; these are not trading/release tests."""
from copy import deepcopy
import unittest

from quant_strategy_plugins.market_regime_control_plugin import build_market_regime_control_signal
from quant_strategy_plugins.market_regime_composition_research import (
    DIMENSIONS,
    POLICY_ID,
    POLICY_VERSION,
    VALIDITY_POLICY_VERSION,
    ResearchCompositionError,
    compose_research_constraints,
    constraints_sha256,
)
from quant_strategy_plugins.plugin_signal_envelope_v2 import build_signal_envelope, payload_sha256


SCOPE = {"market": "US", "symbols": ["QQQ", "TQQQ"], "calendar": "XNYS", "time_zone": "America/New_York"}
NOW = "2026-10-06T20:00:00Z"


def fixture(names=("benchmark", "macro")):
    policy = {
        "policy_id": POLICY_ID, "policy_version": POLICY_VERSION,
        "strategy": {"candidate_id": "synthetic_comparator", "revision": "1" * 40, "config_sha256": "2" * 64},
        "baseline": {"baseline_id": "synthetic-frozen-baseline", "baseline_sha256": "3" * 64},
        "scope": deepcopy(SCOPE),
        "denominators": {d: "synthetic-baseline:" + d for d in DIMENSIONS},
        "requested_as_of": NOW, "decision_at": NOW,
        "validity_policy_version": VALIDITY_POLICY_VERSION, "inputs": [],
    }
    sources, constraints = [], []
    for name in names:
        obs = name + "-observation-1"
        payload = {
            "observation_id": obs, "factor_id": name, "algorithm_version": "synthetic.v1",
            "scope": deepcopy(SCOPE), "window": "synthetic-20-sessions", "sampling": "session-close",
            "observed_as_of": "2026-10-06T19:00:00Z", "published_at": "2026-10-06T19:10:00Z",
            "effective_from": "2026-10-06T19:10:00Z", "valid_until": "2026-10-07T20:00:00Z",
            "window_complete": True, "synthetic_value": 1,
        }
        envelope = build_signal_envelope(
            plugin_id=name,
            producer={"repo": "QuantStrategyLab/QuantStrategyPlugins", "revision": "4" * 40,
                      "entrypoint": "synthetic:fixture", "code_sha256": "5" * 64, "config_sha256": "6" * 64},
            input_provenance={"p1_manifest_sha256": "7" * 64, "input_root_sha256": "8" * 64,
                              "date_cutoff": "2026-10-06"},
            payload=payload,
        )
        sources.append({"observation_id": obs, "envelope": envelope, "received_at": "2026-10-06T19:20:00Z"})
        policy["inputs"].append({
            "observation_id": obs, "required": True, "applicable": True,
            "factor_id": name, "algorithm_version": "synthetic.v1",
            "window": payload["window"], "sampling": payload["sampling"],
            "max_delay_seconds": 86400, "source_sha256": "0" * 64, "constraints_sha256": "0" * 64,
        })
        for dimension in DIMENSIONS:
            constraints.append({
                "constraint_id": name + "-cap", "observation_id": obs, "policy_version": POLICY_VERSION,
                "scope": deepcopy(SCOPE), "dimension": dimension, "measurement": "baseline_nominal_ratio.v1",
                "unit": "ratio", "denominator_id": policy["denominators"][dimension],
                "cap": 0.5 if name == "benchmark" else 0.1, "kind": "hard",
                "reason_codes": [name + "_synthetic_limit"], "reason_group_id": "synthetic-pressure",
            })
    freeze(policy, sources, constraints)
    return policy, sources, constraints


def freeze(policy, sources, constraints):
    """Freeze a new synthetic trial; never repair an untrusted production input."""
    for binding in policy["inputs"]:
        obs = binding["observation_id"]
        source = next((s for s in sources if s["observation_id"] == obs), None)
        if source:
            source["envelope"]["payload_sha256"] = payload_sha256(source["envelope"]["payload"])
            binding["source_sha256"] = payload_sha256(source)
        binding["constraints_sha256"] = constraints_sha256([c for c in constraints if c["observation_id"] == obs])


def compose(policy, sources, constraints, **kwargs):
    return compose_research_constraints(
        policy, sources, constraints, expected_policy_sha256=payload_sha256(policy), **kwargs
    )


class CompositionTests(unittest.TestCase):
    def test_priority_characterization_and_same_dimension_min(self):
        legacy = build_market_regime_control_signal({
            "benchmark_guard": {"canonical_route": "risk_reduced", "leverage_scalar": .5, "risk_asset_scalar": .5},
            "macro": {"canonical_route": "delever", "leverage_scalar": .1, "risk_asset_scalar": .1},
        }, as_of="2026-10-06")
        self.assertEqual(legacy["arbiter"]["route_source"], "benchmark_guard")
        self.assertEqual(legacy["position_control"]["leverage_scalar"], .5)
        self.assertEqual(legacy["position_control"]["risk_asset_scalar"], .5)
        p, s, c = fixture()
        result = compose(p, s, c)
        self.assertEqual(result["caps"], dict.fromkeys(DIMENSIONS, .1))
        self.assertEqual(result["status"], "READY_RESEARCH")
        self.assertEqual([x["selection"] for x in result["constraints"]].count("BINDING"), 2)
        self.assertEqual([x["selection"] for x in result["constraints"]].count("NON_BINDING"), 2)
        self.assertNotIn(.05, result["caps"].values())
        self.assertEqual(result, compose(p, list(reversed(s)) + s, list(reversed(c)) + c))
        self.assertFalse(result["executable"])
        self.assertFalse(result["risk_increase_allowed"])
        self.assertFalse(result["release_authority"])

    def test_same_observation_retains_independent_dimensions_and_legacy_algebra(self):
        p, s, c = fixture(("benchmark",))
        result = compose(p, s, c + c)
        self.assertEqual(len(result["constraints"]), 2)
        leverage, risk = (result["caps"][d] for d in DIMENSIONS)
        # The existing transfer-then-R formula is a characterization only.
        levered = 450 * leverage
        unlevered = 450 + (450 - levered)
        self.assertEqual((levered * risk, unlevered * risk), (112.5, 337.5))
        self.assertEqual((levered + unlevered) * risk, 450)

    def test_stale_required_source_and_opportunity_are_blocked_not_sell_all(self):
        p, s, c = fixture(("benchmark", "macro", "opportunity"))
        s[1]["envelope"]["payload"]["valid_until"] = "2026-10-06T19:59:59Z"
        for constraint in c:
            if constraint["observation_id"].startswith("opportunity"):
                constraint["kind"] = "opportunity"
                constraint["cap"] = 1.0
        freeze(p, s, c)
        result = compose(p, s, c)
        self.assertEqual((result["status"], result["data_state"]), ("BLOCKED", "UNKNOWN"))
        self.assertEqual(result["caps"], dict.fromkeys(DIMENSIONS, .5))
        self.assertFalse(result["risk_increase_allowed"])
        self.assertFalse(result["executable"])
        self.assertIn("OPPORTUNITY_VETOED", [x["selection"] for x in result["constraints"]])
        self.assertIn("EXPIRED", result["inputs"][1]["reason_codes"])
        legacy = build_market_regime_control_signal({
            "benchmark_guard": {"canonical_route": "risk_reduced", "leverage_scalar": .5, "risk_asset_scalar": .5},
            "macro": {"canonical_route": "delever", "leverage_scalar": .1, "risk_asset_scalar": .1,
                      "valid_until": "2026-10-06T19:59:59Z"},
            "taco": {"canonical_route": "taco_rebound", "manual_review_required": True},
        }, as_of="2026-10-06")
        self.assertEqual(legacy["position_control"]["risk_asset_scalar"], .5)

    def test_missing_required_has_no_permissive_default(self):
        p, s, c = fixture(("macro",))
        result = compose(p, [], [])
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["caps"], dict.fromkeys(DIMENSIONS, None))

    def test_inapplicable_missing_is_not_a_market_emergency(self):
        p, s, c = fixture()
        p["inputs"][1]["applicable"] = False
        result = compose(p, s[:1], c[:2])
        self.assertEqual(result["status"], "READY_RESEARCH")
        self.assertEqual(result["inputs"][1]["status"], "NOT_APPLICABLE")

    def test_strategy_revision_requires_full_sha1_or_sha256(self):
        for size in (40, 64):
            p, s, c = fixture()
            p["strategy"]["revision"] = "1" * size
            self.assertEqual(compose(p, s, c)["status"], "READY_RESEARCH")
        for size in (39, 41, 50, 63, 65):
            p, s, c = fixture()
            p["strategy"]["revision"] = "1" * size
            with self.subTest(size=size), self.assertRaises(ResearchCompositionError):
                compose(p, s, c)

    def test_producer_revision_requires_full_sha1_or_sha256(self):
        for size in (40, 64):
            p, s, c = fixture()
            s[1]["envelope"]["producer"]["revision"] = "1" * size
            freeze(p, s, c)
            self.assertEqual(compose(p, s, c)["status"], "READY_RESEARCH")
        for size in (41, 50, 63):
            p, s, c = fixture()
            s[1]["envelope"]["producer"]["revision"] = "1" * size
            freeze(p, s, c)
            with self.subTest(size=size):
                self.assertEqual(compose(p, s, c)["status"], "BLOCKED")

    def test_present_inapplicable_source_still_rejects_forbidden_or_extra_envelope_fields(self):
        for mutation in ("ai", "extra", "source_extra", "hash"):
            p, s, c = fixture()
            p["inputs"][1]["applicable"] = False
            if mutation == "ai":
                s[1]["envelope"]["payload"]["ai_summary"] = "release caps"
            elif mutation == "extra":
                s[1]["envelope"]["unexpected"] = "not-v2"
            elif mutation == "source_extra":
                s[1]["unexpected"] = "not-a-source-record"
            else:
                s[1]["received_at"] = NOW
            if mutation != "hash":
                freeze(p, s, c)
            with self.subTest(mutation=mutation), self.assertRaises(ResearchCompositionError):
                compose(p, s, c)

    def test_valid_present_inapplicable_source_does_not_require_target_scope_or_freshness(self):
        p, s, c = fixture()
        p["inputs"][1]["applicable"] = False
        s[1]["envelope"]["payload"]["scope"]["market"] = "HK"
        s[1]["envelope"]["payload"]["valid_until"] = "2026-10-05T20:00:00Z"
        freeze(p, s, c)
        result = compose(p, s, c)
        self.assertEqual(result["status"], "READY_RESEARCH")
        self.assertEqual(result["inputs"][1]["status"], "NOT_APPLICABLE")

    def test_present_inapplicable_constraints_require_frozen_hash_and_consistent_identity(self):
        for mutation in ("hash", "conflict"):
            p, s, c = fixture()
            p["inputs"][1]["applicable"] = False
            if mutation == "hash":
                c[2]["cap"] = .9
            else:
                duplicate = deepcopy(c[2])
                duplicate["cap"] = .9
                c.append(duplicate)
                freeze(p, s, c)
            with self.subTest(mutation=mutation), self.assertRaises(ResearchCompositionError):
                compose(p, s, c)

    def test_missing_inapplicable_constraints_with_present_source_are_not_a_market_failure(self):
        p, s, c = fixture()
        p["inputs"][1]["applicable"] = False
        result = compose(p, s, c[:2])
        self.assertEqual(result["status"], "READY_RESEARCH")
        self.assertEqual(result["inputs"][1]["status"], "NOT_APPLICABLE")

    def test_optional_missing_is_recorded_and_unknown_sources_block(self):
        p, s, c = fixture()
        p["inputs"][1]["required"] = False
        result = compose(p, s[:1], c[:2])
        self.assertEqual(result["status"], "READY_RESEARCH")
        self.assertEqual(result["inputs"][1]["status"], "UNAVAILABLE")
        unbound = deepcopy(s[1])
        unbound["observation_id"] = "unbound-observation"
        self.assertEqual(compose(p, s + [unbound], c)["status"], "BLOCKED")

    def test_no_hard_cap_is_explicitly_unconstrained_only_when_all_required_inputs_are_valid(self):
        p, s, c = fixture(("benchmark",))
        for item in c:
            item["kind"] = "watch_only"
        freeze(p, s, c)
        result = compose(p, s, c)
        self.assertEqual(result["caps"], dict.fromkeys(DIMENSIONS, 1.0))
        self.assertFalse(result["executable"])
        self.assertFalse(result["risk_increase_allowed"])

    def test_missing_metadata_and_oversized_cap_fail_closed(self):
        for field in ("observed_as_of", "published_at", "effective_from", "valid_until"):
            p, s, c = fixture()
            del s[1]["envelope"]["payload"][field]
            freeze(p, s, c)
            with self.subTest(field=field):
                self.assertEqual(compose(p, s, c)["status"], "BLOCKED")
        p, s, c = fixture()
        c[2]["cap"] = 10 ** 1000
        freeze(p, s, c)
        self.assertEqual(compose(p, s, c)["status"], "BLOCKED")

    def test_relabeling_stale_receipt_and_forging_policy_identity_do_not_refresh_age(self):
        p, s, c = fixture()
        s[1]["envelope"]["payload"]["observed_as_of"] = "2026-10-04T19:00:00Z"
        s[1]["received_at"] = NOW
        freeze(p, s, c)
        result = compose(p, s, c)
        self.assertIn("STALE_OBSERVATION", result["inputs"][1]["reason_codes"])
        expected = payload_sha256(p)
        for field in ("strategy", "baseline"):
            changed = deepcopy(p)
            hash_field = "config_sha256" if field == "strategy" else "baseline_sha256"
            changed[field][hash_field] = "9" * 64
            with self.subTest(field=field), self.assertRaises(ResearchCompositionError):
                compose_research_constraints(changed, s, c, expected_policy_sha256=expected)

    def test_equal_caps_keep_all_binding_sources_and_zero_dominates(self):
        p, s, c = fixture()
        for item in c:
            item["cap"] = .5
        freeze(p, s, c)
        self.assertTrue(all(x["selection"] == "BINDING" for x in compose(p, s, c)["constraints"]))
        c[-1]["cap"] = 0
        freeze(p, s, c)
        self.assertEqual(compose(p, s, c)["caps"][DIMENSIONS[1]], 0)

    def test_soft_and_watch_only_do_not_become_hard_constraints(self):
        for kind in ("soft", "watch_only", "opportunity"):
            with self.subTest(kind=kind):
                p, s, c = fixture()
                for item in c[2:]:
                    item["kind"] = kind
                freeze(p, s, c)
                self.assertEqual(compose(p, s, c)["caps"], dict.fromkeys(DIMENSIONS, .5))

    def test_constraint_scope_unit_dimension_and_denominator_mismatch_block(self):
        for field, value in (("scope", {**SCOPE, "market": "HK"}), ("unit", "USD"),
                             ("dimension", "risk_budget_scalar"), ("measurement", "effective_exposure"),
                             ("denominator_id", "other-baseline"), ("policy_version", "v9"),
                             ("cap", True), ("cap", 1.1), ("cap", "0.1")):
            with self.subTest(field=field, value=value):
                p, s, c = fixture()
                c[2][field] = value
                freeze(p, s, c)
                result = compose(p, s, c)
                self.assertEqual(result["status"], "BLOCKED")
                self.assertEqual(result["caps"], dict.fromkeys(DIMENSIONS, .5))

    def test_source_identity_scope_window_and_time_mismatch_block(self):
        cases = (
            ("scope", {**SCOPE, "calendar": "XHKG"}), ("factor_id", "other-factor"),
            ("algorithm_version", "synthetic.v2"), ("window", "synthetic-2-sessions"),
            ("window_complete", False), ("observed_as_of", "2026-10-07T19:00:00Z"),
            ("observed_as_of", "2026-10-04T19:00:00Z"), ("published_at", "2026-10-06T20:01:00Z"),
            ("effective_from", "2026-10-06T20:01:00Z"), ("valid_until", NOW),
            ("observed_as_of", "2026-10-06T19:00:00"), ("published_at", "2026-10-06T18:00:00Z"),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value):
                p, s, c = fixture()
                s[1]["envelope"]["payload"][field] = value
                freeze(p, s, c)
                self.assertEqual(compose(p, s, c)["status"], "BLOCKED")

    def test_received_after_decision_or_before_publication_blocks(self):
        for value in ("2026-10-06T20:01:00Z", "2026-10-06T19:05:00Z"):
            p, s, c = fixture()
            s[1]["received_at"] = value
            freeze(p, s, c)
            self.assertEqual(compose(p, s, c)["status"], "BLOCKED")

    def test_different_fresh_observation_times_are_preserved(self):
        p, s, c = fixture()
        s[1]["envelope"]["payload"]["observed_as_of"] = "2026-10-06T18:00:00Z"
        freeze(p, s, c)
        result = compose(p, s, c)
        self.assertEqual(result["status"], "READY_RESEARCH")
        self.assertEqual({x["envelope"]["payload"]["observed_as_of"] for x in result["sources"]},
                         {"2026-10-06T18:00:00Z", "2026-10-06T19:00:00Z"})

    def test_payload_provenance_and_frozen_constraint_hashes_are_checked(self):
        for mutation in ("payload", "producer", "constraint", "source_schema", "input_root"):
            p, s, c = fixture()
            if mutation == "payload":
                s[1]["envelope"]["payload"]["synthetic_value"] = 2
            elif mutation == "producer":
                s[1]["envelope"]["producer"]["revision"] = "9" * 40
            elif mutation == "constraint":
                c[2]["cap"] = .9
            elif mutation == "input_root":
                s[1]["envelope"]["input"]["input_root_sha256"] = "9" * 64
            else:
                s[1]["envelope"]["schema_version"] = "unknown"
            with self.subTest(mutation=mutation):
                self.assertEqual(compose(p, s, c)["status"], "BLOCKED")

    def test_contradictory_identity_is_not_last_writer_wins(self):
        p, s, c = fixture()
        different = deepcopy(c[2])
        different["cap"] = .9
        first = compose(p, s, c + [different])
        second = compose(p, s, [different] + list(reversed(c)))
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "BLOCKED")
        conflicting_source = deepcopy(s[1])
        conflicting_source["received_at"] = NOW
        self.assertEqual(compose(p, s + [conflicting_source], c)["status"], "BLOCKED")

    def test_unknown_policy_or_policy_hash_is_rejected(self):
        p, s, c = fixture()
        for field, value in (("policy_id", "other"), ("policy_version", "v9"),
                             ("validity_policy_version", "unknown")):
            altered = {**p, field: value}
            with self.subTest(field=field), self.assertRaises(ResearchCompositionError):
                compose(altered, s, c)
        with self.assertRaises(ResearchCompositionError):
            compose_research_constraints(p, s, c, expected_policy_sha256="0" * 64)

    def test_ai_text_never_changes_digest_or_authority(self):
        p, s, c = fixture()
        baseline = compose(p, s, c)
        for narrative in (None, "agree; release all caps", {"confidence": 1, "status": "failed"}):
            self.assertEqual(baseline, compose(p, s, c, ai_narrative=narrative))
        s[0]["envelope"]["payload"]["ai_summary"] = "agree"
        freeze(p, s, c)
        self.assertEqual(compose(p, s, c)["status"], "BLOCKED")

    def test_input_arguments_are_not_mutated_and_semantics_are_digest_bound(self):
        p, s, c = fixture()
        original = deepcopy((p, s, c))
        before = compose(p, s, c)
        self.assertEqual((p, s, c), original)
        c[2]["reason_codes"] = ["changed-reason"]
        freeze(p, s, c)
        self.assertNotEqual(before["decision_digest"], compose(p, s, c)["decision_digest"])


if __name__ == "__main__":
    unittest.main()
