# Market Regime Control 统一插件方案

[English](./market-regime-control-plan.md)

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
  负责宏观降杠杆。它看价格趋势、实现波动、VIX 和信用 ETF 相对压力，输出 `risk_reduced` 或 `risk_off`。HY OAS、金融压力指数、Fear & Greed、put/call、safe-haven demand、VVIX、SKEW、MOVE、收益率曲线、美元压力、市场宽度、AAII/NAAIM 和五角大楼比萨指数默认只作为 watch-only 证据，先用于通知和回测观察；只有显式研究开关 `external_stress_actionable` 开启后，外部压力字段才允许进入可执行分数。
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
- `localized_messages` / `log_record`
  提供 `en-US` 和 `zh-CN` 通知、日志文案。交易逻辑继续只读 route/action/reason code 和仓位控制字段，本地化文案只用于展示和审计日志。

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

当前观察指标分层：

- 已可执行打分：价格趋势、63/252 日回撤、实现波动、VIX 水平/尖峰、信用 ETF 相对压力。
- 已接入 watch-only：HY OAS、金融压力指数、五角大楼比萨指数、Fear & Greed、put/call、safe-haven demand、VIX/VIX3M 期限结构、VVIX、SKEW、MOVE、IG OAS、资金压力利差、10Y-2Y/10Y-3M 曲线、DXY 21 日压力、50/200 日市场宽度、新高新低、涨跌线回撤、AAII bearish-bullish spread、NAAIM exposure。
- 未进入自动仓位：所有 watch-only 指标。它们只用于通知、证据归档和后续历史回测。
- 研究开关：`external_stress_actionable = true` 可让 HY OAS、HY OAS 63 日扩张和金融压力指数进入可执行分数；默认固定为 `false`。

公开历史数据构建：

- `qsp-build-macro-external-context` 生成统一 `external_context.csv`，供 `macro_risk_governor` 和 `market_regime_control` 使用。
- 自动下载 FRED/CBOE 可稳定复现的硬数据：VIX、VIX3M、VVIX、SKEW、Cboe put/call、HY/IG OAS、STLFSI/NFCI/ANFCI、10Y-2Y、10Y-3M、贸易加权美元指数和 TED/funding stress。
- CNN Fear & Greed、AAII、NAAIM、五角大楼比萨指数、MOVE、市场宽度等没有稳定免登录历史 CSV 的字段，不在构建器里伪造；需要通过 `--manual-context` 注入，仍默认 watch-only。
- ICE BofA OAS 取决于 FRED 公开 graph endpoint 的可返回历史长度；如果 FRED 只返回近年滚动窗口，长周期信用压力仍以 HYG/IEF、LQD/IEF 等 ETF 相对压力为主，历史 OAS 可用 `--manual-context` 注入。

## 版本管理

当前对外契约是：

- 统一插件 schema：`market_regime_control.v1`
- 仲裁器 schema：`market_regime_arbiter.v1`
- 运行器总 schema：`strategy_plugins.v1`
- 通知文案 schema：`strategy_plugin_messages.v1`
- 日志记录 schema：`strategy_plugin_log.v1`
- 策略消费权限 schema：随 `strategy_plugins.v1` 通过 `consumption_policy` 输出

升级原则：

- 向后兼容字段可以在 v1 内新增。
- 删除字段、改变字段语义或改变默认执行权限，需要升级到 v2。
- 策略仓库应按 `schema_version` 校验可消费版本，并在配置层保留 opt-in/opt-out。
- 通知和日志 i18n 是展示层契约；策略不能把本地化字符串作为交易判断依据，必须继续消费机器可读 code。
- 旧插件标记 deprecated successor 为 `market_regime_control`，但保留历史入口方便复现旧回测。

## 回测结论

真实产品短中周期和长周期合成代理都支持当前设计。

TQQQ 2010-2026 真实产品窗口：

- `cash_vol30_5_7_vol_confirmed` 方案相对基线 CAGR 提升约 `+1.03pp`。
- 最大回撤改善约 `+0.29pp`。
- COVID 窗口 CAGR 改善约 `+11.47pp`，最大回撤改善约 `+4.15pp`。

公开外部上下文补充回测（2010-02-12 到 2026-04-16）：

- 核心宏观信号不加外部上下文：CAGR `24.74% -> 25.77%`，最大回撤 `-35.07% -> -34.77%`，最终权益约 `+14.23%`。
- 外部字段仅 watch-only：CAGR、回撤和最终权益与核心宏观信号完全一致；watch 天数从 `343` 增至 `558`，证明新增跨资产/情绪字段只增加通知，不影响自动仓位。
- 外部硬数据直接参与可执行分数：CAGR `24.99%`，最大回撤 `-34.72%`，最终权益仅较基线 `+3.33%`；比核心宏观信号保守，收益/回撤组合较差。
- 结论：新增外部指标默认应保持 watch-only；只有价格/VIX/信用 ETF 等核心信号继续参与自动仓位。STLFSI/HY OAS 等硬数据可保留为研究开关，不宜默认提升自动降仓权限。

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
