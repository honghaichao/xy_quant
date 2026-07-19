# 个人量化交易系统 — 重建计划书 (SilverM 整合版 v7)

> 本文档基于 `SilverM-quant-main` 的实际代码架构，融合 `xy_quant` 的工程化实践，
> 重新制定一套务实、可迭代的量化系统建设路线。
>
> **核心原则**：先跑通、再优化。不追求完美抽象，以结果驱动。

---

## 〇、出发点：SilverM-quant-main 现状评估

### 0.1 已有资产

| 层面 | 状态 | 说明 |
|---|---|---|
| 数据层 | 🟢 **成熟** | 7.6M 行日线 (2020-2026.06)，多源断路器，DWD 层数据仓库 |
| 信号层 | 🟡 **代码完整** | 7 策略信号计算完备，但 daily_signals 表为空（本机未跑） |
| 回测层 | 🟡 **代码完整** | Backtrader 引擎、批量回测、多维度分析均已实现 |
| 策略层 | 🟢 **成熟** | 策略注册表、版本管理、参数系统、CLI 工具 |
| Agent 层 | 🟢 **成熟** | 多 Agent 辩论式分析 (5 分析师 + 3 风控)，LLM 适配器 |
| 交易层 | 🟡 **代码完整** | 持仓管理、每日净值、审计系统 |
| Web 层 | 🟢 **成熟** | Flask + Vue 3 + Tailwind Dashboard，功能齐全 |
| 因子层 | 🟡 **表已建** | factor_data/IC/return 表已定义但为空 |
| 风控层 | 🔴 **缺失** | 无独立风控模块 |
| 实盘层 | 🔴 **缺失** | 无实盘交易对接 |

### 0.2 核心问题

1. **硬编码路径** — 大量 `sys.path` 写死 `/Users/mawenhao/Desktop/code/股票策略`
2. **无接口抽象** — 数据源直接耦合，切换需改代码
3. **测试覆盖弱** — tests/ 只有零星几个文件
4. **无复盘模块** — 没有盘后分析报告
5. **数据流水线为空** — 本机 daily_signals/positions/backtest 全空，流水线从未跑过
6. **缺少分钟线** — 仅日线，无法做日内策略
7. **数据库单点** — 仅 DuckDB，无 PostgreSQL 存储元数据
8. **无 Docker** — 缺少容器化部署

### 0.3 与 xy_quant 的互补

| 领域 | SilverM-quant 优势 | xy_quant 优势 |
|---|---|---|
| 策略信号 | ✅ 7 策略 + 注册表 | ❌ 未实现 |
| 回测 | ✅ Backtrader 批量回测 | ❌ 仅接口 |
| Agent/AI | ✅ 多 Agent 辩论 | ❌ 仅接口 |
| Web Dashboard | ✅ 完整前端 | ❌ 仅接口 |
| 数据接口抽象 | ❌ 耦合 | ✅ ABC 接口层 |
| 测试/CI | ❌ 弱 | ✅ pytest + ruff + mypy |
| 分钟线 | ❌ 无 | ✅ 16.9 亿行 |
| 复盘报告 | ❌ 无 | ✅ P1 已实现 |
| 工程化 | ❌ 松 | ✅ Configured |
| 数据覆盖 | 2020→ (6 年) | 1990→ (36 年) |

---

## 一、总体架构设计

### 1.1 设计原则

1. **DuckDB 为主，PostgreSQL 为辅** — 行情用 DuckDB（性能），元数据/财务用 PG（关系查询）
2. **轻量接口** — 核心数据源和存储保留抽象接口（仅在需要切换时有用），策略/信号层不需要
3. **脚本驱动** — 所有操作通过 scripts/ 下的 CLI 脚本，支持 `--help` 和 `run()` 函数
4. **流水线编排** — data → signals → backtest → trade，每一步有日志和状态追踪
5. **渐进式完善** — 先跑通核心流水线，再补齐分钟线、复盘、实盘

### 1.2 总架构图

```
┌──────────────────────────────────────────────────────────────────┐
│                        Web Dashboard (Flask + Vue 3)              │
│   首页 │ 信号 │ 持仓 │ 回测 │ 多信号共振 │ Agent │ 数据更新       │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────┼───────────────────────────────────────┐
│              应用层       │                                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐│
│  │ 复盘报告  │ │ AI Agent │ │ 策略CLI  │ │ 交易审计  │ │ 因子分析 ││
│  │ (P1)     │ │ 分析     │ │ 工具     │ │          │ │         ││
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └─────────┘│
└──────────────────────────────────────────────────────────────────┘
                           │
┌──────────────────────────┼───────────────────────────────────────┐
│              核心层        │                                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐            │
│  │ 信号引擎  │ │ 回测引擎  │ │ 交易引擎  │ │ 风控引擎  │            │
│  │ 7策略扫描 │ │ Backtrader│ │ 持仓管理  │ │ (P4新增) │            │
│  └─────┬────┘ └────┬─────┘ └────┬─────┘ └──────────┘            │
└────────┼───────────┼───────────┼─────────────────────────────────┘
         │           │           │
┌────────┼───────────┼───────────┼─────────────────────────────────┐
│  数据层 │           │           │                                   │
│  ┌─────┴───────────┴───────────┴──────┐                            │
│  │       统一数据 API (data/api.py)    │                            │
│  └────────────────┬───────────────────┘                            │
│  ┌────────────────┴───────────────────┐                            │
│  │  DuckDB (行情+信号+回测)            │                            │
│  │  dwd_daily_price / dwd_daily_basic │                            │
│  │  daily_signals / backtest_*        │                            │
│  │  factor_data / positions           │                            │
│  └────────────────────────────────────┘                            │
│  ┌────────────────────────────────────┐                            │
│  │  PostgreSQL (元数据+财务+日志)       │                            │
│  │  stock_basic / trade_calendar      │                            │
│  │  income / balancesheet / cashflow  │                            │
│  │  data_update_log / quality_report  │                            │
│  └────────────────────────────────────┘                            │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐               │
│  │ Tushare 适配器│ │ AKShare 适配器│ │ Baostock 适配器│              │
│  │ (复盘+日线)   │ │ (资金流+涨停) │ │ (免费回退)    │              │
│  └──────────────┘ └──────────────┘ └──────────────┘               │
└──────────────────────────────────────────────────────────────────┘
```

