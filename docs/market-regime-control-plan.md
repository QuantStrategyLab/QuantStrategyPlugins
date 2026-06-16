# Market Regime Control Design Plan

[简体中文](./market-regime-control-plan.zh-CN.md)

This document records the current design boundary, arbitration order, strategy
consumption policy, and backtest evidence for `market_regime_control`.

## Goals

`market_regime_control` is a unified deterministic market-regime facade. It
combines the previous crisis-defense, macro de-leveraging, and TACO event
rebound notification plugins into one versioned artifact for strategy
repositories to consume consistently.

Primary goals:

- Reduce position size and leverage when macro conditions, systemic crisis
  risk, or bubble-fragility risk deteriorate.
- Keep TACO's false-crisis, de-escalation, and rebound-context notification
  value without letting it bypass crisis defense.
- Avoid AI-driven trading decisions. AI may only provide shadow-only evidence
  review and notification support.
- Emit a stable `market_regime_control.v1` schema. Strategy repositories consume
  `notification` and `position_control` by schema, not by localized text.

Non-goals:

- This plugin repository does not call broker APIs or mutate account allocation.
- OSINT-style fields, such as a Pentagon pizza index, are watch-only evidence
  and do not enter the executable score by default.
- TACO does not increase position size by default and is not a crisis-period
  dip-buying switch.

## Component Responsibilities

`market_regime_control` keeps three deterministic components internally:

- `crisis_response_shadow`
  Handles hard crisis defense. When `true_crisis` or bubble fragility triggers,
  the unified plugin emits `risk_off` / `defend`; execution remains an
  explicit strategy-side opt-in.
- `macro_risk_governor`
  Handles macro de-leveraging. It scores price trend, realized volatility, VIX,
  and credit ETF relative stress, then emits `risk_reduced` or `risk_off`. HY
  OAS, financial-stress indices, Fear & Greed, put/call, safe-haven demand,
  VVIX, SKEW, MOVE, yield curves, dollar stress, market breadth, AAII/NAAIM,
  and a Pentagon pizza index are watch-only evidence by default. They can enter
  the executable score only when the explicit research switch
  `external_stress_actionable` is enabled.
- `taco_rebound_shadow`
  Handles TQQQ event-rebound notification. It emits manual-review notification
  context and local veto evidence, but it does not raise position size.
- `panic_reversal_shadow`
  Handles research-only VIX panic-reversal notification after volatility has
  fallen from a panic high and price confirmation is present. It emits
  manual-review context only; the sample is still too small, so it is disabled
  by default and cannot raise position size.

The unified artifact exposes five main sections:

- `notification`
  Whether a notification should be sent, route source, reason codes, and veto
  details.
- `position_control`
  Strategy-readable controls such as `risk_budget_scalar`, `leverage_scalar`,
  `risk_asset_scalar`, `taco_allowed`, and `blocked_actions`.
- `component_signals`
  Compact evidence from each component for notification and audit review.
- `execution_controls`
  Explicitly states that the plugin repository writes artifacts only and cannot
  place broker orders or mutate account configuration.
- `localized_messages` / `log_record`
  Provides `en-US` and `zh-CN` notification/log text. Trading logic must keep
  reading machine fields such as route, action, reason codes, and position
  controls. Localized strings are display and audit-log outputs only.

## Arbitration Order

The current order is risk-first:

1. `crisis_response_shadow` `true_crisis` or bubble fragility has top priority,
   emits `risk_off`, and vetoes TACO and panic reversal.
2. `macro_risk_governor` crisis state is next, emits `risk_off`, and vetoes
   TACO and panic reversal.
3. `macro_risk_governor` de-leveraging emits `risk_reduced`, scales down
   leverage or risk-asset budget, and vetoes TACO and panic reversal.
4. Data-quality kill switches or blocked component states block opportunity-side
   actions.
5. TACO or panic reversal may emit `opportunity_watch` and manual-review
   notification only when there is no crisis or macro de-risking route.
6. Watch-only signals notify but never grant position-control authority.

This keeps crisis, macro, and TACO behavior separate: defense first,
opportunity context second, and notification authority separate from execution
authority.

## Strategy Consumption

Strategy repositories should mount `market_regime_control/latest_signal.json`
instead of consuming the three older plugin artifacts directly.

