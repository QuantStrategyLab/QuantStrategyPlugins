# Plugin Lifecycle Policy

[简体中文](./plugin_lifecycle_policy.zh-CN.md)

This document defines the lifecycle ladder and gate model for strategy plugins.

## Design Goal

Plugins should be easy to observe, hard to misuse, and very hard to let affect
capital without explicit approval.

- AI may monitor and summarize plugin evidence.
- AI must not upgrade a plugin into live authority by itself.
- Notification delivery is not the same as position-control authority.
- Compatibility mounts can exist for history, but they should not expand live
permission by accident.

## Recommended Plugin Stages

| Stage | Meaning | Capital impact |
| --- | --- | --- |
| `research_only` | Research artifact, not meant for platform runtime | none |
| `notification_only` | Can notify humans, but cannot control position | none |
| `shadow_observer` | Can be attached to runtime metadata and audit trails | none |
| `automation_candidate` | Has enough evidence to be considered for automation | gated |
| `automation_approved` | Legacy evidence label retained for replay; not direct allocation authority | none |
| `deprecated_compatibility` | Kept for replay or staged migration only | none |

## V2 Authority Rule

Plugin artifacts never carry direct capital authority. They may provide a
signal, observation, or bounded risk suggestion to an owning strategy
candidate. That strategy must validate the behavior through its lifecycle and
submit any target through the central Risk Gate.

Legacy v1 `position_control_allowed` and `automation_approved` fields are kept
readable for historical artifacts, but the runner emits them as
notification/shadow-only and cannot use them to mutate allocations.

## Current Policy Shape

- `src/quant_strategy_plugins/plugin_policies.py` is the machine-readable source
  for lifecycle, consumption, notification-target, schema-version, and
  deprecated-successor policy.
- `market_regime_control` is the unified default runtime plugin.
- `crisis_response_shadow`, `macro_risk_governor`, and `taco_rebound_shadow`
  remain compatibility mounts or notification-only sidecars.
- `panic_reversal_shadow` remains research-heavy and should stay notification-only
  unless it is separately promoted.

## Recommended Operating Rules

- Keep `notification_allowed` broad for research visibility.
- Keep `position_control_allowed = false`; strategy-owned adapters consume
  validated signals through the central Risk Gate.
- Prefer a single shared policy registry instead of spreading allowlists across
  runners.
- When a strategy consumes a plugin for live capital impact, keep the platform
  notification path separate from the strategy execution path.

## Practical Interpretation

- If the artifact is only for human review, use `notification_only`.
- If the artifact is still a sidecar evidence layer, use `shadow_observer`.
- If plugin behavior is being prepared for automation, promote a new owning
  strategy candidate; do not promote the plugin into allocation authority.
- If the plugin is no longer the preferred path, mark it
  `deprecated_compatibility` and keep it out of new runtime defaults.
