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
- `taco_rebound_shadow`：研究阶段的反弹预算观察插件。通用 runner 会保持 gating，直到后续验证和晋级标准满足。

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
  --output-dir data/output/tqqq_growth_income/plugins/crisis_response_shadow
```

输出包括 `latest_signal.json`、按日期归档的 JSON、按日期归档的 CSV，以及 evidence CSV。平台运行时通过 `*_STRATEGY_PLUGIN_MOUNTS_JSON` 挂载的就是 `latest_signal.json`。

## 本地检查

```bash
python -m pip install -e '.[test]'
python -m pytest -q
ruff check .
```

## 许可证

MIT License. Copyright (c) 2026 QuantStrategyLab.
