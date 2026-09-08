# QuantStrategyPlugins


## QSL architecture role

- **Layer**: `strategy-lib`.
- **Responsibility**: sidecar strategy plugin package.
- **Owns**: plugin contracts, market-regime controls, notification/research plugin outputs.
- **Consumes**: QuantPlatformKit and strategy/pipeline consumers.
- **Must not**: decide live eligibility or connect to brokers directly.

[Chinese README](README.zh-CN.md)

> Investing involves risk. This project does not provide investment advice and is for education, research, and engineering review only.

## What this repository is

QuantStrategyPlugins is a QuantStrategyLab strategy plugin package. It provides sidecar strategy plugins such as market-regime controls, notification artifacts, and research-only plugin outputs.

It supports the system but does not decide which strategy should be live. Strategy eligibility remains in the strategy and snapshot repositories; broker execution remains in the platform repositories.

## Design boundary

- Keep contracts stable and versioned where downstream repositories depend on them.
- Prefer backward-compatible changes unless a coordinated migration is planned.
- Keep secrets and environment-specific settings outside the shared library code.
- Document changes that affect multiple platforms or strategy packages.

## Repository layout

- `src/`: library and runtime code.
- `tests/`: unit, contract, and regression tests.
- `docs/`: runbooks, design notes, evidence, and integration contracts.
- `.github/workflows/`: CI, scheduled jobs, release, or deployment workflows.
- `scripts/`: operator scripts and local helpers.

## Quick start

```bash
python -m pip install -e '.[test,ai]'
python -m pytest -q
```

The default runtime install (`python -m pip install .`) does not include the AI
client. Install `.[ai]` only for an approved AI consumer; it adds the pinned,
standard-library-only AIAuditBridge SDK, not the gateway service. Installation
does not enable AI audits, configure credentials, or grant execution authority.
The full test suite uses the real installed SDK with synthetic HTTP responses;
it does not call a model or verify production authentication.

## Useful docs
- [`docs/plugin_lifecycle_policy.md`](docs/plugin_lifecycle_policy.md)
- [`docs/market-regime-control-plan.md`](docs/market-regime-control-plan.md)
- [`docs/market-regime-control-plan.zh-CN.md`](docs/market-regime-control-plan.zh-CN.md)

## Community and security

- See [CONTRIBUTING.md](CONTRIBUTING.md) for pull request scope, local verification, and documentation expectations.
- Follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for maintainer and contributor conduct.
- Report credential, automation, broker, exchange, or cloud-resource vulnerabilities through [SECURITY.md](SECURITY.md); do not open public issues for secrets or live-execution risk.

## License

See [LICENSE](LICENSE).
