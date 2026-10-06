# Ten-year rates context observation research

Status: `UNVALIDATED_RESEARCH`. This is one source-agnostic, standard-library pure observation function. It is not a downloader, enabled plugin, strategy policy, or production adoption. Existing modules, package exports, runner/catalog entries, wide external-context CSVs, defaults, dependencies, and runtime pins are unchanged.

[中文合同](rates-context-observer-research.zh-CN.md)

## Purpose and boundary

`quant_strategy_plugins.rates_context_observer_research.build_rates_context_observation(snapshot, config)` describes ten-year nominal yield, real yield, independently reported breakeven, and an explicitly approximate nominal-minus-real yield spread. It returns facts and data-availability diagnostics only. There are no signals, votes, direction/risk classifications, positions, budgets, orders, notifications, files, clocks, models, or provider calls.

The existing wide CSV merge coerces each column to numeric values. It cannot preserve this contract's source, revision, or publication metadata; do not insert these records into that merge and assume provenance survives. This module neither extends `DEFAULT_FRED_SERIES` nor modifies macro watch/actionable scoring.

## Input and configuration

The input has exactly `schema_version=qsl.rates-context-input.research.v1`, `decision_at`, and `series`. `decision_at` is the actual evaluation/receipt decision time declared by the caller, with an explicit ISO timezone. `series` contains only the optional roles `nominal_10y`, `real_10y`, and `breakeven_10y`; a missing role yields explicit unknown. All three roles are ten-year measurements, not ETF prices or another tenor relabeled as ten-year.

Each series has exactly:

- `source_id`: identity of the actual source collection; the nominal/real pair must match
- `series_id`: the actual measured series identity, not a shared display name
- `basis`: nominal/real accept `treasury_par_yield` or `treasury_constant_maturity_yield`; reported breakeven accepts only `reported_breakeven`
- `unit`: exactly `percent`, meaning percentage points per annum where relevant; `4.2` means 4.2%, not 0.042
- `rows`: caller-frozen observations, in strictly increasing observation-date order

The same `source_id + series_id` identity cannot occupy two roles. Such reuse, including a breakeven role repeating a yield series, makes both roles unknown with `ROLE_SOURCE_IDENTITY_AMBIGUOUS`; a renamed role does not turn one observation into independent evidence.

Each row has exactly `observation_date`, `value`, `available_at`, `received_at`, and `revision_id`:

- Dates are exact `YYYY-MM-DD` source observation labels; no fixed time is manufactured from the label
- Values are finite non-Boolean numbers; negative yields are valid
- `available_at` is the caller's evidence-backed time that this exact revision became available, not the import time or scheduled release time
- `received_at` is when this exact revision reached the caller; both times require explicit timezones and are normalized to UTC
- Missing/invalid times remain unknown; receipt cannot precede availability
- `revision_id` identifies the selected frozen revision; `latest` is rejected. Two visible revisions of one date are ambiguous and rejected rather than silently taking the last row

Configuration has exactly `schema_version=qsl.rates-context-config.research.v1`, `window_start`, `window_end`, and `max_observation_age_days`. All are mandatory. Start must precede end. Maximum age is a nonnegative integer number of UTC calendar days from the latest visible observation date to decision time. It is an explicit research allowance, not a calibrated freshness recommendation.

## Exact windows, units, and unknowns

Each series requires observations on both exact common endpoint dates. The module never selects a nearest date, carries a value forward, interpolates, or changes a window to fit a source. Endpoint differences do not prove full trading-session coverage. A missing start/end is `WINDOW_ENDPOINT_UNAVAILABLE`.

`change_bp = 100 × (end_percent − start_percent)`. It is a yield change in basis points, not a price return or relative percentage change. For example, synthetic 4.0% to 4.2% is +20 bp. This example is `SYNTHETIC_FIXTURE_ONLY` and is not downloaded data.

For historical decisions, dates outside the explicit window and rows published or received after `decision_at` are invisible before value/revision validation. Hidden later revisions and future values therefore cannot alter the historical observation. Unparseable selectors cannot establish invisibility and produce unknown. Within the visible projection, duplicates, reversed dates, nonfinite values, missing metadata, unknown basis, wrong units, stale observations, or insufficient endpoints produce unknown and no numeric change. Invalid configuration raises `ContractError` without echoing input.

