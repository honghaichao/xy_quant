# xy_quant — CLAUDE.md

> Agent 操作手册。任何 Agent 接手本项目，先读此文件。

## 项目概述

个人 A 股量化交易系统。包含数据层、信号引擎、回测引擎、策略管理、AI Agent、Web Dashboard、复盘报告。

## 快速启动

```bash
cd /Volumes/quant-ssd/projects/xy_quant
export PYTHONPATH=/Volumes/quant-ssd/projects/xy_quant
export TUSHARE_TOKEN=e1abaabf9cb905ae1f4baa751f178762c281a90f4398f73aba768d5d

# 启动 Dashboard
.venv/bin/python scripts/run_web.py  # → http://localhost:5004

# Dashboard 页面
# ├── /                         ← Vue SPA 首页（信号/持仓/回测/AI Agent）
# ├── /factors                  ← 因子分析仪表盘（98 因子 IC 排名+时序）
# ├── /live                     ← 实盘组合跟踪（净值曲线/持仓/订单/交易）
# ├── /risk                     ← 风控仪表盘（集中度/止损预警/VaR）
# ├── /strategy-editor          ← Monaco 在线策略编辑器（保存/回测/新建/删除）
# ├── /stock/<code>             ← 个股 K 线（ECharts 蜡烛图）
# └── /backtest/<run_id>        ← 单次回测报告

# 确认数据状态
.venv/bin/python -c "
import duckdb
c=duckdb.connect('data_store/market.duckdb',read_only=1)
r=c.execute('SELECT MAX(trade_date),COUNT(*) FROM daily_bar').fetchone()
print(f'daily_bar latest: {r[0]}, rows: {r[1]}')
c.close()
"

# 如果数据不是今天，先补数
.venv/bin/python scripts/backfill_day.py --trade-date $(date +%Y-%m-%d)

# 扫描今日信号（批量版更快）
.venv/bin/python scripts/batch_scan.py --date $(date +%Y%m%d)

# 填充信号事件
.venv/bin/python scripts/populate_signal_events.py

# 启动 Dashboard
.venv/bin/python scripts/run_web.py  # → http://localhost:5004
```

## 目录结构

