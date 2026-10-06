# 十年利率背景观察研究

状态：`UNVALIDATED_RESEARCH`。本期只有一个来源无关、标准库纯观察函数。不是下载器、已启用插件、策略政策或生产采用。既有模块、包级导出、runner/catalog、外部背景宽表CSV、默认配置、依赖和runtime pin保持原样。

[Full English contract](rates-context-observer-research.md)

## 用途与边界

`quant_strategy_plugins.rates_context_observer_research.build_rates_context_observation(snapshot, config)` 描述十年名义收益率、真实收益率、独立公布的breakeven，以及明确标为近似的名义减真实收益率差。只输出事实及数据可用性诊断，没有信号、投票、方向/风险分类、仓位、预算、订单、通知、文件、时钟、模型或provider调用。

原宽表CSV合并会将各列转成数值，不能保存本合同的来源、修订和发布时间。不能把新记录塞进该合并后声称来源证据仍完整。本模块不扩充 `DEFAULT_FRED_SERIES`，不修改macro的watch/actionable评分。

## 输入与配置

输入恰有 `schema_version=qsl.rates-context-input.research.v1`、`decision_at`、`series`。`decision_at` 是调用方声明的实际评估/接收决策时点，须有明确ISO时区。`series` 仅允许可缺省的 `nominal_10y`、`real_10y`、`breakeven_10y` 三个角色；缺少角色明确unknown。三者必须是真正十年期测量，不能把ETF价格或其他期限重标为十年。

每个序列恰有：

- `source_id`：实际来源集合身份，名义/真实配对须一致
- `series_id`：实际测量序列身份，不能只用共同显示名
- `basis`：名义/真实仅接受 `treasury_par_yield` 或 `treasury_constant_maturity_yield`；独立breakeven仅接受 `reported_breakeven`
- `unit`：准确为 `percent`，适用时为每年百分点口径；4.2表示4.2%，不是0.042
- `rows`：调用方冻结的观察记录，按观察日严格递增

相同 `source_id + series_id` 不能占两个角色；包括breakeven复用收益率序列。这类复用使两个角色均unknown，理由为 `ROLE_SOURCE_IDENTITY_AMBIGUOUS`。改角色名不能让同一观察变成独立证据。

每行恰有 `observation_date`、`value`、`available_at`、`received_at`、`revision_id`：

- 观察日为准确 `YYYY-MM-DD` 来源标签；不从日期拼接固定时钟
- 数值须有限、非布尔；负收益率合法
- `available_at` 是调用方有证据支持的该修订实际首次可得时点，不是导入时间或预定发布时间
- `received_at` 是该修订到达调用方的时间；两者须有明确时区并归一UTC
- 缺失/非法时间保持unknown；接收时间不能早于可得时间
- `revision_id` 标识所选冻结修订，拒绝 `latest`。同日两个已可见修订属于歧义，不能静默取最后一行

配置恰有 `schema_version=qsl.rates-context-config.research.v1`、`window_start`、`window_end`、`max_observation_age_days`，全部必填。起日须早于止日。最大年龄是最新可见观察日距决策时点的非负UTC日历日数；只是显式研究容忍度，不是校准后的新鲜度建议。

## 共同端点、单位及unknown

各序列须在同一组准确起止日都有观察。模块不选邻近日、不前填、不插值，也不为迁就来源而改变窗口。端点差不证明全部交易日覆盖；缺少起点或终点为 `WINDOW_ENDPOINT_UNAVAILABLE`。

`change_bp = 100 × (end_percent − start_percent)`，表示收益率变化的基点，非价格收益或相对百分比变化。例如合成4.0%至4.2%为+20bp；该例为 `SYNTHETIC_FIXTURE_ONLY`，不是下载数据。

历史决策投影中，窗口外日期、decision_at以后公布或收到的行，在读取数值/修订前即不可见。隐藏的迟到修订和未来值不能改变历史观察。不能解析的选择器无法证明属于未来，产生unknown。可见投影中重复/倒序日期、非有限值、缺metadata、未知口径、错误单位、过时或端点不足，均unknown且不给数值变化。非法配置抛出不回显输入的 `ContractError`。