### 1.3 数据职责矩阵

```
┌─────────────────────┬──────────┬─────────┬──────────┐
│   数据类型           │ Tushare  │ AKShare │ Baostock │
├─────────────────────┼──────────┼─────────┼──────────┤
│ 日线历史             │   主     │    -    │   备     │
│ 复权因子             │   主     │    -    │   备     │
│ 每日指标 (PE/PB等)   │   主     │    -    │   -      │
│ 财务三表             │   主     │    -    │   -      │
│ 财务指标             │   主     │    -    │   -      │
│ 分红送股             │   主     │    -    │   -      │
│ 分钟线历史           │   主     │   备    │   -      │
│ 涨停板/炸板          │   -      │   主    │   -      │
│ 板块资金流           │   -      │   主    │   -      │
│ 个股资金流           │   -      │   主    │   -      │
│ 概念/行业板块成分    │   备     │   主    │   -      │
│ 龙虎榜               │   主     │   备    │   -      │
│ 融资融券             │   主     │    -    │   -      │
│ 股东增减持           │   主     │    -    │   -      │
│ 北向资金(历史)       │   主     │    -    │   -      │
│ 指数日线/成分        │   主     │    -    │   -      │
│ 交易日历             │   主     │    -    │   -      │
│ 股票基础信息         │   主     │    -    │   -      │
│ 实时 Tick (P6)       │   -      │    -    │   -      │
│ 实盘下单 (P6)        │   -      │    -    │   -      │
└─────────────────────┴──────────┴─────────┴──────────┘
```

---

## 二、目录结构（目标）

```
quant_system/
├── interfaces/                  # 抽象接口层（核心数据源和存储）
│   ├── __init__.py
│   ├── data_source.py           # IDataSource
│   ├── market_store.py          # IMarketStore
│   ├── meta_store.py            # IMetaStore
│   ├── cache.py                 # ICache
│   ├── notifier.py              # INotifier
│   ├── report_renderer.py       # IReportRenderer
│   └── llm_provider.py          # ILLMProvider
├── config/
│   ├── __init__.py
│   ├── settings.py              # Pydantic Settings (.env + settings.yaml)
│   ├── settings.yaml            # 业务配置（路径、限频、起始日期）
│   ├── scheduler_jobs.yaml      # 调度任务 cron 配置
│   └── review_rules.yaml        # P1 复盘判定阈值
├── data/
│   ├── __init__.py
│   ├── source/
│   │   ├── __init__.py
│   │   ├── factory.py           # get_data_source(name) → IDataSource
│   │   ├── tushare_source.py    # Tushare 实现 IDataSource
│   │   ├── akshare_source.py    # AKShare 实现 IDataSource
│   │   └── baostock_source.py   # Baostock 实现 IDataSource (回退)
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── factory.py           # get_market_store() / get_meta_store()
│   │   ├── duckdb_store.py      # DuckDB 实现 IMarketStore
│   │   ├── pg_store.py          # PG 实现 IMetaStore
│   │   └── redis_cache.py       # Redis 实现 ICache
│   ├── updater/
│   │   ├── __init__.py
│   │   ├── base.py              # BaseUpdater 抽象类
│   │   ├── daily_price_updater.py
│   │   ├── daily_basic_updater.py
│   │   ├── adj_factor_updater.py
│   │   ├── index_daily_updater.py
│   │   ├── minute_bar_updater.py
│   │   ├── limit_list_updater.py
│   │   ├── money_flow_updater.py
│   │   ├── finance_updater.py
│   │   ├── member_updater.py
│   │   ├── top_list_updater.py
│   │   ├── margin_updater.py
│   │   ├── hk_hold_updater.py
│   │   ├── suspend_updater.py
│   │   ├── holdertrade_updater.py
│   │   ├── basic_updater.py
│   │   └── calendar_updater.py
│   ├── validator/
│   │   ├── __init__.py
│   │   ├── completeness.py      # 完整性检查
│   │   ├── consistency.py       # 一致性检查
│   │   └── anomaly.py           # 异常检测
│   ├── adjust/
│   │   ├── __init__.py
│   │   └── adjuster.py          # 复权处理
│   └── api.py                   # 统一数据 API (聚宽风格)
├── signals/                     # 信号引擎 (从 SilverM 移植)
│   ├── __init__.py
│   ├── scan_signals.py          # 全市场多进程信号扫描
│   └── signal_cal/
│       ├── __init__.py
│       ├── basic_module.py      # 基础技术指标计算
│       ├── B1_strategy_module.py
│       ├── B2_strategy_module.py
│       ├── BLK_strategy_module.py
│       ├── BLKB2_strategy_module.py
│       ├── SCB_strategy_module.py
│       ├── DZ30_strategy_module.py
│       └── S1_module.py         # 卖出信号
├── backtest/                    # 回测引擎 (从 SilverM 移植)
│   ├── __init__.py
│   ├── engine.py                # BacktestEngine (Backtrader 封装)
│   ├── multi_dimension.py       # 多维度分析
│   └── batch_backtest.py        # 批量回测
├── strategies/                  # 策略管理 (从 SilverM 移植)
│   ├── __init__.py
│   ├── registry.py              # 策略注册表
│   ├── base/
│   │   ├── __init__.py
│   │   ├── framework_strategy.py
│   │   ├── multi_factor_strategy.py
│   │   └── portfolio_strategy.py
│   └── strategy_template.py     # 策略开发模板
├── trading/                     # 交易层 (从 SilverM 移植)
│   ├── __init__.py
│   ├── portfolio.py             # 持仓管理 + 每日净值
│   ├── audit.py                 # 交易审计
│   └── runner.py                # 交易主入口
├── agent/                       # AI Agent 层 (从 SilverM 移植)
│   ├── __init__.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── analyzer.py          # 单股分析
│   │   └── batch_analyzer.py    # 批量分析
│   ├── analysts/
│   │   ├── __init__.py
│   │   ├── market_analyst.py
│   │   ├── fundamentals_analyst.py
│   │   └── news_analyst.py
│   ├── researchers/
│   │   ├── __init__.py
│   │   ├── bull_researcher.py
│   │   └── bear_researcher.py
│   ├── risk_mgmt/
│   │   ├── __init__.py
│   │   ├── conservative_debator.py
│   │   ├── neutral_debator.py
│   │   ├── aggressive_debator.py
│   │   └── debate_aggregator.py
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── state.py
│   │   └── trading_graph.py
│   ├── llm_adapters/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── deepseek.py
│   │   ├── minimax.py
│   │   └── factory.py
│   ├── dataflows/
│   │   ├── __init__.py
│   │   ├── news/
│   │   │   ├── __init__.py
│   │   │   ├── aggregator.py
│   │   │   ├── base.py
│   │   │   ├── eastmoney.py
│   │   │   └── sentiment.py
│   │   └── markets/
│   │       ├── __init__.py
│   │       └── router.py
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── memory_manager.py
│   │   └── vector_store.py
│   ├── cache/
│   │   ├── __init__.py
│   │   └── redis_cache.py
│   └── traders/
│       ├── __init__.py
│       └── trader.py
├── review/                      # 复盘报告 (从 xy_quant 移植)
│   ├── __init__.py
│   ├── collector.py             # 数据采集器
│   ├── analyzer.py              # 规则分析器
│   ├── narrative.py             # 文案生成器
│   ├── main.py                  # 复盘入口
│   ├── llm/
│   │   └── local_rule_provider.py
│   └── renderer/
│       ├── __init__.py
│       ├── factory.py
│       ├── html_renderer.py
│       ├── image_renderer.py
│       └── templates/
├── factor/                      # 因子引擎 (P2 新建)
│   ├── __init__.py
│   ├── registry.py              # 因子注册表
│   ├── base.py                  # 因子基类
│   ├── technical/               # 量价因子
│   ├── fundamental/             # 基本面因子
│   └── analysis/                # 因子分析 (IC/IR/分层)
├── risk/                        # 风控模块 (P4 新建)
│   ├── __init__.py
│   ├── rules.py                 # 风控规则引擎
│   └── monitor.py               # 风控监控
├── web/                         # Web 仪表板 (从 SilverM 移植)
│   ├── __init__.py
│   ├── app.py                   # Flask 主应用
│   ├── api/
│   │   ├── __init__.py
│   │   ├── signals.py
│   │   ├── positions.py
│   │   ├── backtest.py
│   │   ├── agent.py
│   │   └── data_update.py
│   └── frontend/                # Vue 3 + Vite + Tailwind
│       ├── src/
│       │   ├── App.vue
│       │   ├── main.ts
│       │   ├── components/
│       │   ├── views/
│       │   └── stores/
│       └── dist/
├── utils/                       # 工具层
│   ├── __init__.py
│   ├── logger.py
│   ├── exception.py
│   ├── calendar.py              # 交易日历工具
│   ├── rate_limiter.py          # 令牌桶限频
│   ├── retry.py                 # 重试装饰器
│   └── notifier.py              # 通知（飞书/钉钉/邮件）
├── scripts/
│   ├── __init__.py
│   ├── init_db.py               # 建所有表
│   ├── init_foundations.py      # 初始化基础数据（日历+股票列表）
│   ├── full_load_*.py           # 全量加载脚本 (16个)
│   ├── full_load_all.py         # 全量编排器
│   ├── update_*.py              # 增量更新脚本 (15个)
│   ├── update_all.py            # 日常编排器
│   ├── backfill_day.py          # 单日统一补数
│   ├── backfill_history.py      # 历史回补
│   ├── run_signal_scan.py       # 信号扫描入口
│   ├── run_backtest.py          # 回测入口
│   ├── run_review.py            # 复盘入口
│   ├── run_scheduler.py         # 调度器
│   ├── run_pipeline.py          # 全流水线编排
│   ├── schedule_p0_backfill.py  # P0 守卫型调度
│   └── pipeline_manager.py      # 流水线状态管理
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── unit/
│   └── integration/
├── deploy/
│   ├── docker-compose.yml
│   ├── Dockerfile
│   └── setup.sh
├── docs/
│   ├── conventions.md
│   ├── interfaces.md
│   ├── tables.md
│   └── operations.md
├── .env.example
├── .gitignore
├── pyproject.toml
├── README.md
└── PLAN.md
```

