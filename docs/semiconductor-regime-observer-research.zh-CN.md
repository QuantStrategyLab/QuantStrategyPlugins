# 半导体三轴状态观察研究

状态：`UNVALIDATED_RESEARCH`。这是可直接调用的纯研究模块，不是已启用插件、策略路由或交易权限。没有生产校准或经济增量结论。

[Full English contract](semiconductor-regime-observer-research.md)

## 边界与现有接口

`quant_strategy_plugins.semiconductor_regime_observer_research` 在现有研究模块旁新增 SOXX／SOXL 收盘观察证据，复用当前 `plugin_signal_envelope_v2.canonical_json_bytes` 和 `build_signal_envelope`，不修改原接口合同。

价格／SMA、总体方差实现波动、尾部峰值回撤沿用现有 QQQ observer 口径。合成测试用相同人工数列核对四个共有特征；原 QQQ observer 保持原样，绝不重标为 SOXX。

早期 QSP `3416da47580be1537183e378f3ca9efacc6f9b8c` 是 UES optional research dependency 声明的固定源码锚点，不证明现役安装、启用或生产 producer／consumer pin。

不修改包级 __init__ 导出，不注册运行入口。不新增 CLI、runner 入口、catalog、依赖、默认／live 配置、服务或调度。普通 import 不启用或运行该研究入口。新模块本身无 provider、文件系统、时钟、AI、券商或策略依赖；原包级 import 不变。

输出没有仓位、资金、订单、控制或授权字段。观察、获批策略目标、风险缩减／否决和执行分别负责。数据恢复或风险解除不能用旧信号补仓；新风险须有当前有效的获批策略信号、共同预算、已有持仓／挂单净额及原账户／恢复权限。这是后续消费约束，本模块没有实现对应动作。

## 可调用 API

- `build_semiconductor_regime_observation(snapshot, config)`：确定性观察；输入缺失或不一致返回 unknown
- `semiconductor_regime_observer_config_sha256(config)`：冻结研究配置的规范身份
- `semiconductor_regime_observation_usable_at(observation, at)`：显式时间的数据资格／新鲜度检查，不是交易许可
- `build_semiconductor_regime_signal_v2(*, snapshot, config, producer, input_provenance)`：计算观察并调用原纯 V2 builder

全部计算配置必须明确提供。非法配置或 V2 绑定抛出不回显数据的 `ContractError`。数据缺陷有独立资格原因，不会变成市场风险标签。

V2 研究入口准确为：

`quant_strategy_plugins.semiconductor_regime_observer_research:build_semiconductor_regime_signal_v2`

wrapper 要求 producer.repo=QuantStrategyLab/QuantStrategyPlugins、上述准确 entrypoint 及对应配置 hash。原 V2 helper 继续校验不可变 revision／code／config digest 的形式，并拒绝禁用控制字段和 mutable latest 引用。调用方的 code／revision 声明不是实际已安装字节证明，仍须独立 P3 证据。

input_provenance 恰有 p1_manifest_sha256、input_root_sha256、date_cutoff；cutoff 与观察一致，root 必须等于观察的因果 input_sha256，P1 hash 形式须合法。这只验证声明一致性，不证明 P1 内容、供应商真实性或研究资格。含隐藏未来行的全文件 manifest 不能替代合格因果投影 manifest。

## 标的与代理差异

只接受以下准确配对：

| symbol | series_role | 含义 |
| --- | --- | --- |
| SOXX | SIGNAL_PROXY | SOXL 研究候选的半导体信号代理 |
| SOXL | EXECUTION_BENCHMARK | SOXL 自身价格路径的观察基准 |

两个序列分别形成输入身份。SOXX 信号不能默认等于 SOXL 收益：杠杆、日重置、跟踪差异、波动耗损、隔夜跳空及成交／成本口径均须独立验证。不计算执行价格或真实策略收益。

QQQ 属于独立 QQQ／TQQQ 背景。本模块拒绝 QQQ，不复制其状态为半导体证据。

## 严格输入合同

顶层字段必须恰为：

schema_version、symbol、series_role、as_of、available_at、decision_at、calendar、adjustment、components、bars。

