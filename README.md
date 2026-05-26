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
  strategies. It writes shadow-mode artifacts and never calls brokers.
- `taco_rebound_shadow`: TQQQ-only event-rebound context notifier. It writes
  manual-review artifacts and never recommends position size or changes
  allocations. Softening/de-escalation events stay watch-only until post-event
  price rebound confirmation passes, which reduces early bottom-fishing alerts.
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
  --output-dir data/output/tqqq_growth_income/plugins/crisis_response_shadow
```

Build a TACO rebound notification artifact directly from a local price-history CSV:

```bash
qsp-build-taco-rebound-shadow-signal \
  --prices data/input/price_history.csv \
  --event-set geopolitical-deescalation \
  --as-of 2026-05-22 \
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