```
xy_quant/
├── README.md              ← 系统文档（主入口，数据/模块/命令/路线）
├── PLAN.md / PLAN_v7/8    ← 原始建设计划（部分过时，参考用）
├── CLAUDE.md              ← 本文件（Agent 操作手册）
│
├── config/                ← 配置系统
│   ├── settings.py        ←    Pydantic Settings (.env + settings.yaml)
│   ├── settings.yaml      ←    业务配置
│   ├── scheduler_jobs.yaml←    定时任务 cron 配置
│   └── review_rules.yaml  ←    P1 复盘判定阈值
│
├── utils/                 ← 工具层
│   ├── logger.py          ←    loguru
│   ├── exception.py       ←    自定义异常
│   ├── rate_limiter.py    ←    令牌桶
│   ├── retry.py           ←    tenacity 装饰器
│   └── calendar.py        ←    交易日历
│
├── data/                  ← 数据层
│   ├── source/            ←    Tushare + AKShare 适配器 (实现 IDataSource)
│   ├── storage/           ←    DuckDB + PG + Redis (实现 IMarketStore/IMetaStore/ICache)
│   ├── updater/           ←    数据更新业务逻辑
│   ├── validator/         ←    数据校验
│   ├── adjust/            ←    复权处理
│   └── api.py             ←    统一数据 API（聚宽风格，10 个公开函数）
│
├── signals/               ← 信号引擎（从 SilverM 移植）
│   ├── scan_signals.py    ←    全市场多进程扫描
│   └── signal_cal/        ←    7 策略 + S1 卖出 + 指标引擎
│       ├── B1_module.py   ←    天宫 B1（39 条件低吸）
│       ├── B2_module.py   ←    天宫 B2（31 条件追涨）
│       ├── BLKB2_module.py←    暴力 K + BLKB2 组合
│       ├── SCB_module.py  ←    沙尘暴
│       ├── DZ30_module.py ←    单针 30
│       └── S1_module.py   ←    S1 卖出信号
│
├── backtest/              ← 回测引擎（从 SilverM 移植）
│   ├── engine.py          ←    Backtrader 封装
│   ├── run_backtest.py    ←    单股回测入口
│   └── batch_backtest.py  ←    批量回测
│
├── engine/                ← 统一 JQ 引擎（2026-07 新增，回测/实盘双跑）
│   ├── account.py         ←    账务核心（T+1/费率/取整，两端共用）
│   ├── context.py         ←    Context/Portfolio/Position + g 对象
│   ├── clock.py           ←    时间槽→成交价语义（唯一权威映射）
│   ├── api.py             ←    聚宽 API 命名空间注入器
│   ├── market_data.py     ←    get_current_data 防未来函数视图
│   ├── loader.py          ←    零 import 策略加载器
│   ├── backtest_engine.py ←    回测引擎（run_one_day 与实盘共用）
│   ├── live_engine.py     ←    实盘引擎（夜间结算+次日预演）
│   └── persistence.py     ←    jq_live_state/trades/nav + order_queue
│
├── strategies/            ← 策略管理（从 SilverM 移植）
│   ├── registry.py        ←    策略注册表（已修复 DB 依赖）
│   ├── jq/caimadama.py    ←    聚宽格式参考策略（零 import，引擎注入 API）
│   └── base/              ←    策略基类
│       ├── framework_strategy.py  ←  BaseStrategy (Backtrader)
│       └── portfolio_strategy.py  ←  PortfolioStrategy (组合)
│
├── agent/                 ← AI Agent（从 SilverM 移植，49 .py）
│   ├── api/               ←    analyzer / batch_analyzer
│   ├── analysts/          ←    market / fundamentals / news
│   ├── researchers/       ←    bull / bear
│   ├── risk_mgmt/         ←    conservative / neutral / aggressive
│   ├── graph/             ←    trading_graph
│   ├── llm_adapters/      ←    deepseek / minimax / factory
│   ├── dataflows/         ←    news / markets / stock_adapter
│   └── memory/            ←    记忆管理
│
├── web/                   ← Dashboard（从 SilverM 移植）
│   ├── app.py             ←    Flask 主应用（50+ 路由）
│   ├── api/               ←    signals / positions / backtest / agent / data_update
│   ├── templates/         ←    独立模板页面（factors/live/risk/strategy-editor）
│   └── frontend/dist/     ←    Vue 3 SPA（信号/持仓/回测/AI Agent）
│
├── trading/               ← 交易层（从 SilverM 移植）
│   └── portfolio.py       ←    持仓管理 + 每日净值
│
├── review/                ← 复盘报告（xy_quant 原有）
│   ├── main.py            ←    每日复盘主入口
│   ├── collector.py       ←    数据采集器
│   ├── analyzer.py        ←    规则分析器
│   ├── narrative.py       ←    文案生成器
│   └── renderer/          ←    HTML + PNG 渲染器
│
├── scripts/               ← 脚本入口（60+ .py）
│   ├── backfill_day.py    ←    单日补数
│   ├── backfill_history.py←    历史回补
│   ├── batch_scan.py      ←    批量信号扫描
│   ├── run_signal_scan.py ←    信号扫描入口
│   ├── run_backtest_b1.py ←    B1 回测入口
│   ├── run_review.py      ←    复盘入口
│   ├── run_scheduler.py   ←    定时调度器入口
│   ├── populate_signal_events.py  ←  信号→事件填充
│   ├── populate_strategy_registry.py ← 策略注册
│   ├── full_load_*.py     ←    全量加载（17 个）
│   └── update_*.py        ←    增量更新（22 个）
│
├── tools/                 ← 工具
│   └── visualization/     ←    charts.py (ChartPlotter)
│
├── data_store/market.duckdb ← DuckDB 数据库（99 表）
├── deploy/docker-compose.yml ← PostgreSQL + Redis
└── .env.example           ← 环境变量模板
```

## 数据库

### DuckDB：data_store/market.duckdb（99 表）

