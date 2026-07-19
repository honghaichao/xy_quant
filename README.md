# xy_quant

个人量化交易系统工程骨架，按接口驱动架构分阶段建设。

## 快速开始

```bash
bash deploy/setup.sh
```

## 配置说明

请先复制模板并填写实际配置：

```bash
cp .env.example .env
```

详细字段见 `.env.example`。

## 数据源说明

- 默认主数据源为 `Tushare`
- `minute_bar`（分钟线）全量/增量脚本默认走 `Tushare`
- `AKShare` 保留为补充/回退数据源

## 模块说明

- `interfaces/`：抽象接口层
- `config/`：全局配置与规则
- `data/`：数据源、存储、更新、校验、统一 API
- `review/`：每日复盘报告
- `factor/`：因子引擎
- `backtest/`：回测引擎
- `strategy/` / `risk/` / `scheduler/`：策略、风控、调度
- `api/` / `ui/`：Web 服务
- `live/`：实盘交易
- `utils/`：通用工具
- `scripts/`：脚本入口
- `docs/`：文档

## 开发约定

开发约定见 `docs/conventions.md`。
