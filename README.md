# QuantStrategyPlugins

Sidecar strategy plugin package that emits QuantPlatformKit-compatible signal artifacts.

English | [简体中文](README.zh-CN.md)

## Status

Experimental. Use at your own risk. This project is not financial advice and
does not guarantee any trading result. Its outputs are research evidence, not
trading instructions.

## What this is

QuantStrategyPlugins provides sidecar strategy plugins: market-regime controls,
shadow signals, and research-only output. Each plugin emits a signal envelope
that QuantPlatformKit consumers can read. Plugins run locally against price
history and write artifacts, so strategy and pipeline repositories can add
regime and risk context without changing broker-facing code. It is aimed at
engineers extending strategy behavior.

## What this is not

It does not decide live eligibility. It does not connect to a broker or place
orders. It does not grant execution authority.

## Quick start

Requires Python 3.11 or newer.

```bash
python -m pip install -e '.[test]'
python -m pytest -q
```

Inspect the plugin runner options. The runner reads a TOML config passed with
`--config`; a sample is at `docs/examples/strategy_plugins.example.toml`.

```bash
qsp-run-strategy-plugins --help
```

The default install does not include the optional AI audit client. Install
`.[ai]` only if you use that client; it adds the pinned AI gateway client but
does not enable audits, configure credentials, or grant execution authority.

## Configuration

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `YFINANCE_PROXY` | No | none | Proxy override for Yahoo Finance price downloads. |
| `HTTPS_PROXY` | No | none | Proxy for outbound price downloads. |
| `HTTP_PROXY` | No | none | Proxy for outbound price downloads. |
| `ALL_PROXY` | No | none | Fallback proxy for outbound price downloads. |

The optional AI audit client reads its endpoint and token from the environment.
It stays disabled unless you configure and enable it.

## Repository layout

```
src/        plugin implementations and signal envelopes
scripts/    plugin runner and research scripts
docs/       lifecycle policy and plugin design notes
tests/      unit and contract tests
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Security

See [SECURITY.md](SECURITY.md). Do not open a public issue for a vulnerability.
Keep credentials, private data, and external service tokens out of Git and logs.

## License

MIT. See [LICENSE](LICENSE).
