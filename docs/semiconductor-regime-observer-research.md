# Semiconductor regime observation research

Status: `UNVALIDATED_RESEARCH`. This is a callable pure research module, not an enabled plugin, strategy router, or trading permission. No production calibration or economic improvement is claimed.

[中文完整说明](semiconductor-regime-observer-research.zh-CN.md)

## Boundary and existing interfaces

`quant_strategy_plugins.semiconductor_regime_observer_research` adds close-only SOXX/SOXL evidence beside the existing research modules. It reuses the current `plugin_signal_envelope_v2.canonical_json_bytes` and `build_signal_envelope` without changing their contract.

Shared price/SMA, population realized-volatility, and trailing-drawdown formulas follow the existing QQQ observer. Synthetic tests compare these four facts with that observer on identical artificial numbers. The QQQ observer remains unchanged and is never relabeled as SOXX.

The earlier QSP `3416da47580be1537183e378f3ca9efacc6f9b8c` is a fixed source anchor declared by the UES optional research dependency. It is not proof of active installation, enablement, or production producer/consumer pins.

Package-level __init__ exports are unchanged, and no runtime entry is registered. No new CLI, runner entry, catalog entry, dependency, default/live configuration, service, or scheduler is added. Ordinary import does not enable or run the research entrypoint. The module itself has no provider, filesystem, clock, AI, broker, or strategy dependency; the existing package-level imports are unchanged.

Outputs contain no position, capital, order, control, or authorization fields. Keep observation, approved strategy targets, risk reductions/vetoes, and execution separate. Restoring data or lifting risk restrictions must not buy from an old signal. New exposure requires a current valid approved strategy signal, the shared budget, existing holdings/pending-order netting, and existing account/release permissions. These are downstream constraints, not actions implemented here.

## Callable API

- `build_semiconductor_regime_observation(snapshot, config)`: deterministic observation; incomplete or inconsistent data returns unknown
- `semiconductor_regime_observer_config_sha256(config)`: canonical frozen research-configuration identity
- `semiconductor_regime_observation_usable_at(observation, at)`: explicit-time qualification/freshness check; never permission to trade
- `build_semiconductor_regime_signal_v2(*, snapshot, config, producer, input_provenance)`: computes the observation and calls the existing pure V2 builder

All calculation configuration is mandatory. Invalid configuration or V2 binding raises the sanitized `ContractError`. Data defects are separate quality reasons and never become a market risk label.

The V2 research entrypoint is exactly:

`quant_strategy_plugins.semiconductor_regime_observer_research:build_semiconductor_regime_signal_v2`

The wrapper requires `producer.repo=QuantStrategyLab/QuantStrategyPlugins`, this exact entrypoint, and the matching configuration hash. The unchanged V2 helper validates immutable producer revision/code/config digest formats and rejects forbidden control fields and mutable latest references. A caller's code/revision declaration is not installed-byte proof; independent P3 evidence remains necessary.

`input_provenance` must contain exactly `p1_manifest_sha256`, `input_root_sha256`, and `date_cutoff`. The cutoff must match the observation; the root must equal its causal `input_sha256`. The P1 hash must have valid digest syntax. This verifies declared consistency, not P1 content, provider truth, or research qualification. A full raw-file manifest containing invisible future rows cannot substitute for the causal projection's qualified manifest.

## Symbols and proxy limits

Only the following exact pairs are supported:

| symbol | series_role | Meaning |
| --- | --- | --- |
| SOXX | SIGNAL_PROXY | Semiconductor signal proxy for an SOXL research candidate |
| SOXL | EXECUTION_BENCHMARK | Observation of SOXL's own price path |

Each series has independent input identity. SOXX signals do not imply identical SOXL performance: leverage, daily reset, tracking differences, volatility drag, overnight gaps, and execution/cost definitions need separate validation. No execution prices or realized strategy returns are computed.

QQQ belongs to the separate QQQ/TQQQ background. This module rejects QQQ and never copies a QQQ state to semiconductor evidence.

## Exact input contract

Top-level keys must be exactly:

`schema_version`, `symbol`, `series_role`, `as_of`, `available_at`, `decision_at`, `calendar`, `adjustment`, `components`, `bars`.

