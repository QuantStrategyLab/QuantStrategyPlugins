# QuantStrategyPlugins

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
python -m pip install -e .
python -m pytest -q
```

## Useful docs

- [`docs/market-regime-control-plan.md`](docs/market-regime-control-plan.md)
- [`docs/market-regime-control-plan.zh-CN.md`](docs/market-regime-control-plan.zh-CN.md)

## License

See [LICENSE](LICENSE).