---

## 三、数据库设计（统一版）

### 3.1 DuckDB 表（行情 + 信号 + 回测 + 交易）

#### DWD 层（数据仓库明细层，已从 SilverM 继承）

```sql
-- 日线行情（不复权）
CREATE TABLE dwd_daily_price (
    trade_date  DATE    NOT NULL,
    ts_code     VARCHAR NOT NULL,
    open        DOUBLE,
    high        DOUBLE,
    low         DOUBLE,
    close       DOUBLE,
    vol         BIGINT,
    amount      DOUBLE,
    pct_chg     DOUBLE,
    data_source VARCHAR DEFAULT 'tushare',
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (trade_date, ts_code)
);

-- 日线行情（后复权）
CREATE TABLE dwd_daily_price_hfq (
    ts_code     VARCHAR NOT NULL,
    trade_date  DATE    NOT NULL,
    open        DOUBLE,
    high        DOUBLE,
    low         DOUBLE,
    close       DOUBLE,
    vol         BIGINT,
    amount      DOUBLE,
    pct_chg     DOUBLE,
    adj_factor  DOUBLE,
    data_source VARCHAR DEFAULT 'tushare',
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ts_code, trade_date)
);

-- 每日指标
CREATE TABLE dwd_daily_basic (
    trade_date  DATE    NOT NULL,
    ts_code     VARCHAR NOT NULL,
    close       DOUBLE,
    pe_ttm      DOUBLE,
    pe          DOUBLE,
    ps_ttm      DOUBLE,
    ps          DOUBLE,
    pcf         DOUBLE,
    pb          DOUBLE,
    total_mv    DOUBLE,
    circ_mv     DOUBLE,
    amount      DOUBLE,
    turn_rate   DOUBLE,
    data_source VARCHAR DEFAULT 'tushare',
    PRIMARY KEY (trade_date, ts_code)
);

-- 复权因子
CREATE TABLE dwd_adj_factor (
    ts_code     VARCHAR NOT NULL,
    trade_date  DATE    NOT NULL,
    adj_factor  DOUBLE  NOT NULL,
    data_source VARCHAR DEFAULT 'tushare',
    PRIMARY KEY (ts_code, trade_date)
);

-- 指数日线
CREATE TABLE dwd_index_daily (
    index_code  VARCHAR NOT NULL,
    trade_date  DATE    NOT NULL,
    open        DOUBLE,
    high        DOUBLE,
    low         DOUBLE,
    close       DOUBLE,
    pre_close   DOUBLE,
    change      DOUBLE,
    pct_change  DOUBLE,
    vol         BIGINT,
    amount      DOUBLE,
    data_source VARCHAR DEFAULT 'tushare',
    PRIMARY KEY (index_code, trade_date)
);

-- 股票基础信息
CREATE TABLE dwd_stock_info (
    ts_code     VARCHAR PRIMARY KEY,
    symbol      VARCHAR NOT NULL,
    name        VARCHAR NOT NULL,
    area        VARCHAR,
    industry    VARCHAR,
    market      VARCHAR,
    list_date   DATE,
    is_hs       VARCHAR,
    list_status VARCHAR,
    delist_date DATE,
    data_source VARCHAR DEFAULT 'tushare'
);

-- 交易日历
CREATE TABLE dwd_trade_calendar (
    trade_date  DATE    NOT NULL,
    exchange    VARCHAR NOT NULL,
    is_open     BOOLEAN,
    PRIMARY KEY (trade_date, exchange)
);

-- 分钟线（按月分表）
CREATE TABLE minute_bar (
    ts_code     VARCHAR    NOT NULL,
    datetime    TIMESTAMP  NOT NULL,
    freq        VARCHAR    NOT NULL,
    open        DOUBLE,
    high        DOUBLE,
    low         DOUBLE,
    close       DOUBLE,
    vol         DOUBLE,
    amount      DOUBLE,
    updated_at  TIMESTAMP  DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ts_code, datetime, freq)
);
```