**核心数据表：**
- `daily_bar` (777 万行, 2020-01 ~ 现在)：日线 OHLCV
- `daily_basic` (772 万行)：每日指标
- `adj_factor` (790 万行)：复权因子
- `minute_bar_YYYY_MM` (77+ 个)：分钟线，2020-01 ~ 2026-07-14，17.4 亿行
- `daily_signals` (43万行, 80 个交易日)：信号扫描结果（截至 2026-07-16）
- `signal_events` (31万行)：信号事件明细
- `factor_data` (42万行, 77 个交易日)：因子快照
- `factor_ic` (1666 条)：因子 IC 值，每日自动挖掘
- `factor_rank` (98 个因子)：因子排名（按 |IC| 排序）

**个股 K 线图：** `/stock/<code>` — ECharts蜡烛图 + MA5/10/20/60/120 + 支撑压力位 + Bollinger Bands + 成交量 + 买卖信号标记 + 换手率 + 右下角持仓侧边栏

**应用层表（17 张，已有数据）：**
- `backtest_run` / `backtest_trades` / `backtest_performance` → B1 回测 8 条
- `positions` / `portfolio_daily` / `portfolio_daily_strategy` → positions 12 持仓+8卖出, portfolio_daily 待填充
- `strategy_registry` → 7 策略已注册
- `agent_analysis_results` → 待填充
- `data_pipeline_run` / `step_update_log` / `trade_audit_log` → 待填充

### PostgreSQL：Docker quant_postgres:55432

- `stock_basic` (5,540 行)
- `trade_calendar` (到 2026-12-31)
- 财务三表 + 资金流 + 龙虎榜等 22 张表

启动 PG：
```bash
docker compose -f deploy/docker-compose.yml up -d
```

## 常见操作

### 数据补数
```bash
# 单日
.venv/bin/python scripts/backfill_day.py --trade-date 2026-07-14

# 范围（支持 --resume 断点续传）
.venv/bin/python scripts/backfill_history.py --start-date 2026-07-01 --end-date 2026-07-14 --resume
```

### 分钟线补数
```bash
# 全量补缺失（自动扫描缺口 + 执行）
.venv/bin/python scripts/full_load_minute_bar.py \
  --start-date 2026-05-06 --end-date 2026-07-14 \
  --missing-only --batch-run --workers 20 --queue-workers 3
```

### 信号扫描
```bash
# 批量版（快，一次性拉数据，~22min 全量）
.venv/bin/python scripts/batch_scan.py --date 20260714

# 单进程版（稳妥，每只 stock 重连，~90min）
.venv/bin/python scripts/run_signal_scan.py --date 20260714 --limit 100
```

### 回测
```bash
# B1 策略回测
.venv/bin/python scripts/run_backtest_b1.py --signal-date 20260714

# Backtrader 引擎回测
.venv/bin/python scripts/run_backtest.py --stock 600030 --start 20240101 --end 20241231
```

### JQ 引擎（聚宽格式策略，回测/实盘同一套代码）
```bash
# 回测（新引擎，报告+入库+web 全兼容）
.venv/bin/python scripts/run_backtest.py --strategy caimadama_jq --start 20260101 --end 20260717

# 平价模式（复刻旧 runner 口径，已验证 122 天持仓 0 差异、期末权益 0.000% 偏差）
.venv/bin/python scripts/run_backtest.py --strategy caimadama_jq --parity-mode --start 20260101 --end 20260714

# 实盘夜间（结算上一交易日 + 预演下一交易日推飞书；调度 23:05 jq_live，初始 disabled）
.venv/bin/python scripts/run_jq_live.py --dry-run          # 预览
.venv/bin/python scripts/run_jq_live.py                    # 真跑（写 jq_live_* 表 + order_queue + positions）
```
实盘策略配置在 `config/settings.yaml` trading.live.strategies（mode: paper|confirm）。
状态表：jq_live_state（快照，可删后确定性重放）/ jq_live_trades / jq_live_nav / order_queue。
策略文件写法：真聚宽格式零 import（initialize/run_daily/order_target_value…由引擎注入），
参考 strategies/jq/caimadama.py。聚宽数据函数（get_price 等 13 个）在 jq_adapter/。

