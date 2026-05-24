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
- `taco_rebound_shadow`: research-only rebound-budget observer. The generic
  runner keeps it gated until promotion criteria are met.

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
