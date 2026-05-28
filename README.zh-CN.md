# QuantStrategyPlugins

QuantStrategyLab 的开源侧车策略插件仓库。

文档：[English](README.md) | 简体中文

本仓库生成 JSON 信号 artifact，平台运行时通过
`quant_platform_kit.common.strategy_plugins` 读取这些 artifact。Interactive
Brokers、Schwab、LongBridge、Firstrade 等平台仓库只负责加载 artifact、发送通知和执行平台侧逻辑；插件研究、信号生成和证据输出放在这个仓库。

## 开源范围

- 插件源码和使用合成数据的测试。
- 平台运行时读取的 artifact schema。
- 带占位路径的本地 TOML 示例配置。

## 不进入开源仓库的内容

- 券商凭据、token、账号 ID、SMTP 设置。
- GCS bucket 名称、Cloud Run 服务名、生产部署 workflow。
- 生成的 `data/output` artifact 和私有 runtime 配置。
- 非公开数据集。测试只使用合成价格历史。

## 插件

- `crisis_response_shadow`：面向杠杆美股策略的黑天鹅防守观察插件。它只写入 shadow-mode artifact，不调用券商接口。
  可选启用 AI shadow audit：AI 只审计证据一致性和数据缺口，不改写确定性路线、不下单、不改仓位；默认优先尝试本机 Codex，失败后可走 OpenAI-compatible 或 Anthropic fallback endpoint。
- `macro_risk_governor`：面向 TQQQ 的确定性宏观降杠杆插件。它按价格趋势、实现波动、VIX 和信用 ETF 相对压力打分，输出 `leverage_scalar` / `risk_asset_scalar` 给显式 opt-in 的策略运行时消费。HY OAS、金融压力指数、五角大楼比萨指数、Fear & Greed、put/call、VVIX、SKEW、MOVE、收益率曲线、美元压力、safe-haven demand 等外部硬数据、OSINT、情绪或跨资产字段默认只作为 watch-only 证据，不进入可执行分数；只有显式研究开关开启后才允许外部压力字段参与自动分数。
- `market_regime_control`：统一确定性 facade，汇总 crisis、macro 和 TACO 信号，输出版本化的 `notification` 和 `position_control`。只有经过回测证明自动消费有效的策略才挂载仓位控制；SOXL/SOXX 这类未通过统一宏观插件复核的高波动行业杠杆策略只接收通用通知，人工决定是否干预。股票/ETF 轮动策略通过本地风险缩放策略消费；TACO 在统一插件里保持通知-only，并会被危机和宏观降风险路线 veto。设计说明见 [Market Regime Control 统一插件方案](docs/market-regime-control-plan.zh-CN.md)。
- `taco_rebound_shadow`：仅适用于 TQQQ 的事件反弹上下文通知插件。它只写入人工复核 artifact，不给仓位大小建议，也不改动配置或账户分配。缓和/降温事件会先保持 watch-only，只有事件后价格反弹确认通过后才触发人工复核通知，以减少过早抄底提醒。
  该插件也可选启用同样的 shadow-only AI audit，但 AI 只复核事件来源和反弹证据质量。
- TACO panic-rebound 研究、组合回测和 overlay 对比也归属本仓库；snapshot pipeline 仓库只保留兼容入口。

## 使用方式

运行插件 TOML 配置：

```bash
qsp-run-strategy-plugins --config docs/examples/strategy_plugins.example.toml
```

从本地价格历史 CSV 直接生成 crisis response artifact：

```bash
qsp-build-crisis-response-shadow-signal \
  --prices data/input/price_history.csv \
  --as-of 2026-05-22 \
  --ai-audit-enabled \
  --output-dir data/output/tqqq_growth_income/plugins/crisis_response_shadow
```

生成宏观和统一市场状态插件使用的公开硬数据 `external_context` CSV：

```bash
qsp-build-macro-external-context \
  --start 1999-01-01 \
  --output data/output/market_regime_control/input/external_context.csv
```

