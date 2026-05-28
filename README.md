# QuantStrategyPlugins

Open sidecar strategy plugins for QuantStrategyLab runtimes.

Documentation: English | [简体中文](README.zh-CN.md)

The repository emits JSON signal artifacts that are consumed through
`quant_platform_kit.common.strategy_plugins`. Platform repositories such as
Interactive Brokers, Schwab, LongBridge, and Firstrade only load artifacts and
send notifications; plugin research and signal generation live here.

## What Is Public

- Plugin source code and synthetic tests.
- The artifact schema used by platform runtimes.
- Example local TOML config with placeholder paths.

## What Stays Out

- Broker credentials, tokens, account IDs, and SMTP settings.
- GCS bucket names, Cloud Run service names, and production deploy workflows.
- Generated `data/output` artifacts and proprietary runtime configuration.
- Non-public datasets. Tests use synthetic price histories.

## Plugins

- `crisis_response_shadow`: black-swan defense observer for leveraged US equity
  strategies. It writes shadow-mode artifacts and never calls brokers. It can
  optionally run AI shadow audit: the model audits evidence consistency and data
  gaps only, never overrides the deterministic route, places orders, or changes
  allocations. Local Codex is tried first when enabled; OpenAI-compatible and
  Anthropic fallback endpoints can be configured.
- `macro_risk_governor`: deterministic macro de-leveraging governor for TQQQ.
  It scores price trend, realized volatility, VIX, credit-pair stress, and
  optional external financial-stress fields. The artifact can expose
  `leverage_scalar` and `risk_asset_scalar` to strategy runtimes that explicitly
  opt in through mounted metadata. OSINT-style fields such as a Pentagon pizza
  index are kept as watch-only evidence and do not contribute to the actionable
  trading score.
- `market_regime_control`: unified deterministic facade for crisis, macro, and
  TACO signals. Levered strategies can consume position controls directly;
  stock/ETF rotation strategies should consume the same artifact through their
  local risk-scaling policy and keep TACO as notification-only.
- `taco_rebound_shadow`: TQQQ-only event-rebound context notifier. It writes
  manual-review artifacts and never recommends position size or changes
  allocations. Softening/de-escalation events stay watch-only until post-event
  price rebound confirmation passes, which reduces early bottom-fishing alerts.
  It can optionally run the same shadow-only AI audit on event/source quality.
- TACO panic-rebound research and portfolio/overlay backtests also live here;
  snapshot pipeline repositories keep only compatibility entrypoints.

## Usage

Run a plugin config:

```bash
qsp-run-strategy-plugins --config docs/examples/strategy_plugins.example.toml
```

Build a crisis response artifact directly from a local price-history CSV:

```bash
qsp-build-crisis-response-shadow-signal \
  --prices data/input/price_history.csv \
  --as-of 2026-05-22 \
  --ai-audit-enabled \
  --output-dir data/output/tqqq_growth_income/plugins/crisis_response_shadow
```

AI audit reads API settings from environment variables:

- `QSP_STRATEGY_PLUGIN_AI_AUDIT_CODEX_ENABLED`, default `true`
- `QSP_STRATEGY_PLUGIN_AI_AUDIT_CODEX_MODEL`, optional label for the local Codex provider
- `QSP_STRATEGY_PLUGIN_AI_AUDIT_API_KEY`, falling back to `QSP_CRISIS_AI_AUDIT_API_KEY` / `OPENAI_API_KEY`
- `QSP_STRATEGY_PLUGIN_AI_AUDIT_BASE_URL`, falling back to `QSP_CRISIS_AI_AUDIT_BASE_URL` / `OPENAI_API_BASE_URL` / `OPENAI_BASE_URL`
- `QSP_STRATEGY_PLUGIN_AI_AUDIT_MODEL`, falling back to `QSP_CRISIS_AI_AUDIT_MODEL` / `OPENAI_MODEL`
- `QSP_STRATEGY_PLUGIN_AI_AUDIT_FALLBACK_API_KEY` / `QSP_STRATEGY_PLUGIN_AI_AUDIT_FALLBACK_BASE_URL` / `QSP_STRATEGY_PLUGIN_AI_AUDIT_FALLBACK_MODEL`
- `QSP_STRATEGY_PLUGIN_AI_AUDIT_ANTHROPIC_API_KEY`, falling back to `QSP_CRISIS_AI_AUDIT_ANTHROPIC_API_KEY` / `ANTHROPIC_API_KEY`
- `QSP_STRATEGY_PLUGIN_AI_AUDIT_ANTHROPIC_MODEL` / `QSP_STRATEGY_PLUGIN_AI_AUDIT_ANTHROPIC_BASE_URL` / `QSP_STRATEGY_PLUGIN_AI_AUDIT_ANTHROPIC_VERSION`

If the runtime already injects `ANTHROPIC_API_KEY`, the strategy plugins can reuse it. Use `QSP_STRATEGY_PLUGIN_AI_AUDIT_ANTHROPIC_API_KEY` only when this audit path needs an explicit service-specific override.

Build a TACO rebound notification artifact directly from a local price-history CSV:

```bash
qsp-build-taco-rebound-shadow-signal \
  --prices data/input/price_history.csv \
  --event-set geopolitical-deescalation \
  --as-of 2026-05-22 \
  --ai-audit-enabled \
  --output-dir data/output/tqqq_growth_income/plugins/taco_rebound_shadow
```

Generated artifacts include `latest_signal.json`, dated JSON, dated CSV, and
an evidence CSV. `latest_signal.json` is the file platform runtimes mount via
`*_STRATEGY_PLUGIN_MOUNTS_JSON`.

## Local Checks

```bash
python -m pip install -e '.[test]'
python -m pytest -q
ruff check .
```

## License

MIT License. Copyright (c) 2026 QuantStrategyLab.
