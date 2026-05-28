# Market Regime Control 统一插件方案

本文档记录 `market_regime_control` 的当前设计边界、信号优先级、策略消费方式和回测结论。

## 目标

`market_regime_control` 是统一的确定性市场状态 facade。它把原来的危机防守、宏观降杠杆和 TACO 事件反弹通知汇总成一个版本化 artifact，供策略仓库统一消费。

核心目标：

- 在宏观环境恶化、系统性危机或泡沫破裂风险上升时，主动降低仓位和杠杆。
- 保留 TACO 对假危机、事件缓和和反弹机会的通知能力，但不让它绕过危机防守。
- 不依赖 AI 做交易决策。AI 只允许做 shadow-only 证据复核和通知辅助。
- 输出稳定的 `market_regime_control.v1` schema，策略仓库按 schema 消费 `notification` 和 `position_control`。

非目标：

- 插件仓库不调用券商接口，不直接改账户分配。
- OSINT 字段，例如五角大楼比萨指数，只能作为 watch-only evidence，不能直接进入可执行分数。
- TACO 默认不增加仓位，不作为危机期间的抄底开关。

## 组件职责

`market_regime_control` 内部保留三个确定性组件：

- `crisis_response_shadow`
  负责硬危机防守。`true_crisis` 和泡沫脆弱性触发后，统一插件输出 `risk_off` / `defend`，仓位目标交给策略侧 opt-in 执行。
- `macro_risk_governor`
  负责宏观降杠杆。它看价格趋势、实现波动、VIX、信用相对压力和可选金融压力字段，输出 `risk_reduced` 或 `risk_off`。Fear & Greed、put/call、safe-haven demand 和五角大楼比萨指数只作为 watch-only 证据，先用于通知和回测观察。
- `taco_rebound_shadow`
  负责 TQQQ 事件反弹通知。它输出人工复核通知和本地 veto 线索，不直接提高仓位。

统一插件输出四组主要字段：

- `notification`
  通知是否应该发出、路由来源、原因码和 veto 说明。
- `position_control`
  策略侧可消费的 `risk_budget_scalar`、`leverage_scalar`、`risk_asset_scalar`、`taco_allowed` 和 `blocked_actions`。
- `component_signals`
  子组件的压缩证据，便于通知和审计。
- `execution_controls`
  明确插件仓库只写 artifact，不允许券商下单或账户配置变更。

## 仲裁优先级

当前优先级按风险优先设计：

1. `crisis_response_shadow` 的 `true_crisis` 或泡沫脆弱性优先级最高，输出 `risk_off`，并 veto TACO。
2. `macro_risk_governor` 的 `crisis` 其次，输出 `risk_off`，并 veto TACO。
3. `macro_risk_governor` 的 `delever` 输出 `risk_reduced`，降低杠杆或风险资产预算，并 veto TACO。
4. 数据质量 kill switch 或组件 blocked 状态会阻断机会侧动作。
5. 只有没有危机和宏观降风险时，TACO 才能输出 `opportunity_watch` 和人工复核通知。
6. watch-only 信号只通知，不给仓位权限。

这个顺序保证危机插件、宏观插件和 TACO 不冲突：防守优先，机会次之，通知和执行权限分离。

## 策略消费方式

策略仓库只挂载 `market_regime_control/latest_signal.json`，不再直接消费旧的三个插件。

建议消费规则：

- TQQQ 杠杆增长收益策略
  默认消费 `position_control`。`risk_off` 降到现金类或非风险资产；`risk_reduced` 按策略配置降低杠杆或风险预算；TACO 只触发人工复核和本地 veto。
- SOXL/SOXX 趋势收益策略
  不默认挂载统一插件，也不消费 `position_control`。SOXL 继续只使用已经通过复核的 SOXX 自身趋势和波动率降杠杆门；宏观、危机和 OSINT 信号只进入通用通知，由人工决定是否干预。
- Global ETF、Russell 1000、Tech/Communication、Mega Cap 类轮动策略
  默认支持统一插件。`risk_reduced` 建议做 50% 风险预算缩放，`risk_off` 建议归零风险资产预算。
- DCA 或收入型低频策略
  默认 notification-only，允许用户显式开启仓位影响。

旧插件仍可运行历史回测和兼容输出，但新策略集成应优先挂载 `market_regime_control`。

策略插件 runner 使用显式消费权限 registry，而不是只维护松散 allowlist：

- `notification_allowed`：允许生成和分发通知 artifact。
- `position_control_allowed`：允许策略 runtime 自动消费仓位控制字段。
- `evidence_status`：记录该策略/插件组合是 `automation_approved`、`notification_only` 还是 `deprecated_compatibility`。
- `since_version`：记录该消费权限从哪个 runner schema 开始生效。

SOXL/SOXX 不出现在 `market_regime_control` 的策略级消费 registry 中；它通过 `market_regime_notification` 接收通用通知，避免配置误用把通知信号升级成自动调仓。

## 版本管理

当前对外契约是：

- 统一插件 schema：`market_regime_control.v1`
- 仲裁器 schema：`market_regime_arbiter.v1`
- 运行器总 schema：`strategy_plugins.v1`
- 策略消费权限 schema：随 `strategy_plugins.v1` 通过 `consumption_policy` 输出

升级原则：

- 向后兼容字段可以在 v1 内新增。
- 删除字段、改变字段语义或改变默认执行权限，需要升级到 v2。
- 策略仓库应按 `schema_version` 校验可消费版本，并在配置层保留 opt-in/opt-out。
- 旧插件标记 deprecated successor 为 `market_regime_control`，但保留历史入口方便复现旧回测。

## 回测结论

真实产品短中周期和长周期合成代理都支持当前设计。

TQQQ 2010-2026 真实产品窗口：

- `cash_vol30_5_7_vol_confirmed` 方案相对基线 CAGR 提升约 `+1.03pp`。
- 最大回撤改善约 `+0.29pp`。
- COVID 窗口 CAGR 改善约 `+11.47pp`，最大回撤改善约 `+4.15pp`。

1999-2026 QQQ 合成 3x 长周期代理：

- 纯危机上下文版本：CAGR `14.78% -> 18.93%`，最大回撤 `-94.54% -> -87.63%`。
- 增强泡沫脆弱性版本：CAGR `14.78% -> 19.87%`，最大回撤 `-94.54% -> -86.60%`。
- 金融危机窗口：CAGR `-45.25% -> -27.65%`，最大回撤 `-59.87% -> -40.47%`。
- 互联网泡沫破裂窗口：增强泡沫脆弱性后 CAGR `-67.78% -> -51.69%`，最大回撤改善约 `+7.94pp`。

设计含义：

- 金融危机主要由 `true_crisis` 路线负责，适合硬降风险。
- 互联网泡沫不能只靠传统危机确认，需要保留泡沫脆弱性 route。
- TACO 对这些长周期危机不是防守组件，应继续作为机会通知和人工复核组件。

## 当前推荐默认值

- 杠杆策略：默认挂载统一插件，允许 `risk_off` 生效。
- 高波动行业杠杆策略：除非回测证明自动消费能提升收益/回撤组合，否则不默认挂载统一插件；SOXL 当前只接收通用通知。
- 轮动策略：默认开启 50% risk scaling 和 `risk_off` 归零。
- TACO：默认通知-only；只有没有危机和宏观降风险时才允许提示机会。
- AI audit：默认不参与交易权限，只能写审计结论和通知证据。