- `schema_version`: `qsl.semiconductor-regime-input.research.v1`
- `as_of`: strict YYYY-MM-DD ending trading session
- `available_at`: first complete availability of this causal input snapshot; no later than decision_at and no earlier than used rows/components
- `decision_at`: actual observation evaluation/completion/publication time; a real producer must not backdate it before its completed publication
- All timestamps require explicit ISO timezone information and are normalized to UTC in output

`calendar` has exactly `id`, `version`, `available_at`, `sessions`. The caller supplies the complete official session list and an immutable calendar version, including holidays/early closes; the module does not infer them. Each session has exactly `date`, `close_at`, `complete`. Selected sessions must be strictly increasing, complete=true, closed by decision_at, end at as_of, and cover the required windows. The UTC date of close_at must match the session label for this SOXX/SOXL contract. Extra prices outside the declared calendar fail qualification.

`adjustment` has exactly `basis`, `version`, `available_at`, `point_in_time_attested`. Basis is explicitly `raw`, `split_adjusted`, or `split_and_distribution_adjusted`; availability must be no later than decision_at and point_in_time_attested must be true. Versions/IDs cannot be empty or mutable latest values. Different adjustment bases must not be treated as one comparable experiment; raw split jumps remain a data-validity risk. No factor recalculation occurs.

`components` has exactly `prices`, `calendar`, `adjustment`. Each component has exactly `as_of`, `available_at`, `version`. All end at the same as_of and are available by decision_at. Calendar/adjustment versions and availability match their respective declarations; price-component availability must not predate its used rows. Version identifiers describe frozen producer/interpretation versions, not a rewritten entire-file latest identity.

Each bar has exactly `symbol`, `date`, `close`, `closed`, `available_at`, `adjustment_available_at`, `adjustment_version`. Selected rows must match the symbol and factor version, have finite positive non-boolean closes, closed=true, and publication no earlier than session close and factor availability. Duplicate or unsorted selected dates are rejected; the module does not sort or choose between multiple already-visible revisions.

Qualification is explicitly `qualified_by_declaration`: caller attestations and internal consistency only. The module cannot prove provider historical truth, official-calendar completeness, or factor availability. If both calendar and prices omit a session while declaring completeness, this check alone cannot detect it. Real P0 evidence and immutable PIT snapshots remain required.

## Causal projection and hash

The chosen policy slices at as_of/decision_at:

1. Rows dated after as_of are invisible before any other columns are inspected
2. For historical dates, price availability after decision_at makes the row invisible, including unrelated or malformed remaining columns
3. Factor availability after decision_at also excludes that adjusted row
4. Required unavailable sessions are missing coverage, not imputed prices or market pressure
5. Calendar rows after as_of are likewise invisible

An unparseable selector cannot prove future status and produces `ROW_SELECTOR_INVALID`. Top-level/component declarations must remain frozen for that historical decision; rewriting them is not a hidden future-row append.

`input_sha256` hashes only the projected input using the existing QSP canonical JSON helper. Invisible rows do not enter features, validation, counts, reasons, or identity. Appending them leaves the entire historical observation and hash unchanged. Invalid selected values receive diagnostic error-type identity and remain unknown, never qualified evidence. Configuration hash and V2 payload hash are separate identities.

## Explicit features and configuration

Configuration schema is `qsl.semiconductor-regime-config.research.v1`. Its exact additional fields are:

- `sma_window_sessions` ≥2; `sma_slope_lag_sessions` ≥1
- `path_window_returns` ≥2, requiring one more close than return steps
- `short_vol_window_returns` and `long_vol_window_returns` ≥2, short≤long
- `drawdown_window_sessions` ≥2; `annualization_sessions` ≥1
- `ttl_seconds` ≥1; `classification` explicitly null or the complete hypothesis below

There are no numerical defaults. Freeze windows, TTL, thresholds, and comparison policy before evaluation; never choose them from future outcomes. Very short windows and values in tests are `SYNTHETIC_FIXTURE_ONLY`, not deployment recommendations.

Minimum required history is the maximum of SMA window+slope lag, path returns+1, short returns+1, long returns+1, and drawdown sessions.

