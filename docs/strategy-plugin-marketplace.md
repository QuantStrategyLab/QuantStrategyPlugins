# Strategy Plugin Marketplace Architecture (`V2 Composite Candidate`)

> **Status:** Research & Contract Architecture Only (`position_mutation_allowed = false`, `broker_order_allowed = false`, zero live/paper admission authority).

## 1. Purpose

Scale `QuantStrategyPlugins` from single-theme Nasdaq/semiconductor overlays (`market_regime_control`, `tqqq_growth_income`) into a governed multi-asset plugin marketplace without duplicating broker-facing code across platform repositories.

Every marketplace participant follows strict **N + M separation**:
- **Plugins & Strategy Specs (`QuantStrategyPlugins` / strategy repos):** Express research signals, universe rules, dataset manifests, and V2 composite-candidate bindings. Never place orders or mutate live leverage/cash buffers.
- **Broker Execution (`InteractiveBrokersPlatform`, `CharlesSchwabPlatform`, `FirstradePlatform`, `BinancePlatform`):** Read authoritative broker account facts, enforce shared `FUSE` / `flow_adjusted_hwm` / `V1`–`V7` collars, and route compliant orders only for admitted candidates.

## 2. Four Orthogonal Shelves

| Shelf | Asset Scope | Target Lower-Tail Correlation (`10%` QQQ/TQQQ/SOXL) | Required Controls |
| --- | --- | --- | --- |
| **US Sector & Market-Neutral** | US sector ETFs, defensive low-vol rotation, or long-defensive / short-QQQ market-neutral spreads | `< 0.50` point & 95% UCB | Explicit `1x` unlevered baseline; cash parking rules |
| **Non-US Equity** | Broad ex-US developed / HK / EM equity benchmarks | `< 0.50` point & 95% UCB | Point-in-time total-return verification |
| **Macro Real Assets & Rates** | Physical Gold ETFs (`1x`), regime-filtered long/intermediate US Treasuries | `< 0.50` point & 95% UCB | Interest-rate trend / inflation regime filter mandatory for long duration |
| **Managed Futures / CTA** | Micro index, rates, gold, crude, FX, and commodity trend-following / carry | `< 0.50` point & 95% UCB (Crisis Alpha) | Explicit continuous `roll_rule` AND `margin_isolated_from_cash_buffer = true` |

## 3. Lifecycle Progression

Every composite candidate binds `(candidate_id, strategy_profile, strategy_revision, plugin_id, plugin_revision, asset_class, input_manifest_sha256, sizing_policy_id)` and moves strictly monotonically:

1. `research_active` — Offline `BREADTH` screening (`lower_tail_correlation_gate` `< 0.50`, `OI-COST-*` stress, `DSR` / `PBO` accounting).
2. `shadow_active` — Forward out-of-sample observation recorded against hash-chained `ShadowResearch` evidence (`evidence_digest` required).
3. `paper_active` — Broker paper execution verification after `SHADOW` stability and platform readiness.
4. `live_candidate` — Complete evidence package awaiting explicit Owner deployment admission (contract validation never grants `live_enabled`).

## 4. Onboarding Validation CLI

Validate any candidate JSON specification locally or in CI before opening a promotion/evidence PR:

```bash
python scripts/validate_composite_candidate.py --spec path/to/candidate.json
```

Fail-closed invariants verified automatically:
- Registered `plugin_id` in `docs/registry/plugin_catalog.json` with explicit `position_mutation_allowed = false`, `broker_order_allowed = false`, and non-`LIVE_ENABLED` status.
- Full `64`-hex `input_manifest_sha256` (no trailing newline or truncation).
- Valid `asset_class` and monotonic `lifecycle_stage` with required `64`-hex `evidence_digest` beyond `research_active`.