#### 信号层（从 SilverM 继承）

```sql
CREATE TABLE daily_signals (
    date                DATE    NOT NULL,
    code                VARCHAR NOT NULL,
    name                VARCHAR,
    open                DOUBLE,
    high                DOUBLE,
    low                 DOUBLE,
    close               DOUBLE,
    volume              DOUBLE,
    prev_close          DOUBLE,
    change_pct          DOUBLE,
    score_b1            DOUBLE,
    score_b2            DOUBLE,
    score_blk           DOUBLE,
    score_dl            DOUBLE,
    score_dz30          DOUBLE,
    score_scb           DOUBLE,
    score_blkB2         DOUBLE,
    signal_buy_b1       BOOLEAN,
    signal_buy_b2       BOOLEAN,
    signal_buy_blk      BOOLEAN,
    signal_buy_dl       BOOLEAN,
    signal_buy_dz30     BOOLEAN,
    signal_buy_scb      BOOLEAN,
    signal_buy_blkB2    BOOLEAN,
    signal_sell_b1      BOOLEAN,
    signal_sell_b2      BOOLEAN,
    signal_sell_blk     BOOLEAN,
    signal_sell_dl      BOOLEAN,
    signal_sell_dz30    BOOLEAN,
    signal_sell_scb     BOOLEAN,
    signal_sell_blkB2   BOOLEAN,
    score_s1            DOUBLE,
    signal_s1_full      BOOLEAN,
    signal_s1_half      BOOLEAN,
    signal_跌破多空线    BOOLEAN,
    signal_止损          BOOLEAN,
    indicators          JSON,
    is_observing        BOOLEAN DEFAULT FALSE,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (date, code)
);

CREATE TABLE signal_events (
    id              BIGSERIAL PRIMARY KEY,
    date            DATE    NOT NULL,
    code            VARCHAR NOT NULL,
    name            VARCHAR,
    signal_abbrev   VARCHAR NOT NULL,
    version         VARCHAR,
    signal_type     VARCHAR NOT NULL,   -- buy / sell
    score           DOUBLE,
    signal_field    VARCHAR,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_signal_events_date ON signal_events(date);
```

#### 回测层（从 SilverM 继承）

```sql
CREATE TABLE backtest_run (
    run_id          VARCHAR PRIMARY KEY,
    strategy_name   VARCHAR,
    strategy_params JSON,
    start_date      DATE,
    end_date        DATE,
    universe        VARCHAR,
    benchmark       VARCHAR,
    initial_capital DOUBLE,
    status          VARCHAR,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at    TIMESTAMP
);

CREATE TABLE backtest_trades (
    id          INTEGER,
    run_id      VARCHAR NOT NULL,
    datetime    TIMESTAMP,
    code        VARCHAR,
    name        VARCHAR,
    action      VARCHAR,
    price       DOUBLE,
    size        INTEGER,
    amount      DOUBLE,
    commission  DOUBLE,
    industry    VARCHAR,
    market_cap_group VARCHAR,
    PRIMARY KEY (run_id, id)
);

CREATE TABLE backtest_performance (
    run_id              VARCHAR PRIMARY KEY,
    total_return        DOUBLE,
    annual_return       DOUBLE,
    max_drawdown        DOUBLE,
    sharpe_ratio        DOUBLE,
    win_rate            DOUBLE,
    total_trades        INTEGER,
    avg_holding_days    DOUBLE,
    industry_analysis   JSON,
    cap_group_analysis  JSON,
    monthly_returns     JSON
);

CREATE TABLE backtest_daily_pnl (
    run_id      VARCHAR NOT NULL,
    date        DATE    NOT NULL,
    pnl         DOUBLE,
    pnl_pct     DOUBLE,
    total_value DOUBLE,
    positions   JSON,
    PRIMARY KEY (run_id, date)
);
```

#### 交易层（从 SilverM 继承）