- schema_version：qsl.semiconductor-regime-input.research.v1
- as_of：严格 YYYY-MM-DD 结束交易日
- available_at：此因果输入快照首次完整可得时间；不晚于 decision_at，不早于使用的行／组件
- decision_at：观察实际评估／完成发布时点；真实 producer 不能回填为完成发布之前
- 全部时间要求显式 ISO 时区，输出归一 UTC

calendar 恰有 id、version、available_at、sessions。调用方提供完整正式交易日列表及不可变版本，包括节假日／提前收盘；模块不自行猜测。每个 session 恰有 date、close_at、complete。选中交易日严格递增，complete=true，decision_at 前已收盘，结束于 as_of 且覆盖计算窗口。此 SOXX／SOXL 合同要求 close_at 的 UTC 日期等于 session 标签。价格日期不在声明日历内则资格失败。

adjustment 恰有 basis、version、available_at、point_in_time_attested。basis 明确为 raw、split_adjusted 或 split_and_distribution_adjusted；可得时间不晚于 decision_at，point_in_time_attested=true。版本／ID 不得为空或使用 latest。不同复权口径不能混为同一可比实验；raw 拆分跳变仍是数据资格风险。不重新计算复权因子。

components 恰有 prices、calendar、adjustment，每个恰有 as_of、available_at、version。全部同一截止日并在 decision_at 前可得。日历／复权的版本与可得时间还须匹配对应声明；价格组件可得时间不早于其使用的行。版本指冻结 producer／解释口径，不是会重写的全文件 latest 身份。

每个 bar 恰有 symbol、date、close、closed、available_at、adjustment_available_at、adjustment_version。选中行标的／因子版本一致，价格有限且为正、非布尔，closed=true，发布不早于该日收盘与因子可得时点。重复或乱序日期拒绝；模块不自动重排或选择多个已可得修订。

资格明确标 qualified_by_declaration：只校验调用方声明及内部一致性。不证明供应商历史真实性、正式日历完整性或因子可得性。如果日历／价格同时遗漏一个交易日却声称完整，单靠本检查无法发现。真实 P0 证据与不可变 PIT 快照仍是必需条件。

## 因果投影与 hash

采用按 as_of／decision_at 切片的政策：

1. date>as_of 的行在读取其他列之前即不可见
2. 历史日期的价格 available_at>decision_at 时行不可见，损坏或无关剩余列也不影响历史结果
3. adjustment_available_at>decision_at 时该复权行也不进入切片
4. 必需行不可得是覆盖缺失，不补价，不转成市场压力
5. 日历中 as_of 后的交易日同样不可见

选择器本身无法解析就不能证明属于未来，产生 ROW_SELECTOR_INVALID。顶层／组件声明必须是该历史决策的冻结版本；重写声明不属于隐藏未来行追加。

input_sha256 使用原 QSP canonical JSON helper，只 hash 因果投影。隐藏行不进特征、校验、计数、理由或身份，追加后整个历史观察和 hash 不变。选中错误值只得到诊断错误类型身份，仍为 unknown，不成为合格证据。配置 hash 和 V2 payload hash 分别独立。

## 显式特征与配置

配置 schema 为 qsl.semiconductor-regime-config.research.v1。其余字段必须恰为：

- sma_window_sessions≥2；sma_slope_lag_sessions≥1
- path_window_returns≥2，需要步数＋1 个收盘价
- short_vol_window_returns／long_vol_window_returns≥2，短≤长
- drawdown_window_sessions≥2；annualization_sessions≥1
- ttl_seconds≥1；classification 明确为 null 或下述完整研究假设

没有数值默认值。窗口、TTL、阈值和比较政策必须先冻结再评估，不能从未来结果选参数。测试中的短窗口和数值仅是 SYNTHETIC_FIXTURE_ONLY，不是部署建议。

最少历史长度为 max(SMA窗口＋斜率滞后、路径收益数＋1、短收益数＋1、长收益数＋1、回撤交易日数)。

