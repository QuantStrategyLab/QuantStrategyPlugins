# 同维风险约束组合候选

状态：`DESIGN_ONLY_NOT_RUNTIME`。设计日期：2026-10-04 UTC。候选政策 ID：`market_regime_composition.same_dimension_min.v1`。新候选必须采用下述 UES 强 no-add/release 合同。本文冻结拟议语义和验收要求，不是现行仲裁器的新版本，也不授予策略消费、仓位、通知或执行权限。

建议将所有**适用于同一范围、同一风险度量的硬上限取交集**；同维标量上限取最小值。不同维度分别保留，不把相关风险事实机械连乘。源事实仍由 QSP 提供；事实到限制、baseline、恢复意图和最终目标归属策略候选；账户与订单仍由中央 Risk Gate 检查。

## 当前架构与设计压力

固定读取身份为 QSP `fdc7555d3eb4dd931fd1e4fbbb1795dfba2e33cd`；UES research extra 所 pin 的 QSP `3416da47580be1537183e378f3ca9efacc6f9b8c` 的选定仲裁源码字节相同。当前 `market_regime_arbiter.v1` 是优先级选路：同一时点 benchmark guard 的 `.5` 与 macro 的 `.1` 同时出现时，选择 benchmark 的 `.5`。这是已确认的现行语义，**尚未证明违反获批政策，不能直接叫生产 bug**。[固定仲裁源码](https://github.com/QuantStrategyLab/QuantStrategyPlugins/blob/fdc7555d3eb4dd931fd1e4fbbb1795dfba2e33cd/src/quant_strategy_plugins/market_regime_control_plugin.py#L434-L541)

UES `cc05a78da902c3762a5766291213580cb458e698` 的 dual-drive core 先处理杠杆腿及转移，再缩放全部风险资产；两个维度不能合并成一个折扣。普通 QSP runner 保持 notification-only 权限，本设计不改变它，也不证明现有插件已进入实盘目标。[core](https://github.com/QuantStrategyLab/UsEquityStrategies/blob/cc05a78da902c3762a5766291213580cb458e698/src/us_equity_strategies/strategies/tqqq_dual_drive_core.py#L85-L152)、[runner](https://github.com/QuantStrategyLab/QuantStrategyPlugins/blob/fdc7555d3eb4dd931fd1e4fbbb1795dfba2e33cd/src/quant_strategy_plugins/strategy_plugin_runner.py#L1360-L1394)

## 候选身份与时间合同

这些字段是未来策略候选内部记录要求，**不新增到现有 V2 envelope 的顶层，不绕过其 forbidden-field 校验**。现有 `qsl.strategy-plugin-signal.v2` 仍只含确定性事实，拒绝 AI、目标、授权、资本和旧 `position_control` 树；策略侧的 policy interpretation 与源 envelope 分开存储。[V2 边界](https://github.com/QuantStrategyLab/QuantStrategyPlugins/blob/fdc7555d3eb4dd931fd1e4fbbb1795dfba2e33cd/src/quant_strategy_plugins/plugin_signal_envelope_v2.py#L65-L99)

每个组合决策至少绑定：

- `policy_id`、`policy_version`、政策内容 hash、策略 candidate/revision/config hash；未知版本拒绝，不沿用默认政策
- 每个源的 envelope schema、producer repo/full revision/code/config hash、P1 manifest/root hash、payload hash；这些是**输入版本**，不是运行时安装证明
- `factor_id`、确定性算法版本、市场/标的/窗口/采样口径，以及具体输入 observation ID；同一因子的历史修订产生新 observation ID，不覆盖旧决策
- `requested_as_of` 是请求截止点；每个输入独立的 `observed_as_of` 是真实最后有效观测点，另记 `published_at`、`received_at` 和 `decision_at`。只读当时已经发布且收到的版本，不以矩阵最新日期或报告生成时间替代输入时间
- `validity_policy_version`、`effective_from`、`valid_until`、交易日历/时区及最大延迟；决策必须处于全部必需输入的有效时间交集。`date_cutoff` 和 artifact retention 均不是交易 TTL
- 约束的 `constraint_id`、维度、单位、适用范围、上限、硬/软类别、关联 observation IDs 和原因码；所有政策映射及失效规则也纳入 policy hash
- 输出 canonical digest 绑定规范排序、精确去重后的完整来源集合、选用/未选用原因和状态；固定身份下重复输入幂等。原始接收次数另记日志，不改变语义 digest。执行前若市场、账户或挂单快照改变，归属 consumer 按其合同重验

不同源可以有不同观测时间，不能强行把它们标成同一 `as_of`；只要各自满足已冻结有效期并已在决策时可见，才可联合解释。修订数据不能回填为过去已知输入。

## 组合语义

先按冻结 policy 判断适用范围和输入可用性，再由策略侧映射为约束。watch-only 事实不因加入集合而升级为硬约束；不适用的输入记为 `NOT_APPLICABLE`，它的缺失不构成全市场紧急事件。

对于同一 scope 和相同 measurement definition，保留每一个有效硬约束 `C_i`，可行集为 `baseline_allowed ∩ C_1 ∩ ... ∩ C_n ∩ account_gate`。只有可比较、同分母的 `[0,1]` 标量上限才可写成 `cap_d = min(1, cap_1d, ..., cap_nd)`。绝对金额上限先按冻结 baseline/估值转成同单位；不同 scope、净/总风险、quantity/nominal/effective exposure 不得直接取最小或互相替代。

本候选先只命名现有 research 口径的两个维度：

1. `leverage_leg_nominal`：杠杆资产腿名义目标限制，对应旧 `leverage_scalar` 的策略解释；它不是账户总杠杆或 ETF 内部有效杠杆
2. `total_risk_asset_nominal`：杠杆腿与非杠杆风险资产腿合计限制，对应旧 `risk_asset_scalar`；旧 `risk_budget_scalar` 在此只是同一量的 alias，**不可再乘一次**

每个维度分别取最小：benchmark 的 `(L=.5, R=.5)` 与 macro 的 `(L=.1, R=.1)` 得到 `(L=.1, R=.1)`，不是 `.05`，也不是因 benchmark 优先而丢弃 macro 上限。结果记录所有绑定约束及非绑定约束；显示用 route/source 排序不得改变可行集。等值上限并列记录，不能随机选一个来源。

**保留独立腿约束。** 沿用现有 core 的研究适配口径时，先限制杠杆腿、按既有策略规则转移，再对全部风险资产应用 R；不得为了“去重”删除 L 或 R。baseline 两腿各 450，L=R=.5 时，杠杆腿 112.5、非杠杆腿 337.5、总风险资产 450：杠杆腿为 baseline 的 `.25`，总风险资产为 `.5`。这是跨维度作用，不是总风险资产盲目打两次 `.5`。若未来改用真实有效杠杆/因子预算，必须新 measurement/policy 版本，不得静默重解释这些字段。

单个非杠杆腿可以因既有转移规则而增加；这不自动满足“每腿跨周期只减不增”。若冻结 no-add 合同限制每腿，额外腿上限也进入交集；转移不满足时保留剩余现金，不归一化回满仓。任何同维 cap 都不能撤销别的腿、集中度、现金或挂单约束。

## 因子来源与原因去重

- `factor_id` 标识实际观测及算法；`reason_group_id` 可以说明共同市场压力。VIX、实现波动、回撤与牛熊估计不是同一事实，也不是已证明独立的风险乘子
- 精确重复按 `constraint_id + scope + dimension + observation_id + policy_version` 幂等处理，保留所有来源引用；同一 observation 在两个维度的约束必须分别留下
- 同因子不同政策产生的不同有效硬上限仍取交集；原因文案可以合并，不能因文案去重而丢掉更严限制。相互矛盾的同身份内容作为完整性错误，不采用最后写入者
- 相关但不完全重复的事实可分别触发独立上限；默认不连乘。需要联合评分或条件折扣的模型只能以独立版本候选定义，并接受消融，不能由相关性标签或 AI 临时改权重

## UNKNOWN 过期与机会冲突

缺失、过期、发布晚于决策、窗口不足、标的/日历错位或 hash 不一致不能变成 `no_action`、低风险或 scalar=1。必需依赖失效时输出 `UNKNOWN/BLOCKED` 和阻止新增风险的原因；保留其余仍有效硬约束。若合同允许短期保留上一有效限制，必须冻结保留 TTL、来源及失效边界；不得无限期沿用，也不得在到期后自动解除已有受限 episode。

`UNKNOWN` 表示不能证明当前可用性，**不自动表示清仓**。新增风险冻结；风险减少必须仍有可信账户、position、open/in-flight order 状态并经过 Risk Gate。无法核对账户/订单时先 reconcile，不能把缺失输入映射成不受检查的 sell-all。新鲜 permissive 观察也不能补发旧信号的买入。

crisis、硬上限和必需数据门优先约束机会侧。TACO/panic reversal/price rebound 可留下人工 narrative 和被 veto 记录，但不得放宽 cap、解除 UNKNOWN、删除腿限制或触发恢复权限。一个机会估计即使同日且置信度高，也不是 baseline、新 entry intent 或人的批准。

## Baseline 与跨周期 release 的责任

弱合同是每次最终风险目标不超过当次无插件 baseline；它允许昨天 `.5`、今天 `1` 时恢复仓位。强合同还禁止**仅解除限制**导致跨周期新增风险。**本新候选要求强合同**，现行 runtime 的弱语义保持不变；标量 clamp 不能代替它所需的状态与 intent 链。

强 no-add 的独立设计依赖为 `UsEquityStrategies/docs/strategy_risk_stateful_controls.md#tqqq-plugin-release-candidate-contract-draft-v1-2026-10-04`，候选名为 `tqqq_qqq_guard_cash_release_intent_research_v1`。这是同期未发布的设计依赖，不能用旧版本文件当作新规范已实施的证据。其 frozen baseline/intent identity、risk episode、前驱 transition、release event、风险度量及幂等 replay 必须与本组合 policy/input digest 一起绑定。

该 UES draft v1 限于 long TQQQ 加剩余现金：同维 cap 形成提案后，在 effective-session 的 quantity seam、任何正目标差前应用经验证 split-adjusted 的 retained quantity ceiling。仅恢复限制不提高 ceiling，价格/NAV 漂移不授予额外股数；必须由策略发出完整 alpha 条件 false-to-true 的新 alpha-epoch、精确 identity/version/digest/expiry 匹配的 intent 才能讨论释放。风险清仓造成的空仓或 core 的 `entry` 标签不是新 alpha epoch。原两腿例子只说明 legacy 维度，**不能把这个窄 release 合同扩展成多腿、空头、期权或 hedge 的证明**。

重复旧 intent、机会通知、AI agree、文案或报告时间更新均不能形成 release event；本 draft 没有泛化的人工 override 或 approved-refresh bypass。组合输入变宽只移除一个 veto，不能生成 baseline 或买入意图。缺少真实 TQQQ intent issuer、明确 initialization/migration receipt、完整前驱 state 链及 missing-chain/crash 生命周期时，本候选**不可采用**。已有 QPK append-only/idempotent state seam 不补齐这些缺口；这不是扩大权限的理由。

本文件不实现 release store，不把插件 output 转成权限，不修改 QPK/UES API、默认/live 配置、依赖 pin 或 P1–P3/P4–P6 promotion。当前账户/订单约束仍是独立最后检查；源 envelope 有效不等于获批策略 consumer 有效。[现行 UES 权限检查](https://github.com/QuantStrategyLab/UsEquityStrategies/blob/cc05a78da902c3762a5766291213580cb458e698/src/us_equity_strategies/market_regime_control_contract.py#L23-L44)

## 三个有界合成验收规格

以下是待实现测试规格，**本文件未运行新测试或收益优化**。只使用固定 JSON/日期和代数，不读取 provider、运行 AI、回测历史、搜索阈值或连接 broker。旧策略只作 characterization，新政策必须另有入口，不能覆盖旧断言。

1. **同维优先级与交集对照**：fresh benchmark `(L=.5,R=.5)`、fresh macro `(L=.1,R=.1)`，相同 scope/分母/决策时点。旧输出 source=benchmark、`.5/.5`；候选 `.1/.1`，两维都绑定 macro，仍记录 benchmark。反转输入顺序和重复同身份记录不改变候选 digest/结果。断言不是 `.05`，旧默认输出不变
2. **同源去重与独立维度**：同一个 guard observation 同时给 L=R=.5，并重复同身份约束；baseline 两腿各450，使用上述冻结 legacy adapter。旧与候选 cap 都是 `.5/.5`；候选保留两个维度，代数结果仍为112.5/337.5、总风险450。原因去重不能删 R、删 L、变成总风险225或新增第三个 risk_budget 折扣。这是目标代数检查，不是持仓或实际买入证明
3. **新旧日期与机会冲突**：fresh benchmark `.5/.5`、已过 valid_until 的必需 macro `.1/.1`、同日 opportunity；前一已接受 transition 为受限 episode，且无新策略 intent/release event。旧 arbiter 不在此函数逐源验时，仍优先 benchmark `.5/.5`；候选为 UNKNOWN/BLOCKED，机会不可放宽，过去限制不得因 stale 消失而自动恢复。记录当前有效 `.5` 只作已验约束，不当作 executable full budget；strict consumer 增加风险许可为 false，账户不可信时不提交任何假设减仓

正式安全测试另需覆盖 policy/input 版本错配、同身份矛盾、多个 scope、不同单位、crisis cap=0、非交换转移顺序、并发/部分成交/挂单、重复 release 与 AI 文案变更；这些要求不冒充本轮额外合成结果。

## OOS 消融与准入要求

在改变 consumer 前冻结至多三个对照：现行 priority 基准、仅同维交集的消融 comparator、同维交集加明确因子去重及 UES 强 release 合同的新候选。第二项只用于隔离组合变化，不满足本新候选的采用要求。冻结 source/strategy/policy/config/input/有效时间版本和各 trial；不能只把三份局部 JSON 对照当经济效果验收。

每个候选必须与同一 core-only baseline 成对比较，再逐项删除 benchmark、macro/volatility 及组合组件；保持 universe、baseline sizing、成本/滑点、自融资现金和执行假设一致。按时间分开开发、walk-forward、未触碰 OOS 和前瞻 shadow；阈值在对应 OOS 前冻结，不反复用同一 holdout 选政策。源修订按当时可见版本 replay。

报告净收益、最大回撤、尾部损失、nominal/effective exposure、现金、换手/成本、veto 数、错过反弹和恢复重入；同时单独验安全不变量，尤其 strict 合同的零未经授权风险增加、硬 cap 不可绕过、目标与 cash residual 不被归一化。真实 ETF 与合成代理分档。预先定义风险目标及可接受成本/收益损失；未满足 OOS 或操作故障验收就不推广。本文没有经济表现结论。

## 参考边界与最小落地

外部资料沿用 2026-10-04 已直接阅读并保留的 primary-source notes，不引入新 provider 或框架依赖：

- LEAN 的 [Framework Overview](https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/overview) 支持 alpha→目标→风险→执行分层；[Risk Management](https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/risk-management/key-concepts) 的多模型是顺序消费，并不自动证明本候选的交集或严格 no-add。其 [Alpha 生命周期](https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/alpha/key-concepts) 警告旧 Insight 可导致风控清仓后重入
- Nautilus [Execution](https://nautilustrader.io/docs/latest/concepts/execution/) 支持订单级检查、REDUCING 合格 reduce-only 与 HALTED 的区别；这些状态不是自动清仓，也不替本系统证明已执行对应控制
- Cboe [Volatility Trading](https://www.cboe.com/tradable-products/volatility-trading) 将 VIX 定义为 SPX 期权隐含的30日期望波动且非方向预测；跨市场适用性和风险折扣仍须本候选验证，不拿 VIX 下降作恢复批准

最小集成只新增本设计文档；可在已有 market-regime plan 增加“未生效组合候选”的链接，但不修改旧优先级说明为已生效 min-policy。未来实现先做独立 pure research composition helper/测试及 UES candidate adapter，经独立 review 后再决定接线。本文件不推荐迁移 LEAN/Nautilus、重建统一引擎、增加市场指标或删除现有腿约束。

AI 仅为人的来源可追溯 narrative。AI 输出、失败、延迟、agree/confidence/摘要变更必须不改变确定性事实、policy 状态、目标 digest 或授权；人的实际决定另有明确 decision record。AI 不能放宽风险、选择更宽 cap、解决权限冲突或批准恢复。
