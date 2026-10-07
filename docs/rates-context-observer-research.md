# Ten-year rates context observation research

Status: `UNVALIDATED_RESEARCH`. This module has source-agnostic, standard-library pure observation entry points. It is not a downloader, enabled plugin, strategy policy, or production adoption. Existing modules, package exports, runner/catalog entries, wide external-context CSVs, defaults, dependencies, and runtime pins are unchanged.

[中文合同](rates-context-observer-research.zh-CN.md)

## Purpose and boundary

`quant_strategy_plugins.rates_context_observer_research.build_rates_context_observation(snapshot, config)` describes ten-year nominal yield, real yield, independently reported breakeven, and an explicitly approximate nominal-minus-real yield spread. It returns facts and data-availability diagnostics only. There are no signals, votes, direction/risk classifications, positions, budgets, orders, notifications, files, clocks, models, or provider calls.

The existing wide CSV merge coerces each column to numeric values. It cannot preserve this contract's source, revision, or publication metadata; do not insert these records into that merge and assume provenance survives. This module neither extends `DEFAULT_FRED_SERIES` nor modifies macro watch/actionable scoring.

## Existing v1 input and configuration

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

## Explicit forward-known v2 entry point

build_rates_context_observation_v2(snapshot, config) is a separate pure entry
point in the same module. It accepts only qsl.rates-context-input.research.v2
and returns qsl.rates-context-observation.research.v2. The original v1 entry
point, constants, input/output semantics and rejection behavior remain unchanged.
Neither entry point automatically upgrades the other's input. V2 never substitutes
first-seen for v1 available_at.

The v2 root has exactly schema_version, availability_basis, collector_id,
decision_at and series. availability_basis is collector_first_seen. collector_id
identifies the collector to which the declared first-seen time belongs: a nonempty,
whitespace-trimmed string of at most 256 characters. Existing source/series/basis,
percent-unit roles and explicit v1 window/age configuration are reused. There is
no MSS family, catalog or runtime consumer registration.

Each v2 row has exactly:

- observation_date, value, revision_id
- source_published_at: explicitly null, never omitted or inferred
- first_seen_at: when the named collector first completely received this declared semantic row version
- received_at: when the research consumer received that fixed version
- capture_sha256: the declared hash of the original complete response retained when the row version was first seen
- row_sha256: the producer's declared immutable row-content reference

Both hashes require lowercase 64-hex syntax. The observer does not read the
response, recompute either hash, authenticate origin or clocks, establish an
earliest capture, or verify the producer's hashing algorithm. These are references
and consistency checks, not historical PIT proof. The collector retains original
bytes/capture records externally. Repeated downloads must not refresh an old
first_seen or replace its first-capture reference with the latest whole-file hash.
Corrections require separately retained versions; old accepted decisions are not
rewritten. This stateless function cannot enforce those rules across calls.

### Time projection and visible conflicts

V2 timestamps require YYYY-MM-DDTHH:MM:SS, optionally 1–6 fractional second
digits, followed by Z or ±HH:MM (offset hours <=23, minutes <=59). Greater
precision, comma fractions and second-bearing offsets are unsupported and remain
unknown; times are never truncated or rounded. Valid timestamps normalize to UTC.
Selected rows require
first_seen_at <= received_at <= decision_at; the UTC first-seen date cannot
precede the observation date. known_at is the later first-seen/receipt time,
which equals receipt under valid ordering. It is not a publication timestamp.

Dates outside the explicit window, future observation dates, and rows whose
first-seen or receipt is later than the decision are excluded before non-selector
fields. Hidden rows cannot affect counts, validation, identities, endpoint records
or numeric results. An unparseable selector cannot prove invisibility and produces
unknown unless another valid selector has already excluded the row.

Visible rows retain strict chronological order. Two rows for one date, including
exact repeats, are ambiguous: no sorting, deduplication, latest-wins or revision
selection. A duplicated endpoint has no selected endpoint metadata. Conflicting
content or timing under one observation/revision identity is unknown. Reuse of one
row hash for different observation dates or values within a series is unknown.
One capture hash may legitimately cover multiple different rows.

An old observation first captured today may be known today when its explicit
window/age policy permits it. It is never visible to an earlier decision. Age stays
observation-date age, not capture/receipt age; today's import does not refresh it.

### Output and assurance

V2 preserves collector/basis and each unambiguous endpoint's null publication,
first-seen, receipt, known-at, revision and hash references. There is no available_at
field. first_seen_delay_calendar_days compares date labels;
consumer_receipt_lag_seconds measures first-seen-to-consumer receipt. Neither is
source-publication latency or market-close-to-publication latency.

Missing/invalid fields, identities, times, nonfinite values, visible conflicts,
wrong roles/bases/units, stale observations or unavailable exact endpoints produce
unknown and no numeric change. Invalid configuration retains ContractError.
AI, opportunity and control fields are outside this exact input contract.

The same-source nominal/real approximate spread remains separate from independent
reported breakeven. Missing breakeven does not erase valid nominal/real declaration
facts or a valid pair difference; overall quality remains unknown. Every output
retains UNVALIDATED_RESEARCH, CALLER_DECLARATIONS_AND_CONSISTENCY_ONLY,
historical_pit_verified=false, backtest_eligible=false and
position_control_allowed=false.

This is offline contract preparation. Actual capture, source rights, retained
source bytes, genuine first-seen clocks, forward history, economic qualification
and approved consumption remain unverified. A later separately reviewed MSS
adapter can consume fixed v2 fields without changing v1. Real collection/adoption
need their own evidence; pre-collection historical availability is not recreated.

The existing focused unittest command runs original v1 plus synthetic v2 cases:
version/collector gates, arrival boundaries, old-date visibility without backdating,
stale age, hidden future/revision invariance, visible ambiguity, hash-reference
consistency, partial series, absent independent breakeven, strict JSON and unchanged
inputs. Pure tests do not prove external first-seen persistence.