Recommended policy:

- TQQQ growth/income strategy
  Consumes `position_control` by default. `risk_off` moves toward cash-like or
  non-risk assets; `risk_reduced` lowers leverage or risk budget based on local
  strategy configuration. TACO and panic reversal remain manual-review
  notification and local veto context only.
- SOXL/SOXX trend/income strategy
  Mounts the unified plugin by default. `risk_off` may move risk exposure toward
  defensive assets, while `risk_reduced` remains disabled in the strategy
  default config. SOXL keeps its reviewed SOXX trend and volatility de-levering
  gates, and may consume the deterministic
  `position_control.volatility_delever_context` retention profiles when its
  local volatility gate triggers. TACO, panic reversal, AI audit, OSINT, and
  localized notification copy remain manual-review context only.
- Global ETF, Russell 1000, and Mega Cap rotation
  strategies
  Support the unified plugin by default. `risk_reduced` should apply a 50% risk
  budget scale; `risk_off` should zero the risk-asset budget.
- DCA or low-frequency income strategies
  Default to notification-only and may allow explicit operator opt-in for
  position impact.

Legacy plugins remain available for historical backtests and compatibility
outputs. New integrations should prefer `market_regime_control`.

The runner uses an explicit consumption-policy registry rather than a loose
allowlist:

- `notification_allowed`: the runner may generate and distribute notification
  artifacts.
- `position_control_allowed`: a strategy runtime may automatically consume
  position-control fields.
- `evidence_status`: records whether the strategy/plugin pair is
  `automation_approved`, `notification_only`, or `deprecated_compatibility`.
- `since_version`: records the runner schema version where the permission
  became effective.

Permission boundaries live in documentation and machine-readable fields, not in
the human notification body:

- The plugin repository only writes artifacts and notifications. It does not
  call broker APIs or directly mutate account allocation.
- Automated position impact happens only when the strategy side explicitly
  consumes `position_control`, and only when `position_control_allowed = true`
  and `evidence_status = automation_approved`.
- `notification_only`, TACO, panic reversal, AI audit, and general notification
  targets are for manual review only.
- Human notification copy should contain only the situation and suggested
  action; it should not display internal governance fields such as
  `position_control_allowed`, `execution_controls`, route codes, or veto codes.

SOXL/SOXX is now in the strategy-level `market_regime_control` consumption
registry for automation-approved deterministic fields. It also keeps the
general `notification_targets.market_regime_notification` artifact for
portfolio-wide human review. That notification target is not a strategy, cannot
enter strategy runtime metadata, and cannot affect position sizing; this keeps
notification-only evidence separate from automated de-risking.

## Indicator Tiers

Current indicator tiers:

- Executable score:
  price trend, 63/252-day drawdown, realized volatility, VIX level/spike, and
  credit ETF relative stress.
- Watch-only:
  HY OAS, financial-stress indices, Pentagon pizza index, Fear & Greed,
  put/call, safe-haven demand, VIX/VIX3M term structure, VVIX, SKEW, MOVE, IG
  OAS, funding-stress spread, 10Y-2Y and 10Y-3M curves, DXY 21-day stress,
  50/200-day market breadth, new-high/new-low spread, advance-decline drawdown,
  AAII bearish-bullish spread, and NAAIM exposure.
- Not in automated position control:
  all watch-only fields. They are used for notification, evidence archiving, and
  future historical research.
- Research switch:
  `external_stress_actionable = true` can allow HY OAS, 63-day HY OAS widening,
  and financial-stress indices into the executable score. The default is fixed
  to `false`.

## Public Historical Data

`qsp-build-macro-external-context` builds a shared `external_context.csv` for
`macro_risk_governor` and `market_regime_control`.

The builder downloads public FRED/CBOE fields when available: VIX, VIX3M, VVIX,
SKEW, Cboe put/call ratios, HY/IG OAS, STLFSI/NFCI/ANFCI, 10Y-2Y, 10Y-3M,
trade-weighted dollar stress, and TED/funding stress.

CNN Fear & Greed, AAII, NAAIM, Pentagon pizza, MOVE, market breadth, and other
fields without a stable no-login historical CSV are not fabricated by the
builder. They must be injected with `--manual-context` and remain watch-only by
default.

