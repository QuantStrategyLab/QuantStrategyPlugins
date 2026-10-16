# QuantStrategyPlugins

输出与 QuantPlatformKit 兼容的信号产物的 sidecar 策略插件包。

[English](README.md) | 简体中文

## 状态

实验性项目，使用风险自负。本项目不构成投资建议，也不保证任何交易结果。它的输出是研究证据，不是交易指令。

## 简介

QuantStrategyPlugins 提供 sidecar 策略插件：市场状态控制、shadow 信号和仅研究的输出。每个插件输出一个 QuantPlatformKit 消费方可读取的信号信封。插件在本地基于价格历史运行并写出产物，让策略仓与管线仓在不改券商对接代码的前提下补充市场状态与风险上下文。它面向扩展策略行为的工程师。

## 不适用范围

它不决定实盘资格。它不连接券商，也不提交订单。它不授予执行权限。

## 快速开始

需要 Python 3.11 或更高版本。

最小运行时安装（仅库与插件 runner，不含可选的 AI 审阅客户端）：

```bash
python -m pip install .
```

完整测试：测试会导入可选的 AI 审阅客户端，因此需安装 `test` 与 `ai` extra
以匹配 CI（`.github/workflows/ci.yml`），再运行 pytest：

```bash
python -m pip install -e '.[test,ai]'
python -m pytest -q
```

查看插件 runner 的选项。runner 通过 `--config` 读取 TOML 配置，示例见 `docs/examples/strategy_plugins.example.toml`。

```bash
qsp-run-strategy-plugins --help
```

`ai` extra 会加入固定版本的 AI gateway 客户端；安装它不会启用审阅、配置凭据或授予执行权限。

## 配置

| 变量 | 必填 | 默认值 | 用途 |
|---|---|---|---|
| `YFINANCE_PROXY` | 否 | 无 | Yahoo Finance 价格下载所用的代理覆盖。 |
| `HTTPS_PROXY` | 否 | 无 | 出站价格下载所用的代理。 |
| `HTTP_PROXY` | 否 | 无 | 出站价格下载所用的代理。 |
| `ALL_PROXY` | 否 | 无 | 出站价格下载的回退代理。 |

可选的 AI 审阅客户端从环境变量读取端点与 token，未配置并启用时保持关闭。

## 仓库结构

```
src/        插件实现与信号信封
scripts/    插件 runner 与研究脚本
docs/       生命周期策略与插件设计说明
tests/      单元与契约测试
```

## 参与贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 安全

见 [SECURITY.md](SECURITY.md)。安全漏洞不要开公开 issue，也不要让凭据、私有数据和外部服务 token 进入 Git 或日志。

## 许可证

MIT，见 [LICENSE](LICENSE)。
