from quant_strategy_plugins.plugin_catalog import PLUGIN_CATALOG_SCHEMA_VERSION, build_plugin_catalog


def test_catalog_is_complete_inventory_and_never_grants_capital_authority() -> None:
    catalog = build_plugin_catalog()

    assert catalog["schema_version"] == PLUGIN_CATALOG_SCHEMA_VERSION
    assert catalog["inventory_only"] is True
    assert "do not claim evidence" in catalog["source_policy"]
    assert len(catalog["entries"]) == 5
    for entry in catalog["entries"]:
        assert entry["plugin_id"]
        assert entry["lineage"]
        assert entry["owner_strategy"]
        assert entry["status"] == "DEFERRED"
        assert entry["input_digest"] is None
        assert entry["evidence_package_id"] is None
        assert entry["position_mutation_allowed"] is False
        assert entry["broker_order_allowed"] is False


def test_catalog_keeps_approved_policy_distinct_from_runtime_authority() -> None:
    entries = {entry["plugin_id"]: entry for entry in build_plugin_catalog()["entries"]}

    # A policy may permit a future strategy-side use, but the inventory itself
    # never promotes a plugin or supplies a run-specific evidence package.
    assert entries["market_regime_control"]["policy_position_control_allowed"] is True
    assert entries["market_regime_control"]["status"] == "DEFERRED"