ICE BofA OAS history depends on what the public FRED graph endpoint returns. If
FRED only provides a recent rolling window, long-cycle credit stress should rely
primarily on HYG/IEF and LQD/IEF ETF relative stress. Archived OAS history can
also be injected with `--manual-context`.

## Version Management

Current public contracts:

- Unified plugin schema: `market_regime_control.v1`
- Arbiter schema: `market_regime_arbiter.v1`
- Runner summary schema: `strategy_plugins.v1`
- Notification message schema: `strategy_plugin_messages.v1`
- Log record schema: `strategy_plugin_log.v1`
- Strategy consumption policy schema: emitted through `consumption_policy` under
  `strategy_plugins.v1`

Upgrade rules:

- Backward-compatible fields may be added within v1.
- Removing fields, changing field semantics, or changing default execution
  permission requires v2.
- Strategy repositories should validate consumable versions through
  `schema_version` and keep config-level opt-in/opt-out controls.
- Notification and log i18n is a display contract. Strategies must not use
  localized strings for trading decisions; they must consume machine-readable
  codes.
- Legacy plugins are marked with deprecated successors pointing to
  `market_regime_control`, but their historical entrypoints remain available for
  replaying older backtests.

## Backtest Conclusions

Real-product short/medium windows and long-cycle synthetic proxy tests support
the current design.

TQQQ real-product window, 2010-2026:

- `cash_vol30_5_7_vol_confirmed` improved CAGR by about `+1.03pp` versus the
  baseline.
- Max drawdown improved by about `+0.29pp`.
- COVID-window CAGR improved by about `+11.47pp`; max drawdown improved by
  about `+4.15pp`.

Public external-context test, 2010-02-12 to 2026-04-16:

- Core macro signals without external context:
  CAGR `24.74% -> 25.77%`, max drawdown `-35.07% -> -34.77%`, final equity
  about `+14.23%`.
- External fields as watch-only:
  CAGR, drawdown, and final equity were unchanged versus core macro signals;
  watch days rose from `343` to `558`, showing that the added cross-asset and
  sentiment fields expand notification evidence without changing automated
  position control.
- External hard data directly in the executable score:
  CAGR `24.99%`, max drawdown `-34.72%`, final equity only `+3.33%` versus the
  baseline. This was more conservative than the core macro signal and delivered
  a weaker return/drawdown tradeoff.
- Conclusion:
  Added external indicators should remain watch-only by default. Only price,
  VIX, and credit ETF signals stay in automated position control. STLFSI/HY OAS
  and similar hard data may remain behind a research switch, but should not gain
  default de-risking authority.

1999-2026 synthetic QQQ 3x proxy:

- Crisis-context version:
  CAGR `14.78% -> 18.93%`, max drawdown `-94.54% -> -87.63%`.
- Enhanced bubble-fragility version:
  CAGR `14.78% -> 19.87%`, max drawdown `-94.54% -> -86.60%`.
- Financial crisis window:
  CAGR `-45.25% -> -27.65%`, max drawdown `-59.87% -> -40.47%`.
- Dot-com bust window:
  after enhanced bubble fragility, CAGR `-67.78% -> -51.69%`; max drawdown
  improved by about `+7.94pp`.

Design implications:

- Financial-crisis defense is mainly handled by the `true_crisis` route and is
  suitable for hard de-risking.
- The dot-com bust cannot rely only on traditional crisis confirmation; bubble
  fragility should remain part of the route.
- TACO is not a defense component for these long-cycle crises. It should remain
  opportunity notification and manual-review context.

## Recommended Defaults

- Leveraged broad-index strategies:
  mount the unified plugin by default and allow `risk_off` to take effect.
- High-volatility sector leveraged strategies:
  SOXL mounts the unified plugin by default after the 2026-06-16 retention
  replay. Its default strategy config allows `risk_off` and deterministic
  volatility-delever retention context, but does not apply `risk_reduced`
  position impact by default.
- Rotation strategies:
  enable 50% risk scaling for `risk_reduced` and zero risk-asset budget for
  `risk_off`.
- TACO / panic reversal:
  notification-only by default; they can surface opportunity context only when
  no crisis or macro de-risking route is active. Panic reversal remains disabled
  by default until event-window and no-regression reports justify promotion.
- AI audit:
  no trading authority by default. It may write audit conclusions and
  notification evidence only.
