# 插件生命周期策略

[English](./plugin_lifecycle_policy.md)

本文定义策略插件的生命周期阶梯和门槛模型。

## 设计目标

插件应该容易观察、难以误用，而且在没有显式批准前非常难影响资金。

- AI 可以监控和总结插件证据。
- AI 不能单独把插件升级成 live 权限。
- 通知投递不等于仓位控制权限。
- 兼容挂载可以保留用于历史回放，但不能意外扩大 live 权限。

## 推荐插件阶段

| 阶段 | 含义 | 资金影响 |
| --- | --- | --- |
| `research_only` | 研究 artifact，不打算进入平台 runtime | 无 |
| `notification_only` | 可以通知人工，但不能控制仓位 | 无 |
| `shadow_observer` | 可以挂到 runtime metadata 和审计轨迹 | 无 |
| `automation_candidate` | 证据足够，进入自动化候选 | 受门槛控制 |
| `automation_approved` | 当平台门槛也通过时，策略侧可自动消费 | 有 |
| `deprecated_compatibility` | 仅用于回放或迁移兼容 | 无 |

## 三道门槛

任何由插件驱动的资金影响，都必须同时通过三道门槛：

1. **插件 schema 门槛**
   - artifact 必须匹配支持的 schema version，并在共享契约中保持 `shadow` 模式。
2. **插件证据门槛**
   - 插件必须标记为 `automation_approved`，且 `position_control_allowed = true`。
3. **策略 / 平台门槛**
   - 消费策略必须显式 opt-in，并且仍然被平台 catalog 允许。

任意一项失败，插件就应该停留在 notification-only 或兼容模式。

## 当前策略形态

- `src/quant_strategy_plugins/plugin_policies.py` 是 lifecycle、消费权限、
  notification target、schema version 和 deprecated successor 的机器可读来源。
- `market_regime_control` 是统一默认 runtime 插件。
- `crisis_response_shadow`、`macro_risk_governor` 和 `taco_rebound_shadow`
  仍然是兼容挂载或 notification-only sidecar。
- `panic_reversal_shadow` 仍然偏研究，应继续保持 notification-only，
  除非后续单独晋级。

## 推荐运行规则

- `notification_allowed` 可以保持宽松，方便研究可见。
- `position_control_allowed` 必须保持窄而明确。
- 尽量使用统一的 policy registry，不要把 allowlist 分散到多个 runner。
- 当策略消费插件并产生 live 资金影响时，平台通知路径应与策略执行路径分离。

## 实际解释

- 只给人工复核看的 artifact，用 `notification_only`。
- 仍然只是 sidecar 证据层的 artifact，用 `shadow_observer`。
- 正在准备自动化的插件，用 `automation_candidate`，直到策略门槛也通过。
- 不再是新默认路径的插件，用 `deprecated_compatibility`，并避免出现在新的 runtime 默认值里。
