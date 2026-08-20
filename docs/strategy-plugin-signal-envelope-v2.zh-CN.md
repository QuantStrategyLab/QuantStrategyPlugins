# 策略插件确定性信号 Envelope V2（仅设计契约）

> 状态：`DESIGN_ONLY_NOT_RUNTIME`
> Schema：`qsl.strategy-plugin-signal.v2`

本契约为可历史回测、由策略自行消费的**确定性插件信号**定义最小、可复算的
JSON envelope。它不是运行时接线：不会读取行情、访问 GCS、调用 legacy resolver、
改变策略参数，也不会创建订单、仓位或自动化权限。

## 适用边界

- 插件只表达由冻结输入复算出的信号事实，例如 `regime`、原因码或风险状态。
- AI/LLM 黑盒不得写入此 envelope；它们只能走人工通知/决策路径，不能成为可回测
  信号的隐含输入。
- 该 envelope 不含、也会拒绝任何 `order`、`target_weight`、`authorization`、
  `automation_approved` 或 `ai_*` / `llm_*` 字段（包括嵌套 payload）。
- 旧的 policy/action 树同样会在任意嵌套层被拒绝：`position_control`、
  `consumption_policy`、`execution_control(s)`、`runtime`、`broker`、`account`、
  `capital`、`trade(s)` 及其前缀变体。`risk_state` 和 `reason_codes` 仍是允许的
  纯信号事实，不表达仓位、交易或授权。
- 它不替换现有 market-regime 输出，也不授权任何旧 artifact 被 runtime 消费。

## 固定 schema

顶层字段必须且只能是以下七项：

| 字段 | 要求 | 用途 |
| --- | --- | --- |
| `schema_version` | 固定 `qsl.strategy-plugin-signal.v2` | 拒绝未知 schema |
| `plugin_id` | 小写稳定标识 | 识别信号生产者 |
| `kind` | 固定 `deterministic_signal` | 排除 AI 或执行命令 |
| `producer` | 见下表 | 固定代码来源 |
| `input` | 见下表 | 绑定 P1 可用输入与 cutoff |
| `payload` | 非空 JSON object | 插件的策略信号事实 |
| `payload_sha256` | payload 的 SHA-256 | 发现任何内容改变 |

`producer` 必须且只能有：`repo`（`owner/repository`）、`revision`（完整小写 git
SHA）、`entrypoint`（`python.module:function`）、`code_sha256` 和 `config_sha256`。
`input` 必须且只能有：`p1_manifest_sha256`、`input_root_sha256` 和
`date_cutoff`（`YYYY-MM-DD`）。所有 hash 均为小写 64 位 SHA-256，`revision` 为
40 至 64 位小写 git SHA。

`latest`、`latest_signal.json` 或任意指向 mutable latest artifact 的值会被拒绝；
它们不能成为证据输入。

## 确定性 hash

`payload_sha256` 等于下列 Python 标准 JSON 表示的 UTF-8 SHA-256：

```python
json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")
```

校验器先限制 payload 为 JSON 值且禁止 `NaN`/无穷大，然后比对 hash。Python 对象本身
仍可被调用方修改；所谓“immutable”是指 artifact 的来源、输入和 payload hash 一起构成
不可静默篡改的身份。每次读取或消费前都必须重新校验。

## 生命周期位置

```text
P1 frozen data manifest/root + cutoff
             │
             ▼
deterministic plugin → V2 envelope (validated, hashed)
             │
             ▼
future P2 candidate explicitly pins this exact envelope
             │
             ▼
future P3 independently recomputes and verifies it
```

本 PR 只完成左侧 envelope 的本地 schema/校验能力。P2/P3 接线、策略消费、任何 shadow
运行，以及 P4/P5/P6 均不在本契约或本次实现范围内。

## 迁移规则

旧 `market_regime_control`、其 `latest_signal.json` 和 legacy resolver 只能保留用于
历史回放或受控迁移。它们在没有明确 P2 绑定和 P3 重算证明前，不是 V2 信号来源，也不得
被策略名称自动挂载。