| Feature | Definition |
| --- | --- |
| close_to_sma_ratio | last close/current trailing SMA −1 |
| sma_slope_per_session | (current SMA/lagged SMA −1)/lag sessions |
| path_efficiency | absolute endpoint change/sum of absolute path steps |
| short/long_realized_volatility_annualized | population standard deviation of arithmetic returns × square root of annualization sessions |
| volatility_ratio | short volatility/long volatility |
| trailing_drawdown_ratio | last close/trailing-window peak −1 |

Finite features are rounded to 12 decimals; classification uses that same precision. Zero path variation yields null path efficiency; zero long volatility yields null volatility ratio. These are undefined market features, not automatic range or safety labels. Non-finite computation fails qualification and clears all features.

## Independent axes and research hypotheses

`classification=null` is normal feature-only mode. Qualified input still yields features, while all axes return unknown/`CLASSIFICATION_NOT_CONFIGURED`.

A classifier must have exactly `hypothesis_id`, `status=UNVALIDATED_RESEARCH_HYPOTHESIS`, `direction`, `trendiness`, `pressure`. No calibrated status or probabilities are accepted.

- Direction: explicit positive `price_distance_min` and `sma_slope_min`; both facts exceed positive thresholds for up, negative thresholds for down. Significant opposite signs or threshold gaps yield unknown
- Trendiness: 0≤`range_efficiency_max`<`trend_efficiency_min`≤1; low efficiency is range_like, high is trend_like, the gap is unknown. Range_like does not prove profitable mean reversion or authorize RSI2
- Pressure: 0≤`drawdown_normal_max`<`drawdown_stress_min`≤1 and 0≤`volatility_ratio_normal_max`<`volatility_ratio_stress_min`; both market features must align for normal or stressed. Significant disagreement and threshold gaps yield unknown

Pressure uses market facts only. Missing/inconsistent input sets quality unknown and every axis unknown/`INPUT_QUALIFICATION_FAILED`, never stressed or risk_off. Zero denominator reasons remain independent market-feature unknowns when declarations are qualified.

No fitted model, HMM, parameter optimizer, state memory, dwell time, or hysteresis is hidden here. Any later switching policy needs its own preregistered causal candidate/version and validation.

## Availability, expiry, and outputs

Output records schema/feature version, configuration/input digest, symbol/role, as_of, input calendar/factor/producer context, features, axes, and separate quality.

- `input_available_at`: declared complete input availability
- `decision_at`: actual evaluation/completed publication instant
- `available_at`: no earlier than either; equals decision_at for qualified observations, never the earlier raw-price publication time
- `valid_until`: as_of's official close_at + explicit ttl_seconds, exclusive

At decision_at≥valid_until the observation is expired and unknown. Replaying old closes or changing evaluation time never renews expiry. The usability helper returns true only for declared-qualified evidence at or after availability/decision and strictly before expiry; axes may still be unknown. True means usable evidence, not transaction permission.

Consumers must independently verify actual publication time, immutable V2 payload, P1/P2/P3 evidence, source identity, and expiry. available_at/decision_at checks validate declarations only; actual computation/publication-time proof remains P0 work. Synthetic future-row invariance is not real-provider PIT evidence. Hashes and pure functions are not authentication or production adoption proof.

## Validation and next admission

Run `PYTHONPATH=src python -m pytest -q tests/test_semiconductor_regime_observer_research.py tests/test_qqq_price_regime_observer_v2.py tests/test_plugin_signal_envelope_v2.py`, then the existing full tests, Ruff, whitespace check, and package build.

Synthetic tests cover future/late invisible-row invariance, late required bars, incomplete/unclosed sessions, unavailable factors, mismatched component dates/versions, zero variation/volatility, NaN/infinity/extreme finite values, duplicate/disordered dates, conflicts, TTL boundary/replay, feature-only mode, and original QQQ/V2 compatibility. Producer repo/entrypoint/config and causal-root/cutoff binding are separately tested.

These are contract/interface results, not real market backtests, economic alpha, provider PIT verification, production deployment, or active consumption. Further research still needs qualified real P0 inputs, frozen comparable baselines, preregistration/all-trial records, causal out-of-sample results, common costs/risk controls, component ablation, and real no-order paired shadow before approved use.