```sql
CREATE TABLE positions (
    id              SERIAL PRIMARY KEY,
    code            VARCHAR NOT NULL,
    name            VARCHAR,
    strategy        VARCHAR,
    signal_date     DATE,
    buy_date        DATE,
    shares          INTEGER,
    buy_price       DOUBLE,
    buy_change_pct  DOUBLE,
    buy_score_b1    DOUBLE,
    buy_score_b2    DOUBLE,
    buy_dif         DOUBLE,
    buy_j_value     DOUBLE,
    current_price   DOUBLE,
    current_score_s1 DOUBLE,
    stop_loss_pct   DOUBLE DEFAULT 0.03,
    status          VARCHAR DEFAULT 'holding',
    sell_date       DATE,
    sell_price      DOUBLE,
    sell_reason     VARCHAR,
    profit_loss     DOUBLE,
    profit_pct      DOUBLE,
    notes           VARCHAR,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE portfolio_daily (
    id              SERIAL PRIMARY KEY,
    date            DATE NOT NULL,
    init_cash       DECIMAL(12,2),
    position_cost   DECIMAL(12,2),
    position_value  DECIMAL(12,2),
    position_pnl    DECIMAL(12,2),
    closed_pnl      DECIMAL(12,2) DEFAULT 0,
    total_pnl       DECIMAL(12,2),
    available_cash  DECIMAL(12,2),
    position_ratio  DECIMAL(5,2),
    total_value     DECIMAL(12,2),
    notes           VARCHAR,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 按策略维度的每日净值
CREATE TABLE portfolio_daily_strategy (
    id              SERIAL PRIMARY KEY,
    date            DATE NOT NULL,
    strategy        VARCHAR NOT NULL,
    position_cost   DECIMAL(12,2),
    position_value  DECIMAL(12,2),
    position_pnl    DECIMAL(12,2),
    closed_pnl      DECIMAL(12,2) DEFAULT 0,
    total_pnl       DECIMAL(12,2),
    trade_count     INTEGER DEFAULT 0,
    notes           VARCHAR,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE trade_audit_log (
    id          SERIAL PRIMARY KEY,
    audit_date  DATE NOT NULL,
    check_item  VARCHAR,
    check_type  VARCHAR,
    severity    VARCHAR,
    status      VARCHAR,
    detail      VARCHAR,
    fix_action  VARCHAR,
    before_val  VARCHAR,
    after_val   VARCHAR,
    auditor     VARCHAR DEFAULT 'auto',
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### 因子层

```sql
CREATE TABLE factor_data (
    date                DATE    NOT NULL,
    code                VARCHAR NOT NULL,
    pe_ttm              FLOAT,
    pb                  FLOAT,
    ps_ttm              FLOAT,
    pcf_ttm             FLOAT,
    dividend_yield      FLOAT,
    roe                 FLOAT,
    roa                 FLOAT,
    gross_margin        FLOAT,
    net_margin          FLOAT,
    debt_to_asset       FLOAT,
    revenue_growth_yoy  FLOAT,
    profit_growth_yoy   FLOAT,
    macd_dif            FLOAT,
    macd_dea            FLOAT,
    macd_histogram      FLOAT,
    kdj_k               FLOAT,
    kdj_d               FLOAT,
    kdj_j               FLOAT,
    rsi_6               FLOAT,
    rsi_12              FLOAT,
    rsi_24              FLOAT,
    boll_upper          FLOAT,
    boll_mid            FLOAT,
    boll_lower          FLOAT,
    ma_5                FLOAT,
    ma_10               FLOAT,
    ma_20               FLOAT,
    ma_60               FLOAT,
    volatility_20d      FLOAT,
    turnover_20d        FLOAT,
    volume_ratio        FLOAT,
    price_momentum_20d  FLOAT,
    price_momentum_60d  FLOAT,
    update_time         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (date, code)
);

CREATE TABLE factor_ic (
    date                DATE    NOT NULL,
    factor_name         VARCHAR NOT NULL,
    ic                  FLOAT,
    ic_rank             FLOAT,
    ir                  FLOAT,
    ic_positive_ratio   FLOAT,
    update_time         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (date, factor_name)
);

