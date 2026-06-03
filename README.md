# QuantStrategyPlugins

[Chinese README](README.zh-CN.md)

> ⚠️ Investing involves risk. This project does not provide investment advice and is for educational and research purposes only.

## What this project does

QuantStrategyPlugins is a **Plugin package** in the QuantStrategyLab ecosystem. It provides open sidecar strategy plugins that QuantStrategyLab runtimes can load without changing platform code.

## Who this is for

- Engineers and researchers who want to inspect, reproduce, or extend this part of the QuantStrategyLab stack.
- Operators who need a clear entry point before reading the deeper runbooks or workflow files.
- Reviewers who need to understand the repository purpose, safety boundary, and evidence requirements before enabling automation.

## Current status

Extension package; plugin eligibility still depends on strategy validation.

## Repository layout

- `src/`: main library and runtime code.
- `tests/`: unit and contract tests.
- `docs/`: detailed design notes, runbooks, and evidence docs.
- `.github/workflows/`: CI, scheduled jobs, and deployment workflows.
- `scripts/`: operator scripts and local helpers.

## Quick start

From a fresh clone:

```bash
python -m pip install -e .
python -m pytest -q
```

If a command requires credentials, run it only after reading the relevant workflow or runbook and configuring secrets outside Git.

## Deployment and operation

Install or package the plugins with the target runtime, then point the platform loader to the plugin entrypoint. Validate in dry-run before enabling live execution.

Prefer manual or dry-run execution first. Enable schedules or live execution only after logs, artifacts, permissions, and rollback steps are reviewed.

## Strategy performance and evidence

Plugin code does not make a strategy live-ready by itself. Use the associated strategy research artifacts to evaluate returns, drawdowns, benchmark comparison, and robustness.

README files are intentionally not a source of dated performance promises. Re-run the relevant tests, backtests, or pipeline jobs before relying on any result.

## Safety notes

- Never commit API keys, broker credentials, OAuth tokens, cookies, or account identifiers.
- Run new strategies and platform changes in dry-run or paper mode before any live execution.
- Review generated orders, artifacts, and logs manually before enabling schedules.

## Contributing

Keep changes small, reproducible, and covered by the narrowest useful tests. For strategy-facing changes, include the evidence artifact or command used to validate behavior.

## License

See [LICENSE](LICENSE) if present in this repository.
