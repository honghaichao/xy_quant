# 量化交易系统 - 整合计划书 (v8)

> **决策**：以 `xy_quant` 为主工程骨架，从 `SilverM-quant-main` 移植核心应用模块。
> **理由**：xy_quant 工程基础设施完整（虚环境、配置、接口、数据层、复盘、分钟线 16.9 亿行），
> SilverM 上层模块成熟（信号、回测、Agent、Dashboard），各取所长。

## 〇、两项目差异与合并策略

| 模块 | 当前状态 | 目标 |
|---|---|---|
| 数据层 | xy_quant 有完整 P0，数据/命名不同 | 保持 xy_quant 实现，表名统一 |
| 信号层 | xy_quant 无，SilverM 有 7 策略 | 移植到 `signals/` |
| 回测层 | xy_quant 仅接口，SilverM 有完整引擎 | 移植到 `backtest/` |
| 策略管理 | xy_quant 无，SilverM 有注册表系统 | 移植到 `strategies/` |
| 交易层 | xy_quant 无，SilverM 有持仓+审计 | 移植到 `trading/` |
| Agent | xy_quant 仅接口，SilverM 完整 | 移植到 `agent/` |
| Web | xy_quant 仅接口，SilverM 完整 | 移植到 `web/` |
| 复盘 | xy_quant P1 已完成 | 保持不动 |
| 脚本 | xy_quant 有全量/增量脚本体系 | 增加 SilverM 的流水线/信号/回测脚本 |
| 表结构 | 两份各有差异 | 统一到 xy_quant 的表名 |

## 一、目标目录结构

```
xy_quant/
├── interfaces/                  # ✅ 已有，保持不变
├── config/                      # ✅ 已有，保持不变
├── data/                        # ✅ 已有，保持不变
│   ├── source/                  # ✅ 已有：tushare + akshare 适配器
│   ├── storage/                 # ✅ 已有：duckdb + pg + redis
│   ├── updater/                 # ✅ 已有：全表 updater
│   ├── validator/               # ✅ 已有：校验
│   ├── adjust/                  # ✅ 已有：复权
│   └── api.py                   # ✅ 已有：统一数据 API
│
├── signals/                     # 🆕 从 SilverM 移植
│   ├── scan_signals.py          # 全市场多进程信号扫描
│   └── signal_cal/
│       ├── basic_module.py      # 技术指标引擎
│       ├── B1_module.py         # B1 买入策略
│       ├── B2_module.py         # B2 买入策略
│       ├── BLK_module.py        # 暴力K
│       ├── BLKB2_module.py      # 暴力K B2 组合
│       ├── SCB_module.py        # 沙尘暴
│       ├── DZ30_module.py       # 单针30
│       └── S1_module.py         # S1 卖出信号
│
├── backtest/                    # 🆕 从 SilverM 移植
│   ├── engine.py                # Backtrader 引擎封装
│   ├── multi_dimension.py       # 多维度分析
│   └── batch_backtest.py        # 批量回测
│
├── strategies/                  # 🆕 从 SilverM 移植
│   ├── registry.py              # 策略注册表
│   └── base/
│       ├── framework_strategy.py
│       └── multi_factor_strategy.py
│
├── trading/                     # 🆕 从 SilverM 移植
│   ├── portfolio.py             # 持仓管理
│   ├── audit.py                 # 交易审计
│   └── runner.py                # 交易入口
│
├── agent/                       # 🆕 从 SilverM 移植
│   ├── api/                     # analyzer / batch_analyzer
│   ├── analysts/                # market / fundamentals / news
│   ├── researchers/             # bull / bear
│   ├── risk_mgmt/               # conservative / neutral / aggressive
│   ├── graph/                   # trading_graph
│   ├── llm_adapters/            # deepseek / minimax / factory
│   ├── dataflows/               # news / markets
│   ├── memory/                  # 记忆管理
│   ├── cache/                   # 缓存
│   └── traders/                 # 交易信号
│
├── web/                         # 🆕 从 SilverM 移植
│   ├── app.py                   # Flask 主应用
│   ├── api/                     # signals / positions / backtest / agent
│   └── frontend/                # Vue 3 + Vite + Tailwind (可选，先不搬)
│
├── review/                      # ✅ 已有，保持不变
├── factor/                      # ✅ 已有骨架，P3 实现
├── risk/                        # ✅ 已有骨架，P4 实现
├── utils/                       # ✅ 已有，保持不变
├── scripts/                     # ✅ 已有 + 🆕 增加信号/回测/流水线入口
├── tests/                       # ✅ 已有 + 🆕 增加新模块测试
│
├── PLAN_v8.md                   # 本文档
├── pyproject.toml               # 保持不变
└── .env                         # 保持不变
```

## 二、移植清单（按优先级）

### Block 1：信号层 (signals/) — 最高优先级