| 特征 | 定义 |
| --- | --- |
| close_to_sma_ratio | 最后收盘／当前尾部 SMA −1 |
| sma_slope_per_session | (当前 SMA／滞后 SMA −1)／滞后交易日数 |
| path_efficiency | 路径端点净变化绝对值／每步绝对变化之和 |
| short／long_realized_volatility_annualized | 算术收益总体标准差 × 年化交易日数平方根 |
| volatility_ratio | 短波动／长波动 |
| trailing_drawdown_ratio | 最后收盘／尾部窗口峰值 −1 |

有限特征保留 12 位小数，分类用同一精度。零路径变化时 path_efficiency=null；长波动为零时 volatility_ratio=null。它们是市场特征定义域未知，不能自动判震荡或安全。计算非有限则数据资格失败并清空所有特征。

## 独立三轴与研究假设

classification=null 是正常的仅特征模式。数据声明合格仍给特征，三轴全为 unknown／CLASSIFICATION_NOT_CONFIGURED。

分类配置恰有 hypothesis_id、status=UNVALIDATED_RESEARCH_HYPOTHESIS、direction、trendiness、pressure。不接受 calibrated 或概率。

- 方向：显式正数 price_distance_min／sma_slope_min；价格位置与均线斜率一起过正阈值为 up，一起过负阈值为 down。显著反向冲突或阈值间隙均 unknown
- 趋势性：0≤range_efficiency_max<trend_efficiency_min≤1；低效率为 range_like，高效率为 trend_like，间隙 unknown。range_like 不证明均值回归盈利，也不授权 RSI2
- 压力：0≤drawdown_normal_max<drawdown_stress_min≤1；0≤volatility_ratio_normal_max<volatility_ratio_stress_min。两个市场特征共同成立才为 normal／stressed；显著冲突及间隙均 unknown

压力只读取市场特征。输入缺失／不一致使 quality unknown、各轴 unknown／INPUT_QUALIFICATION_FAILED，不产生 stressed 或 risk_off。零分母在资格声明合格时仍是独立的市场特征未知。

没有拟合模型、HMM、参数优化器、状态记忆、最短驻留或隐藏迟滞。后续切换政策需另有预登记的因果候选／版本和验证。

## 可得时间、过期与输出

输出记录 schema／特征版本、配置／输入 digest、标的／角色、as_of、日历／复权／producer 上下文、特征、三轴及独立 quality。

- input_available_at：声明的完整输入可得时间
- decision_at：实际评估／完成发布时间
- available_at：不早于两者；合格观察中等于 decision_at，不能回填为更早原始价格发布时间
- valid_until：as_of 正式 close_at＋显式 ttl_seconds，右端开区间

decision_at≥valid_until 即过期、unknown。重播旧收盘或改评估时间不能续期。usable helper 仅在声明资格合格、已达到 available_at／decision_at、且严格早于 valid_until 时为真；分类仍可 unknown。true 只是有效观察证据，不是交易许可。

consumer 仍须独立核实际发布时间、不可变 V2 payload、P1／P2／P3 证据、来源身份和有效期。available_at／decision_at 检查只核声明，实际计算／发布时间证明仍留 P0；合成未来行不变性不是真实供应商 PIT 证据。hash 和纯函数不是认证或生产采用证明。

## 验证与后续准入

运行 `PYTHONPATH=src python -m pytest -q tests/test_semiconductor_regime_observer_research.py tests/test_qqq_price_regime_observer_v2.py tests/test_plugin_signal_envelope_v2.py`，再运行既有全仓 tests、Ruff、空白检查和 package build。

合成覆盖未来／迟到隐藏行不变、迟到必需行、未完成／未收盘日历、复权不可得、组件异日／异版本、零路径／零波动、NaN／infinity／极端有限数值、重复／乱序、冲突、TTL边界／重播、仅特征模式及原 QQQ／V2 兼容。独立测试 producer repo／entrypoint／config 与因果 root／cutoff 绑定。

这些是合同／接口结果，不是真实行情回测、经济 alpha、供应商 PIT 核证、生产部署或现役消费。后续仍须真实 P0 合格输入、冻结可比基准、预登记／全部试验、因果样本外、共同成本／风险约束、组件消融和真实无订单 paired shadow，之后才可讨论获准采用。