各序列独立保存source/series/basis、端点观察/修订/可得/接收metadata、最新观察日、可见数量、观察年龄、日期级可得延迟和接收延迟。可得延迟只是UTC日期标签差，不是经核证的市场收盘至发布时间差。今天导入不能让旧观察变新鲜。一个序列缺失不抹掉另一个序列的合格声明事实；完整组合或配对不可得时，总质量仍unknown。

## 近似差值与独立breakeven分开

只有名义/真实使用同一声明来源集合、测量口径、单位及准确端点，才计算 `approximate_yield_spread`，明确标为 `APPROXIMATE_NOMINAL_MINUS_REAL_YIELD_SPREAD`。不能自动当作官方公布的breakeven、纯通胀预期或第二个独立风险投票。

后续调用方自行负责的窄适配须区分：

- 直接Treasury名义par/真实par配对保留Treasury集合身份及 `treasury_par_yield`；相减仍是近似spread
- 已获准H.15/FRED DGS10/DFII10配对保留H.15/FRED身份及 `treasury_constant_maturity_yield`；不能只因均写十年，就与另采Treasury记录混配
- 独立取得的T10YIE保留其真实来源/修订/公布时间及 `reported_breakeven`，单独返回，绝不以名义减真实补值

H.15名义/通胀指数恒定期限序列是来源特定的收益率测量。[H.15定义](https://www.federalreserve.gov/releases/h15/)及[Treasury利率统计](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics)说明期限/方法。[DGS10](https://fred.stlouisfed.org/series/DGS10)、[DFII10](https://fred.stlouisfed.org/series/DFII10)、[T10YIE](https://fred.stlouisfed.org/series/T10YIE) metadata为percent/daily；T10YIE说明独立列明其派生关系，以及自2019-06-21直接使用Treasury数据。数值相同不证明发布时间或历史修订相同。

## 来源许可与历史证据

本期不新增真实数据采集、provider凭据、provider数据复制或观察值再发布。测试仅用有标签的合成数值。来源链接仅作metadata参考，不授予许可、不认证feed或provider真实性。

2026-10-06核查时，FRED将DGS10/DFII10标为 `Public Domain: Citation Requested`，T10YIE标为 `Copyrighted: Citation Required`。未来采集方须核适用来源权利、署名、服务/API条款及具体用途，包括[当前FRED条款](https://fred.stlouisfed.org/legal/)的限制。本模块不替其审核授权或宣称已获许可。数据公有领域标签不覆盖服务访问/用途条款。本期没有新增FRED采集器，也未扩充既有CSV读取机制。

所有输出始终是 `UNVALIDATED_RESEARCH`、`assurance=CALLER_DECLARATIONS_AND_CONSISTENCY_ONLY`、`historical_pit_verified=false`、`backtest_eligible=false`、`position_control_allowed=false`。`declared_available` 仅表示输入满足内部时间/一致性检查。时间声明、revision字符串不是经核证的采集证据；真实历史PIT仍须不可变来源快照、实际公布/接收证据、来源许可和独立producer/consumer核验。今天导入旧CSV不能伪造其历史available_at。

## 离线验证及后续

focused测试可用 `python -m unittest discover -s tests -p test_rates_context_observer_research.py`，运行环境必须在import测试前禁止网络/子进程/模型/通知入口。测试用文件spec加载纯模块，避开原包级可选依赖；正常包级import和全仓suite仍须单独验证。

合成覆盖percent→bp、独立breakeven、各源延迟、负利率、未来行/修订不变、缺公布/接收证据、今天导入旧数据、NaN/无穷/布尔/字符串、错误单位、混源/混口径、倒序/可见重复修订、错误/缺失端点、过时、非法配置、严格JSON、输入不变及无交易字段。

这只是准备步骤。未来获准采集/consumer接线须保留逐行证据，不能经过丢失metadata的宽表；另验真实来源覆盖/可得性、策略经济价值及获批消费。breadth历史membership/prices和NDX参与结构是独立缺口，本期没有实现breadth或NDX代理。纯函数或合成测试通过均不证明runtime采用。