Each series independently retains its source/series/basis, endpoint observation/revision/availability/receipt metadata, latest observation date, visible count, observation age, date-level availability delay, and receipt lag. Availability delay is a difference of UTC date labels, not a measured market-close-to-publication latency. Stale data do not become fresh because they were imported today. One missing series does not erase valid facts from another; aggregate quality remains unknown if the complete bundle or pair comparison is unavailable.

## Approximate spread is separate from reported breakeven

Only nominal and real observations with the same declared source collection, measurement basis, units, and exact endpoints form `approximate_yield_spread`. It is labeled `APPROXIMATE_NOMINAL_MINUS_REAL_YIELD_SPREAD`. It is not automatically an official published breakeven, a pure inflation expectation, or a second independent risk vote.

Examples of identity distinctions for a future caller-owned adapter:

- A direct Treasury nominal-par/real-par pair is identified as its Treasury collection and `treasury_par_yield`; its difference remains an approximate spread
- A caller-authorized H.15/FRED DGS10/DFII10 pair retains the H.15/FRED identities and `treasury_constant_maturity_yield`; it is not mixed with a separately sourced Treasury record merely because both say ten-year
- An independently acquired T10YIE retains its actual source/revision/publication metadata and `reported_breakeven`. It is returned separately and never filled from the nominal-real subtraction

The H.15 nominal and inflation-indexed constant-maturity series are source-specific yield measurements. [H.15 definitions](https://www.federalreserve.gov/releases/h15/) and [Treasury interest-rate statistics](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics) explain the underlying tenors and methods. The [DGS10](https://fred.stlouisfed.org/series/DGS10), [DFII10](https://fred.stlouisfed.org/series/DFII10), and [T10YIE](https://fred.stlouisfed.org/series/T10YIE) metadata describe percent/daily units; T10YIE's notes separately describe its derivation and the direct-Treasury source used since June 21, 2019. Shared numerical values do not establish shared release times or immutable historical revisions.

## Source rights and historical evidence

This phase contains no new real-data collection, provider credentials, copied provider dataset, or redistributed observations. Tests use labeled synthetic values. Source links are metadata references and do not grant permission, certify a feed, or establish provider authenticity.

At the October 6, 2026 review, FRED labels DGS10/DFII10 `Public Domain: Citation Requested` and T10YIE `Copyrighted: Citation Required`. A future data collector must check the applicable source rights, attribution, service/API terms, and intended use, including the restrictions in the [current FRED terms](https://fred.stlouisfed.org/legal/). This module does not perform that authorization review or assert a license. A dataset's public-domain status does not override service access/use terms. No new FRED collector or extension of the existing CSV fetch mechanism is implemented here.

Every output remains `UNVALIDATED_RESEARCH`, `assurance=CALLER_DECLARATIONS_AND_CONSISTENCY_ONLY`, `historical_pit_verified=false`, `backtest_eligible=false`, and `position_control_allowed=false`. `declared_available` means only that supplied records satisfy internal timing and consistency checks. An available/received declaration or revision string is not a verified capture. Genuine historical PIT use still needs immutable source snapshots, actual publication/receipt evidence, source rights, and independent producer/consumer verification. Loading an old historical CSV today must not invent its historical `available_at`.

## Offline verification and next step

Focused tests can run with `python -m unittest discover -s tests -p test_rates_context_observer_research.py` in an environment whose network/child-process/model/notification entrypoints are blocked before importing tests. They load the pure module by file specification, isolating existing package-level optional dependencies. The normal package import and complete repository suite remain separate checks.

Synthetic coverage includes percent-to-bp arithmetic, independent breakeven, individual source delays, negative yields, future-row/revision invariance, missing publication/receipt evidence, today's import of old data, nonfinite/Boolean/string values, wrong units, mixed sources/methodologies, reversed dates, visible duplicate revisions, wrong/missing endpoints, stale observations, invalid configuration, strict JSON, input immutability, and absent trading fields.

This is a preparation step. A future authorized collector/consumer integration must retain the row-level evidence rather than using the lossy wide CSV, then validate genuine source coverage/availability, strategy-specific economic usefulness, and approved consumption. Historical breadth membership/prices and NDX participation are separate gaps; this phase implements neither breadth nor an NDX proxy. No runtime adoption follows from a pure function or passing synthetic tests.