| 源文件 (SilverM) | 目标文件 (xy_quant) | 改动 |
|---|---|---|
| `signals/scan_signals_v2.py` | `signals/scan_signals.py` | 去掉硬编码路径，用 `config.settings` |
| `signals/singal_cal/basic_module.py` | `signals/signal_cal/basic_module.py` | 校正目录名拼写 (singal→signal) |
| `signals/singal_cal/B1_strategy_module.py` | `signals/signal_cal/B1_module.py` | 去掉 sys.path hack |
| `signals/singal_cal/B2_strategy_module.py` | `signals/signal_cal/B2_module.py` | 同上 |
| `signals/singal_cal/BLKB2_strategy_module.py` | `signals/signal_cal/BLKB2_module.py` | 同上 |
| `signals/singal_cal/SCB_strategy_module.py` | `signals/signal_cal/SCB_module.py` | 同上 |
| `signals/singal_cal/DZ30_strategy_module.py` | `signals/signal_cal/DZ30_module.py` | 同上 |
| `signals/singal_cal/S1_module.py` | `signals/signal_cal/S1_module.py` | 同上 |

### Block 2：回测 + 策略 (backtest/ + strategies/)

| 源文件 | 目标文件 | 改动 |
|---|---|---|
| `backtest/engine.py` | `backtest/engine.py` | 改用 `data.api` 取数据 |
| `backtest/multi_dimension.py` | `backtest/multi_dimension.py` | 去硬编码 |
| `backtest/strategy_backtest/run_backtest.py` | `backtest/run_backtest.py` | 整合 |
| `backtest/strategy_backtest/batch_backtest_V3.py` | `backtest/batch_backtest.py` | 去 Deprecation |
| `strategies/registry.py` | `strategies/registry.py` | 去硬编码 |
| `strategies/base/framework_strategy.py` | `strategies/base/framework_strategy.py` | 去硬编码 |

### Block 3：交易层 (trading/)

| 源文件 | 目标文件 | 改动 |
|---|---|---|
| `scripts/update_portfolio_daily.py` | `trading/portfolio.py` | 重构为模块 |
| 审计逻辑 | `trading/audit.py` | 新写 |

### Block 4：Agent 层 (agent/) — 几乎原样搬

| 源文件 | 目标文件 | 改动 |
|---|---|---|
| `agent_integration/` 全目录 | `agent/` | 去硬编码路径，用 `config.settings` |

### Block 5：Web Dashboard (web/) — 最后搬

| 源文件 | 目标文件 | 改动 |
|---|---|---|
| `dashboard/app.py` | `web/app.py` | 去硬编码路径 |
| `dashboard/agent_api.py` | `web/api/agent.py` | 同上 |
| `dashboard/backtest_api.py` | `web/api/backtest.py` | 同上 |
| `dashboard/data_update_api.py` | `web/api/data_update.py` | 同上 |

## 三、表结构统一

### 表名映射

SilverM 使用 `dwd_*` 前缀（如 `dwd_daily_price`），xy_quant 使用简洁名（如 `daily_bar`）。
**决策：保持 xy_quant 的表名不变**，但在代码中通过统一数据 API (`data/api.py`) 屏蔽差异。

所有上层模块（信号、回测、Agent）必须通过 `data.api` 取数据，不直接查 SQL。

### 需要新增的表（在 xy_quant DuckDB 中创建）

从 SilverM 移植的信号/回测/交易需要这些表：

