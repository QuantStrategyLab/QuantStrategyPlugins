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
| `automation_approved` | 为历史回放保留的旧证据标签，不代表直接仓位权限 | 无 |
| `deprecated_compatibility` | 仅用于回放或迁移兼容 | 无 |

## V2 权限规则

插件 artifact 永远不携带直接资金权限。它只能向归属策略候选提供信号、观察或
受限风险建议；策略必须通过自己的生命周期验证，并把仓位目标提交中央 Risk Gate。

旧 v1 的 `position_control_allowed` 和 `automation_approved` 字段继续可读，
方便历史 artifact 回放；但 runner 统一输出为 notification/shadow-only，不能
借这些字段修改仓位。

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
- `position_control_allowed` 固定为 `false`；策略侧适配器只通过中央 Risk Gate
  消费已经验证的信号。
- 尽量使用统一的 policy registry，不要把 allowlist 分散到多个 runner。
- 当策略消费插件并产生 live 资金影响时，平台通知路径应与策略执行路径分离。

## 实际解释

- 只给人工复核看的 artifact，用 `notification_only`。
- 仍然只是 sidecar 证据层的 artifact，用 `shadow_observer`。
- 如果准备自动消费某个插件行为，应晋级新的归属策略候选，而不是给插件仓位权限。
- 不再是新默认路径的插件，用 `deprecated_compatibility`，并避免出现在新的 runtime 默认值里。
