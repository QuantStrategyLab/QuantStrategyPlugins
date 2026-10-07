# 十年利率背景观察研究

状态：`UNVALIDATED_RESEARCH`。保留原来源无关、标准库纯 v1 观察入口，并新增独立显式 v2 入口。不是下载器、已启用插件、策略政策或生产采用。既有模块、包级导出、runner/catalog、外部背景宽表CSV、默认配置、依赖和runtime pin保持原样。

[Full English contract](rates-context-observer-research.md)

## 用途与边界

`quant_strategy_plugins.rates_context_observer_research.build_rates_context_observation(snapshot, config)` 描述十年名义收益率、真实收益率、独立公布的breakeven，以及明确标为近似的名义减真实收益率差。只输出事实及数据可用性诊断，没有信号、投票、方向/风险分类、仓位、预算、订单、通知、文件、时钟、模型或provider调用。

原宽表CSV合并会将各列转成数值，不能保存本合同的来源、修订和发布时间。不能把新记录塞进该合并后声称来源证据仍完整。本模块不扩充 `DEFAULT_FRED_SERIES`，不修改macro的watch/actionable评分。

## 原 v1 输入与配置

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

## 显式 forward-known v2 入口

同模块新增独立纯入口 build_rates_context_observation_v2(snapshot, config)，
仅接收 qsl.rates-context-input.research.v2，返回
qsl.rates-context-observation.research.v2。原 v1 入口、常量、输入／输出语义
及拒绝行为保持不变。两个入口不自动升级对方输入；v2 不把 first_seen
填入 v1 的 available_at。

v2 根字段恰为 schema_version、availability_basis、collector_id、decision_at、
series。availability_basis 固定 collector_first_seen。collector_id 是 first_seen
所归属采集器的声明身份，须为无首尾空白、非空且不超过 256 字符的字符串。
source/series/basis/percent 单位、三个角色和显式 v1 窗口／年龄配置继续沿用。
本批不注册 MSS family、catalog 或运行消费者。

每个 v2 row 恰有：

- observation_date、value、revision_id
- source_published_at：必须显式 null，不能省略或推算
- first_seen_at：指定采集器首次完整收到该声明语义行版本的时间
- received_at：研究 consumer 收到该固定版本的时间
- capture_sha256：该行版本首次被看到时保留的原始完整响应之声明 hash
- row_sha256：producer 声明的不可变行内容引用

两个 hash 均要求小写 64 位十六进制形式。observer 不读取响应、不重算 hash、
不认证来源或时钟、不确定“首次”真实性，也不验证 producer 的 hash 算法。
这里是引用和一致性检查，不是历史 PIT 证据。collector 在外部保留原始 bytes
和捕获记录。重复下载不能刷新旧 first_seen 或把首次 capture 引用换成新版
整文件 hash；更正须另留版本，不改写旧接受决策。无状态纯函数不能跨调用
强制这些持久记录规则。

### 时间投影与可见冲突

v2 时间精确支持 YYYY-MM-DDTHH:MM:SS，可带 1–6 位小数秒，后接 Z 或 ±HH:MM。
偏移小时不得大于 23、分钟不得大于 59；不支持更高精度、逗号小数或带秒的偏移。
不截断／舍入时间；不支持的形式保持 unknown。合法时间归一 UTC。选中行满足 first_seen_at <= received_at <= decision_at；
first_seen 的 UTC 日期不得早于观察日。known_at 为 first_seen／received 较晚值，
合法顺序下等于 received，不是源发布时间。

先排除显式窗口外日期、未来观察日，以及 first_seen 或 received 晚于决策的行，
再处理非选择器字段。隐藏行不影响计数、校验、身份、端点记录和数值。
无法解析的选择器不能证明不可见；若其他合法选择器尚未排除该行，则 unknown。

可见行保持严格日期顺序；同日两行，包括完全重复，也属于歧义。
不排序、不去重、不 latest-wins、不自行选择修订。重复端点没有选中端点 metadata。
同一观察／revision 身份下内容或时间冲突为 unknown；同一 series 中，
同一 row hash 对应不同观察日或数值也为 unknown。一个 capture hash 可以
合法对应同份响应的多条不同记录。

旧观察今天首次采集后，可以在显式窗口／年龄允许时成为今天已知的信息，
不能成为更早决策可见的信息。年龄始终取观察日期，不按采集／接收时间刷新。

### 输出与保证范围

v2 保留 collector/basis 及每个无歧义端点的 null publication、first_seen、
received、known_at、revision 和 hash 引用，不输出 available_at。
first_seen_delay_calendar_days 仅比较日期标签；consumer_receipt_lag_seconds
表示首次采集到 consumer 接收的间隔。两者都不是源公布延迟或市场收盘至发布时间。

缺失／非法字段、身份、时间、非有限值、可见冲突、错误角色／basis／单位、
过期或准确端点不可用，均 unknown 且不给数值变化。非法配置仍为 ContractError。
AI、机会和控制字段不属于该精确合同。

同源 nominal/real 的 approximate spread 与独立 reported breakeven 分开。
缺 breakeven 不抹掉两条有效声明事实或合法配对差值，整体 quality 仍 unknown。
所有输出保持 UNVALIDATED_RESEARCH、CALLER_DECLARATIONS_AND_CONSISTENCY_ONLY、
historical_pit_verified=false、backtest_eligible=false、position_control_allowed=false。

本批仅离线合同准备，未证明真实采集、来源权利、原始 bytes、可信 first_seen
时钟、前向历史、经济资格或获批消费。冻结 v2 后另行复审 MSS adapter 才接入，
不改旧 v1。真实采集／采用各需证据，不能还原采集前的历史可得性。

既有 focused unittest 命令同时运行原 v1 和合成 v2：版本／collector gate、
到达边界、旧日期非回填可见性、旧数据年龄、未来／迟到修订不变性、
可见版本歧义、hash 引用一致性、局部 series、缺独立 breakeven、严格 JSON
和输入不变。纯测试不能证明外部 first_seen 持久性。
