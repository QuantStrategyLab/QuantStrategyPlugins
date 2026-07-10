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
| `automation_approved` | Strategy-side automation is allowed when the platform gate also passes | yes |
| `deprecated_compatibility` | Kept for replay or staged migration only | none |

## Three-Gate Rule

For any plugin-driven capital impact, all three gates must pass:

1. **Plugin schema gate**
   - The artifact must match a supported schema version and remain in `shadow`
     mode for the shared contract.
2. **Plugin evidence gate**
   - The plugin must be marked `automation_approved` and
     `position_control_allowed = true`.
   - If the platform enables automated position control, the runner should also
     carry a machine-readable `auditable_position_control` block with
     `evidence_package_id`, `evidence_valid_until`, and `bounded_budget`.
3. **Strategy/platform gate**
   - The consuming strategy must explicitly opt in to the plugin and remain
     allowed by the platform catalog.

If any gate fails, the plugin should stay notification-only or compatibility-only.

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
- Keep `position_control_allowed` narrow and explicit.
- Prefer a single shared policy registry instead of spreading allowlists across
  runners.
- When a strategy consumes a plugin for live capital impact, keep the platform
  notification path separate from the strategy execution path.

## Practical Interpretation

- If the artifact is only for human review, use `notification_only`.
- If the artifact is still a sidecar evidence layer, use `shadow_observer`.
- If the plugin is being prepared for automation, keep it in
  `automation_candidate` until the strategy gate also passes.
- If the plugin is no longer the preferred path, mark it
  `deprecated_compatibility` and keep it out of new runtime defaults.