构建器会尽量下载公开 FRED/CBOE 字段：VIX、VIX3M、VVIX、SKEW、Cboe
put/call、HY/IG OAS、金融压力指数、收益率曲线、贸易加权美元压力和
TED/funding stress。CNN Fear & Greed、AAII、NAAIM、五角大楼比萨指数、
MOVE、市场宽度等没有稳定免登录历史源的字段，可以通过 `--manual-context`
提供。OAS 覆盖范围以 FRED 公开 graph endpoint 实际返回为准；如果需要更早的
本地归档 OAS 历史，也通过同一个 manual context 注入。

AI audit 使用环境变量读取 API 配置：

- `QSP_STRATEGY_PLUGIN_AI_AUDIT_CODEX_ENABLED`，默认 `true`
- `QSP_STRATEGY_PLUGIN_AI_AUDIT_CODEX_MODEL`，本机 Codex provider 的可选标签
- `QSP_STRATEGY_PLUGIN_AI_AUDIT_API_KEY`，或 fallback 到 `QSP_CRISIS_AI_AUDIT_API_KEY` / `OPENAI_API_KEY`
- `QSP_STRATEGY_PLUGIN_AI_AUDIT_BASE_URL`，或 fallback 到 `QSP_CRISIS_AI_AUDIT_BASE_URL` / `OPENAI_API_BASE_URL` / `OPENAI_BASE_URL`
- `QSP_STRATEGY_PLUGIN_AI_AUDIT_MODEL`，或 fallback 到 `QSP_CRISIS_AI_AUDIT_MODEL` / `OPENAI_MODEL`
- `QSP_STRATEGY_PLUGIN_AI_AUDIT_FALLBACK_API_KEY` / `QSP_STRATEGY_PLUGIN_AI_AUDIT_FALLBACK_BASE_URL` / `QSP_STRATEGY_PLUGIN_AI_AUDIT_FALLBACK_MODEL`
- `QSP_STRATEGY_PLUGIN_AI_AUDIT_ANTHROPIC_API_KEY`，或 fallback 到 `QSP_CRISIS_AI_AUDIT_ANTHROPIC_API_KEY` / `ANTHROPIC_API_KEY`
- `QSP_STRATEGY_PLUGIN_AI_AUDIT_ANTHROPIC_MODEL` / `QSP_STRATEGY_PLUGIN_AI_AUDIT_ANTHROPIC_BASE_URL` / `QSP_STRATEGY_PLUGIN_AI_AUDIT_ANTHROPIC_VERSION`

如果运行环境已经统一注入 `ANTHROPIC_API_KEY`，不需要为策略插件重新申请 key；只有当希望把策略插件和其他 audit 服务隔离时，才使用 `QSP_STRATEGY_PLUGIN_AI_AUDIT_ANTHROPIC_API_KEY` 覆盖。

从本地价格历史 CSV 直接生成 TACO 反弹通知 artifact：

```bash
qsp-build-taco-rebound-shadow-signal \
  --prices data/input/price_history.csv \
  --event-set geopolitical-deescalation \
  --as-of 2026-05-22 \
  --ai-audit-enabled \
  --output-dir data/output/tqqq_growth_income/plugins/taco_rebound_shadow
```

输出包括 `latest_signal.json`、按日期归档的 JSON、按日期归档的 CSV，以及 evidence CSV。平台运行时通过 `*_STRATEGY_PLUGIN_MOUNTS_JSON` 挂载的就是 `latest_signal.json`。

## 通知和日志 i18n

通过 strategy plugin runner 生成的 artifact 会附带展示层 i18n 字段：

- `localized_messages.schema_version = strategy_plugin_messages.v1`
- `localized_messages.notification.en-US` / `localized_messages.notification.zh-CN`
- `localized_messages.log.en-US` / `localized_messages.log.zh-CN`
- `log_record.schema_version = strategy_plugin_log.v1`
- `market_regime_control.notification.localized_message_schema_version`

策略和券商运行时的交易逻辑仍应只读取 `schema_version`、`canonical_route`、
`suggested_action`、`reason_codes` 和 `position_control` 等机器字段。中英文文案只用于通知界面和日志展示，不参与策略判断。`market_regime_control.notification`
会同步包含本地化通知文案和原因标签，方便现有通知代码直接渲染，不需要在策略仓库里重复翻译 route/action code。

## 本地检查

```bash
python -m pip install -e '.[test]'
python -m pytest -q
ruff check .
```

## 许可证

MIT License. Copyright (c) 2026 QuantStrategyLab.
