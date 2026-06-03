# QuantStrategyPlugins

[English README](README.md)

> 投资有风险。本项目不构成投资建议，仅用于学习、研究和工程审阅。

## 这个仓库是什么

QuantStrategyPlugins 是 QuantStrategyLab 的策略插件包。提供 market-regime control、通知 artifact 和研究侧 plugin 输出等 sidecar 策略插件。

它支撑系统运行，但不决定哪个策略应该 live。策略资格由策略仓和 snapshot 仓负责；券商执行由平台仓负责。

## 设计边界

- 下游仓库依赖的契约要保持稳定，必要时做版本化。
- 除非有协同迁移计划，否则优先保持向后兼容。
- 密钥和环境专属配置不要写进共享库代码。
- 会影响多个平台或策略包的改动，需要在文档中说明。

## 仓库结构

- `src/`：库代码和运行时代码。
- `tests/`：单元测试、契约测试和回归测试。
- `docs/`：运行手册、设计说明、证据和集成契约。
- `.github/workflows/`：CI、定时任务、发布或部署 workflow。
- `scripts/`：运维脚本和本地辅助工具。

## 快速开始

```bash
python -m pip install -e .
python -m pytest -q
```

## 延伸文档

- [`docs/market-regime-control-plan.md`](docs/market-regime-control-plan.md)
- [`docs/market-regime-control-plan.zh-CN.md`](docs/market-regime-control-plan.zh-CN.md)

## 许可证

详见 [LICENSE](LICENSE)。
