# QuantStrategyPlugins

<!-- qsl-doc-overview:start -->

> ⚠️ 投资有风险，不构成投资建议，仅供学习交流用途。
> ⚠️ Investing involves risk. This project does not provide investment advice and is for educational and research purposes only.

## Open-source overview / 开源项目入口

| Item | Description |
| --- | --- |
| Project type | plugin package |
| What it does | Sidecar strategy plugins for risk regime, crisis context and notification-only overlays used by QuantStrategyLab runtimes. |
| 中文说明 | 策略 sidecar 插件包，用于风险状态、危机上下文和通知/影子信号，不直接替代核心策略。 |
| Current status | Plugin package. Plugins should be mounted only when backtest evidence and runtime policy explicitly allow them. |

### Quick start

- `python -m pip install -e '.[test]'`
- `python -m pytest -q`

### Deploy / operate safely

Publish through platform or snapshot plugin workflows; keep notification-only plugins out of execution paths unless explicitly accepted.

### Strategy performance / evidence boundary

See `docs/market-regime-control-plan.md` and `.zh-CN.md` for CAGR/drawdown impact and watch-only versus actionable signal policy.

> Detailed runbooks, migration notes, workflow internals, and historical decisions are kept below. Start with this overview before using the lower-level operational sections.

<!-- qsl-doc-overview:end -->

> ⚠️ 投资有风险，不构成投资建议，仅供学习交流用途。


## 中文摘要

- 完整中文版见 [`README.zh-CN.md`](README.zh-CN.md)；本节保留在英文文件顶部，方便从当前文件直接找到中文入口。
- 用途：本文档围绕 `QuantStrategyPlugins`，用于理解 `QuantStrategyPlugins` 的配置、运行、部署、研究或验收边界。
- 主要覆盖：`What Is Public`、`What Stays Out`、`Plugins`、`Usage`、`Notification and Log i18n`。
- 阅读顺序：先确认边界、输入输出和权限要求，再执行文档里的命令、CI、dry-run、发布或切换步骤。
- 风险提示：涉及实盘、密钥、权限、Cloud Run、交易所或券商 API 的变更，必须先在测试环境或 dry-run 验证；不要只凭示例直接修改生产。
- 英文正文保留更完整的命令、字段名和配置键；如果摘要和正文不一致，以正文中的实际命令和配置为准。
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
  It scores price trend, realized volatility, VIX, and credit-pair stress. The
  artifact can expose
  `leverage_scalar` and `risk_asset_scalar` to strategy runtimes that explicitly
  opt in through mounted metadata. External hard-data fields such as HY OAS and
  financial-stress indices, plus OSINT-style, sentiment, options-volatility,
  rates, breadth, funding, and liquidity fields such as a Pentagon pizza index,
  Fear & Greed, put/call, VVIX, SKEW, MOVE, yield curves, dollar stress, and
  safe-haven demand, are kept as watch-only evidence by default. They do not
  contribute to the actionable trading score unless explicitly enabled for
  research.
- `market_regime_control`: unified deterministic facade for crisis, macro, and
  TACO signals. Only strategies with positive backtest evidence should mount
  position controls for automated consumption; SOXL/SOXX currently receives
  broad macro/crisis signals through `notification_targets` only. Stock/ETF
  rotation strategies should consume the same artifact through their local
  risk-scaling policy and keep TACO as notification-only. See the
  [Market Regime Control design plan](docs/market-regime-control-plan.md).
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

Build the public hard-data `external_context` CSV used by macro and unified
market-regime plugins:

```bash
qsp-build-macro-external-context \
  --start 1999-01-01 \
  --output data/output/market_regime_control/input/external_context.csv
```

The builder downloads public FRED/CBOE fields when available: VIX, VIX3M,
VVIX, SKEW, Cboe put/call ratios, HY/IG OAS, financial-stress indices, yield
curves, trade-weighted dollar stress, and TED/funding stress. Fields without a
stable no-login historical feed, such as CNN Fear & Greed, AAII, NAAIM,
Pentagon pizza, MOVE, and breadth, can be supplied with `--manual-context`.
OAS coverage follows what the public FRED graph endpoint returns; archived
local OAS history can be injected with the same manual context path.

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

## Notification and Log i18n

Runner-managed artifacts add display-only i18n fields for notifications and
logs:

- `localized_messages.schema_version = strategy_plugin_messages.v1`
- `localized_messages.notification.en-US` / `localized_messages.notification.zh-CN`
- `localized_messages.log.en-US` / `localized_messages.log.zh-CN`
- `log_record.schema_version = strategy_plugin_log.v1`
- `market_regime_control.notification.localized_message_schema_version`

Strategy and broker runtimes should keep trading logic on machine fields such
as `schema_version`, `canonical_route`, `suggested_action`, `reason_codes`, and
`position_control`. Localized strings are for human notification surfaces and
logs only. `market_regime_control.notification` mirrors the localized
notification text and reason labels so existing notification code can render a
message without translating route/action codes itself.
General notification targets are configured under `notification_targets`, not as
synthetic strategies, and never receive position-control permission.

## Local Checks

```bash
python -m pip install -e '.[test]'
python -m pytest -q
ruff check .
```

## License

MIT License. Copyright (c) 2026 QuantStrategyLab.