### 信号事件填充
```bash
.venv/bin/python scripts/populate_signal_events.py
```

### 调度器管理
```bash
# 查看已注册任务
.venv/bin/python scripts/run_scheduler.py --list

# 启动后台调度器
nohup .venv/bin/python scripts/run_scheduler.py > logs/scheduler.log 2>&1 &

# 立即执行某个任务
.venv/bin/python scripts/run_scheduler.py --run-now backfill_day

# 查看调度器日志
tail -f logs/scheduler.log
```

### 数据查询
```bash
.venv/bin/python -c "
import duckdb
c=duckdb.connect('data_store/market.duckdb',read_only=1)
# 日线范围
print(c.execute('SELECT MIN(trade_date),MAX(trade_date),COUNT(*) FROM daily_bar').fetchone())
# 最新信号
print(c.execute('SELECT date,COUNT(*) FROM daily_signals GROUP BY date').fetchall())
# 分钟线覆盖
print(c.execute('SELECT MIN(datetime),MAX(datetime),COUNT(*) FROM minute_bar').fetchone())
c.close()
"
```

## 定时调度

### 本地调度器（APScheduler，常驻后台）

| 时间 | 任务 | 说明 |
|---|---|---|
| 周一~五 20:30 | backfill_day | 日线 + 基本指标 |
| 周一~五 20:45 | backfill_day | 涨停板 + 资金流 |
| 周一~五 21:00 | backfill_day | 龙虎榜 T+1 |
| 周一~五 22:07 | batch_scan | 全市场信号扫描 |
| 周一~五 22:17 | signal_events | 信号→事件转换 |
| 周一~五 22:30 | factor_compute | 因子计算 |
| 周一~五 22:35 | auto_factor_mine | 因子自动挖掘 (IC ranking) |
| 周一~五 22:45 | risk_check | 风险检查 |
| 周一~五 22:50 | feishu_notify | 飞书卡片推送 |
| 周一~五 22:55 | build_positions | 信号→持仓建仓（建仓+卖出）|
| 周一~五 23:00 | portfolio_daily | 持仓净值快照 |
| 周一~五 23:05 | jq_live | JQ 实盘引擎（结算+预演，**初始 disabled**）|
| 周日 08:07 | backfill_day | 股票列表 + 日历 + 板块成分周更 |

## Web Dashboard

```bash
.venv/bin/python scripts/run_web.py    # → http://localhost:5004
```
| 页面 | 功能 |
|---|---|
| `/` | Vue SPA 首页（信号/持仓/回测/AI Agent）|
| `/factors` | 因子分析仪表盘（98 因子 IC 排名+时序）|
| `/live` | 实盘组合跟踪（净值曲线/持仓/订单/交易）|
| `/risk` | 风控仪表盘（集中度/止损预警/VaR）|
| `/strategy-editor` | Monaco 在线策略编辑器（保存/回测/新建/删除）|
| `/stock/<code>` | 个股 K 线（ECharts 蜡烛图）|
| `/backtest/<run_id>` | 单次回测报告（KPI/图表/交易明细）|

注意：Tushare 日线数据在收盘 15:00 后通常 17:30~20:00 到位。若 backfill_day 跑完 daily_bar < 100 条，说明数据还没到全，调度器设置了 20:30/20:45/21:00 三次重试。

### cc-connect 调度（远程触发）

| 时间 | 任务 |
|---|---|
| 周一~五 17:37 | 数据补数 + 扫描 + 事件 |
| 周一~五 22:07 | 信号事件填充 |
| 周日 08:07 | 周度数据更新 |

## 重要限制

1. **DuckDB 单写锁**：同时只有 1 个进程可写。信号扫描时不要查 DB
2. **信号扫描 ~22 分钟全量**：5,500+ 只股票，纯 Python 指标计算
3. **B1/B2 信号极少**：触发条件严格，非 bug
4. **Tushare 限频 200 次/分钟**：rate_limiter 已控制
5. **分钟线按月分表**：通过 `minute_bar` 视图统一查询
6. **所有脚本需设置 PYTHONPATH**：或 cd 到项目根目录