```sql
-- 日信号表 (从 SilverM 移植)
CREATE TABLE IF NOT EXISTS daily_signals (
    date                DATE    NOT NULL,
    code                VARCHAR NOT NULL,
    name                VARCHAR,
    open                DOUBLE,  high DOUBLE,  low DOUBLE,
    close               DOUBLE,  volume DOUBLE,
    prev_close          DOUBLE,  change_pct DOUBLE,
    score_b1            DOUBLE,  score_b2 DOUBLE,  score_blk DOUBLE,
    score_dl            DOUBLE,  score_dz30 DOUBLE,
    score_scb           DOUBLE,  score_blkB2 DOUBLE,
    signal_buy_b1       BOOLEAN, signal_buy_b2 BOOLEAN,
    signal_buy_blk      BOOLEAN, signal_buy_dl BOOLEAN,
    signal_buy_dz30     BOOLEAN, signal_buy_scb BOOLEAN,
    signal_buy_blkB2    BOOLEAN,
    signal_sell_b1      BOOLEAN, signal_sell_b2 BOOLEAN,
    signal_sell_blk     BOOLEAN, signal_sell_dl BOOLEAN,
    signal_sell_dz30    BOOLEAN, signal_sell_scb BOOLEAN,
    signal_sell_blkB2   BOOLEAN,
    score_s1            DOUBLE,
    signal_s1_full      BOOLEAN, signal_s1_half BOOLEAN,
    signal_跌破多空线    BOOLEAN, signal_止损 BOOLEAN,
    indicators          JSON,
    is_observing        BOOLEAN DEFAULT FALSE,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (date, code)
);

-- 信号事件
CREATE TABLE IF NOT EXISTS signal_events (
    id              BIGINT PRIMARY KEY,
    date            DATE    NOT NULL,
    code            VARCHAR NOT NULL,
    name            VARCHAR,
    signal_abbrev   VARCHAR NOT NULL,
    version         VARCHAR,
    signal_type     VARCHAR NOT NULL,
    score           DOUBLE,
    signal_field    VARCHAR,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 回测运行
CREATE TABLE IF NOT EXISTS backtest_run (
    run_id          VARCHAR PRIMARY KEY,
    strategy_name   VARCHAR,
    strategy_params JSON,
    start_date      DATE,  end_date DATE,
    universe        VARCHAR,  benchmark VARCHAR,
    initial_capital DOUBLE,
    status          VARCHAR,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at    TIMESTAMP
);

-- 回测交易
CREATE TABLE IF NOT EXISTS backtest_trades (
    id          INTEGER  NOT NULL,
    run_id      VARCHAR  NOT NULL,
    datetime    TIMESTAMP,
    code        VARCHAR,  name VARCHAR,
    action      VARCHAR,  price DOUBLE,
    size        INTEGER,  amount DOUBLE,
    commission  DOUBLE,
    industry    VARCHAR,
    market_cap_group VARCHAR,
    PRIMARY KEY (run_id, id)
);

-- 回测绩效
CREATE TABLE IF NOT EXISTS backtest_performance (
    run_id              VARCHAR PRIMARY KEY,
    total_return        DOUBLE,  annual_return DOUBLE,
    max_drawdown        DOUBLE,  sharpe_ratio DOUBLE,
    win_rate            DOUBLE,  total_trades INTEGER,
    avg_holding_days    DOUBLE,
    industry_analysis   JSON,
    cap_group_analysis  JSON,
    monthly_returns     JSON
);

-- 回测每日净值
CREATE TABLE IF NOT EXISTS backtest_daily_pnl (
    run_id      VARCHAR NOT NULL,
    date        DATE    NOT NULL,
    pnl         DOUBLE,  pnl_pct DOUBLE,
    total_value DOUBLE,  positions JSON,
    PRIMARY KEY (run_id, date)
);

-- 持仓
CREATE TABLE IF NOT EXISTS positions (
    id              SERIAL PRIMARY KEY,
    code            VARCHAR NOT NULL,  name VARCHAR,
    strategy        VARCHAR,
    signal_date     DATE,  buy_date DATE,
    shares          INTEGER,  buy_price DOUBLE,
    buy_change_pct  DOUBLE,
    buy_score_b1    DOUBLE,  buy_score_b2 DOUBLE,
    buy_dif         DOUBLE,  buy_j_value DOUBLE,
    current_price   DOUBLE,
    current_score_s1 DOUBLE,
    stop_loss_pct   DOUBLE DEFAULT 0.03,
    status          VARCHAR DEFAULT 'holding',
    sell_date       DATE,  sell_price DOUBLE,
    sell_reason     VARCHAR,
    profit_loss     DOUBLE,  profit_pct DOUBLE,
    notes           VARCHAR,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 每日投资组合净值
CREATE TABLE IF NOT EXISTS portfolio_daily (
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

-- 策略注册表
CREATE TABLE IF NOT EXISTS strategy_registry (
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

-- Agent 分析结果
CREATE TABLE IF NOT EXISTS agent_analysis_results (
    run_id      VARCHAR NOT NULL,
    symbol      VARCHAR,
    trade_date  VARCHAR,
    result_json JSON,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 流水线管理
CREATE TABLE IF NOT EXISTS data_pipeline_run (
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

CREATE TABLE IF NOT EXISTS step_update_log (
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
```

## 四、执行路线

```
Phase 1: 建表 + 移植信号层 (今天)
  ├─ 在 xy_quant DuckDB 中创建 daily_signals 等新表
  ├─ 移植 signals/ 全部模块
  ├─ 去硬编码、接 config.settings
  └─ 验证: 能对单只股票跑 signal scan
            ↓

Phase 2: 移植回测 + 策略 (1-2天)
  ├─ 移植 backtest/ engine + batch + multi_dimension
  ├─ 移植 strategies/ registry + base
  ├─ 接 data.api 取数据
  └─ 验证: 能跑通 B1 策略回测
            ↓

Phase 3: 移植交易层 + Agent + Web (1-2天)
  ├─ 移植 trading/ portfolio + audit
  ├─ 移植 agent/ 全目录
  ├─ 移植 web/ Flask + API
  └─ 验证: Dashboard 可访问、Agent 可分析
            ↓

Phase 4: 端到端打通 + 复盘集成 (1天)
  ├─ 全流水线: data → signals → backtest → review
  ├─ 调度脚本补全
  └─ 验证: 一天数据从入库到复盘报告全自动
```

## 五、核心原则

1. **所有硬编码路径 → `config.settings`**
2. **所有 SQL → `data.api` 统一入口**
3. **所有 import → 相对路径 (`from signals.signal_cal import ...`)**
4. **表名不做迁移**，xy_quant 保持 `daily_bar` 等原名
5. **每移植一个模块就测试**，不通不继续
6. **保持 xy_quant 已有的 ruff/mypy/pytest 门禁**

---

现在要开始执行 Phase 1 吗？从建表和移植信号层开始。