CREATE TABLE factor_return (
    date                DATE    NOT NULL,
    factor_name         VARCHAR NOT NULL,
    long_return         FLOAT,
    short_return        FLOAT,
    long_short_return   FLOAT,
    quantile_returns    JSON,
    update_time         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (date, factor_name)
);
```

#### Agent 分析结果

```sql
CREATE TABLE agent_analysis_results (
    run_id      VARCHAR NOT NULL,
    symbol      VARCHAR,
    trade_date  VARCHAR,
    result_json JSON,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### 策略管理（从 SilverM 继承）

```sql
CREATE TABLE strategy_registry (
    id              VARCHAR PRIMARY KEY,
    name            VARCHAR NOT NULL,
    display_name    VARCHAR,
    class_path      VARCHAR,
    source_file     VARCHAR,
    description     VARCHAR,
    version         VARCHAR DEFAULT '1.0.0',
    author          VARCHAR,
    status          VARCHAR DEFAULT 'active',
    strategy_type   VARCHAR,
    threshold_required BOOLEAN DEFAULT FALSE,
    min_data_days   INTEGER DEFAULT 0,
    param_schema    JSON,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE strategy_params (
    id              SERIAL PRIMARY KEY,
    strategy_name   VARCHAR NOT NULL,
    param_name      VARCHAR NOT NULL,
    param_type      VARCHAR,
    default_value   JSON,
    current_value   JSON,
    description     VARCHAR,
    constraints     JSON,
    is_required     BOOLEAN DEFAULT FALSE,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE strategy_versions (
    id              SERIAL PRIMARY KEY,
    strategy_name   VARCHAR NOT NULL,
    signal_abbrev   VARCHAR,
    version         VARCHAR NOT NULL,
    backtest_metrics JSON,
    backtest_params JSON,
    run_id          VARCHAR,
    status          VARCHAR DEFAULT 'tested',
    promoted_at     TIMESTAMP,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE strategy_metadata (
    name            VARCHAR PRIMARY KEY,
    signal_abbrev   VARCHAR,
    class_name      VARCHAR,
    description     VARCHAR,
    status          VARCHAR DEFAULT 'draft',
    current_version VARCHAR,
    promotion_config JSON,
    latest_backtest JSON,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### 流水线管理（从 SilverM 继承）

```sql
CREATE TABLE data_pipeline_run (
    id              INTEGER,
    pipeline_id     VARCHAR,
    pipeline_name   VARCHAR,
    step_name       VARCHAR,
    step_order      INTEGER,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at      TIMESTAMP,
    completed_at    TIMESTAMP,
    duration_sec    FLOAT,
    params          JSON,
    status          VARCHAR,
    records_count   INTEGER,
    error_message   VARCHAR,
    depends_on      VARCHAR,
    dependency_met  BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (pipeline_id, step_name)
);

CREATE TABLE step_update_log (
    id              SERIAL PRIMARY KEY,
    pipeline_id     VARCHAR,
    step_name       VARCHAR,
    update_type     VARCHAR,
    update_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    start_time      TIMESTAMP,
    end_time        TIMESTAMP,
    duration_sec    FLOAT,
    expected_count  INTEGER,
    actual_count    INTEGER,
    is_success      BOOLEAN,
    error_message   VARCHAR,
    error_details   JSON,
    step_details    JSON,
    validation_results JSON,
    check_time      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE pipeline_monitor_flag (
    id          SERIAL PRIMARY KEY,
    date        VARCHAR,
    completed   BOOLEAN DEFAULT FALSE,
    completed_at TIMESTAMP
);
```

### 3.2 PostgreSQL 表（元数据 + 财务 + 日志）

> 与 xy_quant 原有设计一致，包含：
> - `stock_basic`, `trade_calendar`, `stock_suspend`
> - `income`, `balancesheet`, `cashflow`, `fina_indicator`, `dividend`
> - `top_list`, `margin_detail`, `hk_hold`, `stk_holdertrade`
> - `concept_member`, `industry_member`, `index_weight`
> - `concept_money_flow`, `industry_money_flow`, `stock_money_flow`
> - `data_update_log`, `data_quality_report`
>
> 完整表结构见 PLAN.md 历史版本第六章，此处不赘述。

---

## 四、建设路线图

```
Phase A: 工程重建 (2-3天)
  ├─ 统一目录结构，pyproject.toml
  ├─ 移植接口层 (只保留核心接口)
  ├─ 移植工具层
  └─ Docker Compose (PG + Redis)
            ↓ Gate0

P0: 数据层统一 (1周)
  ├─ 数据源适配器 (Tushare + AKShare + Baostock)
  ├─ 存储层 (DuckDB + PG)
  ├─ 从 SilverM 迁移现有数据到新表结构
  ├─ 分钟线补数（利用 xy_quant 的分钟线数据）
  ├─ 全量/增量脚本体系
  └─ 数据校验 + 统一 API
            ↓ Gate1

P1: 信号 + 回测跑通 (1周)
  ├─ 移植信号模块 (7策略 + 卖出信号)
  ├─ 移植回测引擎 (Backtrader)
  ├─ 全市场信号扫描 (多进程)
  ├─ 批量回测跑通
  └─ 策略注册表 + CLI
            ↓ Gate2

P2: 交易 + 复盘 + Dashboard (1周)
  ├─ 移植交易/持仓/审计模块
  ├─ 移植复盘报告 (collector + analyzer + renderer)
  ├─ 移植 Web Dashboard (Flask + Vue 3)
  └─ 每日流水线打通 (data → signals → backtest → dashboard)
            ↓ Gate3

P3: 因子引擎 (1-2周)
  ├─ 因子注册表 (基类 + 工厂)
  ├─ 量价因子 (30+)
  ├─ 基本面因子 (ROE/PB/PE/...)
  ├─ 因子分析 (IC/IR/分层/衰减)
  └─ 因子合成 (加权/正交/中性化)
            ↓ Gate4

P4: 策略 + 风控 + AI 深度集成 (1-2周)
  ├─ 策略开发框架
  ├─ 风控引擎
  ├─ AI Agent 深度集成 (从策略发现到信号验证)
  └─ 调度器 (APScheduler)
            ↓ Gate5

P5: 实盘准备 (时间待定)
  ├─ 仿真交易网关 (PaperGateway)
  ├─ QMT 实盘网关 (QmtGateway)
  ├─ 仿真盘跑 2 周
  └─ 实盘上线
```

---

## 五、Phase A：工程重建（详细计划）

### 5.1 目标

创建统一的项目骨架，将两个项目的优点整合到一个目录中。

### 5.2 目录初始化

```bash
mkdir quant_system && cd quant_system
git init
# 创建所有 __init__.py 和目录
```

### 5.3 pyproject.toml（合并依赖）

```toml
[project]
name = "quant_system"
version = "0.1.0"
description = "Personal quantitative trading system"
requires-python = ">=3.11,<3.13"
dependencies = [
    # 数据源
    "tushare>=1.4.0",
    "akshare>=1.15.0",
    "baostock>=0.8.8",
    # 存储
    "duckdb>=1.0.0",
    "psycopg[binary]>=3.2.0",
    "redis>=5.0.0",
    "sqlalchemy>=2.0.0",
    # 数据处理
    "polars>=1.0.0",
    "pandas>=2.2.0",
    "numpy>=1.26.0",
    "pyarrow>=15.0.0",
    # 配置
    "pydantic>=2.6.0",
    "pydantic-settings>=2.2.0",
    "python-dotenv>=1.0.0",
    "pyyaml>=6.0.0",
    # 工具
    "loguru>=0.7.2",
    "tenacity>=8.2.3",
    "apscheduler>=3.10.4",
    # 回测
    "backtrader>=1.9.78",
    # Web
    "flask>=3.0.0",
    "flask-cors>=4.0.0",
    # 报告
    "jinja2>=3.1.0",
    "matplotlib>=3.8.0",
    "pillow>=10.0.0",
    "playwright>=1.42.0",
    # LLM
    "langchain-core>=0.1.0",
]

[project.optional-dependencies]
factor = ["scipy>=1.13.0", "scikit-learn>=1.4.0", "numba>=0.59.0"]
backtest_extra = ["quantstats>=0.0.62"]
parallel = ["ray[default]>=2.10.0"]
dev = [
    "pytest>=8.0.0",
    "pytest-cov>=5.0.0",
    "pytest-mock>=3.12.0",
    "ruff>=0.4.0",
    "black>=24.0.0",
    "mypy>=1.10.0",
    "pre-commit>=3.7.0",
]
```

### 5.4 核心接口定义（最小集）

仅保留真正需要抽象的接口：

1. **IDataSource** — 数据源（Tushare/AKShare/Baostock 切换）
2. **IMarketStore** — 行情存储（DuckDB）
3. **IMetaStore** — 元数据存储（PostgreSQL）
4. **ICache** — 缓存（Redis）
5. **INotifier** — 通知（飞书/钉钉/邮件）
6. **IReportRenderer** — 报告渲染（HTML/PNG/PDF）
7. **ILLMProvider** — LLM 服务

### 5.5 脚本统一模板

```python
"""scripts/update_daily.py - 日线增量更新。"""
import argparse, sys
from datetime import date, datetime
from loguru import logger
from config.settings import settings
from data.source.factory import get_data_source
from data.storage.factory import get_market_store
from data.updater.daily_price_updater import DailyPriceUpdater
from utils.logger import setup_logger


def run(
    target_date: date | None = None,
    start: date | None = None,
    end: date | None = None,
    ts_codes: list[str] | None = None,
    force: bool = False,
) -> int:
    """供调度器调用的入口。"""
    source = get_data_source(settings.primary_data_source)
    store = get_market_store()
    updater = DailyPriceUpdater(source, store)
    return updater.update(target_date=target_date, start=start, end=end,
                          ts_codes=ts_codes, force=force)


def parse_args():
    p = argparse.ArgumentParser(description="日线增量更新")
    p.add_argument("--date", type=str, default=None, help="目标日期 YYYY-MM-DD")
    p.add_argument("--start", type=str, default=None)
    p.add_argument("--end", type=str, default=None)
    p.add_argument("--ts_codes", type=str, default=None, help="逗号分隔")
    p.add_argument("--force", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    setup_logger(name="update_daily")
    try:
        rows = run(
            target_date=date.fromisoformat(args.date) if args.date else None,
            start=date.fromisoformat(args.start) if args.start else None,
            end=date.fromisoformat(args.end) if args.end else None,
            ts_codes=args.ts_codes.split(",") if args.ts_codes else None,
            force=args.force,
        )
        logger.info(f"完成,影响 {rows} 行")
        return 0
    except Exception as e:
        logger.exception(f"失败: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

### 5.6 Gate0 验收标准

- [ ] 项目目录骨架完整
- [ ] `pyproject.toml` 完整, `pip install -e ".[dev]"` 可跑
- [ ] `.env.example` 创建,所有敏感字段为空
- [ ] `config/settings.py` 可实现从 `.env` 加载
- [ ] 所有核心接口骨架定义完毕
- [ ] `utils/` 工具层实现 (logger/rate_limiter/retry/exception/calendar)
- [ ] Docker Compose 可启动 PG + Redis
- [ ] `pytest` 可运行

---

## 六、P0：数据层统一（详细计划）

### 6.1 数据迁移策略

**第一步：保持 SilverM DuckDB 结构不变，对接现有的 dwd_* 表。**

SilverM-quant-main 的 DuckDB 已有完整数据（7.6M 日线到 2026-06-03），表命名是 `dwd_*`，
而 xy_quant 使用 `daily_bar`/`daily_basic`/`adj_factor` 等命名。

**决策**：统一用 **dwd_*** 命名（后向兼容 SilverM），同时保持 xy_quant 的数据 API 抽象层。

**第二步：将 xy_quant 的分钟线数据迁移到新结构。**

xy_quant 有 16.9 亿行分钟线（2009-2026），按月分表。迁移到 `minute_bar` 单表或保持按月分表。

### 6.2 需要补齐的数据

当前 SilverM DuckDB 数据截止 2026-06-03，距今（2026-07-14）差 1.5 个月。需要：
- `dwd_daily_price` 补到最新交易日
- `dwd_daily_basic` 补到最新
- `dwd_adj_factor` 补到最新
- 财务表（income/balancesheet/cashflow）当前仅 66-113 行，需要从 xy_quant PG 迁移或重拉

### 6.3 脚本清单

**全量加载** (16 个):
`full_load_calendar`, `full_load_basic`, `full_load_daily`, `full_load_adj_factor`,
`full_load_daily_basic`, `full_load_index_daily`, `full_load_minute_bar`,
`full_load_limit_list`, `full_load_money_flow`, `full_load_top_list`,
`full_load_margin`, `full_load_hk_hold`, `full_load_suspend`,
`full_load_finance`, `full_load_member`, `full_load_holdertrade`,
`full_load_all` (编排器)

**增量更新** (15 个):
对应的 `update_*.py` + `update_all.py` (编排器)

**调度器**: `run_scheduler.py`

### 6.4 统一数据 API

```python
# data/api.py - 聚宽风格
def get_price(security, start_date, end_date, frequency='daily',
              fields=None, fq='pre', skip_paused=False) -> pd.DataFrame: ...
def get_fundamentals(table, ts_code, start_date=None, end_date=None,
                     fields=None) -> pd.DataFrame: ...
def get_index_stocks(index_code, date=None) -> list[str]: ...
def get_industry_stocks(industry, date=None) -> list[str]: ...
def get_trade_days(start_date=None, end_date=None) -> list[date]: ...
def get_security_info(ts_code) -> dict: ...
def attribute_history(security, count, unit='1d', fields=None,
                      skip_paused=True, fq='pre') -> pd.DataFrame: ...
def get_money_flow(target_type, code=None, trade_date=None,
                   start_date=None, end_date=None) -> pd.DataFrame: ...
def get_limit_pool(trade_date=None, kind='U', start_date=None,
                   end_date=None) -> pd.DataFrame: ...
```

### 6.5 P0 验收标准 (Gate1)

- [ ] 所有表创建成功
- [ ] 数据源适配器（Tushare + AKShare + Baostock 实现 IDataSource）
- [ ] DuckDB + PG 存储实现就绪
- [ ] 日线数据覆盖到最新交易日
- [ ] 分钟线数据迁移完成
- [ ] 财务数据完整
- [ ] 全量/增量脚本全部可执行（`--help` 全部通过）
- [ ] 数据校验跑通无异常
- [ ] 统一数据 API 可查询
- [ ] 单元测试覆盖率 ≥ 50%

---

## 七、P1：信号 + 回测跑通（详细计划）

### 7.1 从 SilverM 移植的文件

| 源文件 | 目标路径 | 说明 |
|---|---|---|
| `signals/scan_signals_v2.py` | `signals/scan_signals.py` | 去硬编码路径 |
| `signals/singal_cal/basic_module.py` | `signals/signal_cal/basic_module.py` | 基础指标 |
| `signals/singal_cal/B1_strategy_module.py` | `signals/signal_cal/B1_module.py` | B1 策略 |
| `signals/singal_cal/B2_strategy_module.py` | `signals/signal_cal/B2_module.py` | B2 策略 |
| `signals/singal_cal/BLKB2_strategy_module.py` | `signals/signal_cal/BLKB2_module.py` | BLKB2 |
| `signals/singal_cal/SCB_strategy_module.py` | `signals/signal_cal/SCB_module.py` | SCB |
| `signals/singal_cal/DZ30_strategy_module.py` | `signals/signal_cal/DZ30_module.py` | DZ30 |
| `signals/singal_cal/S1_module.py` | `signals/signal_cal/S1_module.py` | 卖出信号 |
| `backtest/engine.py` | `backtest/engine.py` | 去硬编码 |
| `backtest/multi_dimension.py` | `backtest/multi_dimension.py` | 多维度 |
| `backtest/strategy_backtest/*.py` | `backtest/` | 批量回测 |
| `strategies/registry.py` | `strategies/registry.py` | 策略注册表 |
| `strategies/base/*.py` | `strategies/base/` | 策略基类 |
| `tools/strategy_cli.py` | `scripts/strategy_cli.py` | CLI 工具 |

### 7.2 关键修改

1. **去掉所有 `sys.path.insert` 硬编码路径**
2. **改为从 `config.settings` 读取 DB_PATH**
3. **使用 `data.api` 获取数据**（而非直接 DuckDB SQL）
4. **信号扫描写入 `daily_signals` 和 `signal_events`**

### 7.3 流水线

```bash
python scripts/run_pipeline.py --date 2026-07-14
```

内部步骤：
1. `update_daily` — 更新日线到目标日期
2. `update_daily_basic` — 更新每日指标
3. `run_signal_scan` — 全市场信号扫描
4. `run_backtest` — 按策略回测
5. `update_portfolio_daily` — 更新持仓净值

### 7.4 P1 验收标准 (Gate2)

- [ ] `run_signal_scan --date` 能对 5000+ 股票计算信号并写入 `daily_signals`
- [ ] 7 个买入策略 + 卖出信号全部正常
- [ ] `run_backtest` 能跑通单策略回测
- [ ] `batch_backtest` 能跑通批量回测
- [ ] 策略注册表 + CLI 工具可正常使用
- [ ] `run_pipeline` 流水线端到端打通
- [ ] 单元测试覆盖率 ≥ 50%

---

## 八、P2：交易 + 复盘 + Dashboard（详细计划）

### 8.1 从 SilverM 移植

- `scripts/update_portfolio_daily.py` → `trading/portfolio.py`
- `scripts/audit_trade` → `trading/audit.py`
- 交易逻辑 + 持仓管理

### 8.2 从 xy_quant 移植

- `review/` 全套复盘模块
- `reports/` 输出目录

### 8.3 Web Dashboard 移植

- `dashboard/app.py` + API 蓝图 → `web/`
- `frontend/` Vue 3 项目 → `web/frontend/`

### 8.4 P2 验收标准 (Gate3)

- [ ] 持仓管理 + 每日净值更新
- [ ] 每日复盘报告自动生成 (HTML + PNG)
- [ ] Dashboard 首页 / 信号 / 持仓 / 回测 / Agent 页面可用
- [ ] 每日流水线全自动跑通

---

## 九、P3-P5 概要（后续展开）

### P3 因子引擎
- 移植 `factor_data` 计算逻辑
- 因子基类 + 注册表
- 因子分析 (IC/IR/分层/衰减/回归)
- Alpha101 因子库

### P4 策略 + 风控 + AI 深度
- 策略开发框架
- 风控规则引擎
- AI Agent 与策略信号联动
- 调度器时间表

### P5 实盘对接
- PaperGateway 仿真
- QMT 实盘
- 仿真盘观察期 2 周

---

## 十、自检清单（每次 commit 前必跑）

```
[SELF_CHECK]
[✓] 所有函数有 type hints
[✓] 所有 public 函数有 docstring
[✓] ruff 无警告
[✓] mypy 无警告
[✓] 单元测试通过 (pytest)
[✓] 覆盖率 ≥ 50% (Phase A) / ≥ 70% (P0+)
[✓] 没有 TODO/FIXME/XXX 占位
[✓] 没有 print(用 loguru)
[✓] 没有硬编码 token/path
[✓] 没有裸 except
[✓] 接口签名与文档一致
[✓] 表结构与文档一致
```

---

## 十一、禁止行为清单

1. ❌ 修改本文档定义的表名、字段名、字段类型、主键
2. ❌ 修改本文档定义的接口签名
3. ❌ 添加文档没要求的功能
4. ❌ 跳过未实现的依赖（用 TODO/pass/NotImplementedError 占位）
5. ❌ 在代码中硬编码 token、账号、密码、文件路径
6. ❌ 用 print 代替 loguru.logger
7. ❌ 写裸 except: 或 except Exception:
8. ❌ 用字符串拼接 SQL
9. ❌ 在没有 Gate 通过时进入下一阶段
10. ❌ 替用户做产品决策
11. ❌ 自己往 .env 里填真实值
12. ❌ 安装文档没列出的第三方库

---

## 十二、通信协议

- `[GATE_REQUEST]` — 请求通过门禁
- `[GATE_PASS]` — 用户批准通过
- `[ALERT]` — 偏航或冲突告警
- `[QUESTION]` — 需要用户决策
- `[BLOCKED]` — 被外部依赖阻塞
- `[DONE]` — 子模块完成

---

文档结束。

下一步：当用户回复 `[GATE_PASS]` 后，Hermes 从 Phase A 开始执行。
