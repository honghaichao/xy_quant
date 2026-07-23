# xy_quant 量化交易系统

> 最后更新：2026-07-23 22:00
> 项目路径：/Volumes/quant-ssd/projects/xy_quant
> Python 环境：.venv/bin/python (3.14)
> 数据库：DuckDB (data_store/market.duckdb) + PostgreSQL (Docker quant_postgres:55432)

---

## 一、系统概况

个人 A 股量化交易系统，整合自 SilverM-quant（策略信号/回测/Agent/Dashboard）和 xy_quant（数据基础设施/复盘）。

**核心定位**：数据驱动 → 信号扫描 → 回测验证 → 复盘分析 → 交易决策

---

## 二、数据资产

### DuckDB 行情库（99 张表）

| 表 | 行数 | 覆盖范围 | 状态 |
|---|---|---|---|
| `daily_bar` | 777 万 | 2020-01-02 ~ 2026-07-16 | ✅ 完整 |
| `daily_basic` | 772 万 | 2020-01-02 ~ 2026-07-16 | ✅ 完整 |
| `adj_factor` | 790 万 | 2020-01-02 ~ 2026-07-16 | ✅ 完整 |
| `minute_bar` | 17.4 亿 | 2020-01-02 ~ 2026-07-15 (79 个月表) | ✅ 完整 |
| `index_daily` | 9,437 | 1990-12 ~ 2026-07-16 | ✅ 完整 |
| `limit_list` | 120,105 | 2020-01 ~ 2026-07-16 | ✅ 完整 |
| `daily_signals` | 43.1 万 | 2026-03-17 ~ 2026-07-16 (80 天) | ✅ 每日自动 |
| `signal_events` | 31.1 万 | 2026-03-17 ~ 2026-07-16 | ✅ 每日自动 |
| `factor_data` | 42.6 万 | 2026-03-17 ~ 2026-07-16 | ✅ 每日自动 |
| `backtest_run` | 8 | 2025-07-14 ~ 2026-07-14 | 🟡 B1 回测 7 只 |
| `backtest_performance` | 8 | 2025-07-14 ~ 2026-07-14 | 🟡 B1 回测 |
| `backtest_trades` | 3,219 | 2025-07-14 ~ 2026-07-14 | 🟡 有数据 |
| `backtest_daily_pnl` | 1,770 | 2025-07-14 ~ 2026-07-14 | 🟡 有数据 |
| `strategy_registry` | 8 | — | ✅ 8 策略已注册 |
| `positions` | 10 | 2026-07-14 | ✅ 信号→建仓自动 |
| `portfolio_daily` | 0 | — | 🔴 待填充 |
| `agent_analysis_results` | 16 | 2026-07-20 | 🟡 AI 分析结果已接入建仓和飞书通知 |

### PostgreSQL 元数据库（Docker 容器）

- `stock_basic` 5,541 只 · `trade_calendar` 到 2026-12-31
- 财务三表 (135K+) · 资金流 · 龙虎榜 · 北向资金等 22 张表
- `data_update_log` 13 行（调度器写入正常）

---

## 三、模块清单

| 模块 | 状态 | 说明 |
|---|---|---|
| **data/** | ✅ 完整 | 数据源适配器 (Tushare/AKShare) + 存储层 (DuckDB/PG/Redis) + 更新层 + 校验 + 统一 API |
| **config/** | ✅ 完整 | pydantic-settings 配置系统 + settings.yaml + scheduler_jobs.yaml + review_rules.yaml |
| **utils/** | ✅ 完整 | logger / rate_limiter / retry / exception / calendar / feishu_image |
| **signals/** | ✅ 完整 | 7 策略信号: B1/B2/BLK/BLKB2/SCB/DZ30 + S1 卖出, 全市场 22min |
| **backtest/** | 🟡 已验证 | Backtrader 引擎 + B1 回测脚本, 7 只股票回测已跑 |
| **strategies/** | ✅ 就位 | 策略注册表 (已接入 DuckDB) + BaseStrategy + PortfolioStrategy 基类 + JQ 引擎 (聚宽格式) + LightGBM 滚动训练 |
| **agent/** | 🟡 代码就位 | 49 .py 多 Agent 辩论系统 (DeepSeek/MiniMax), 从未端到端验证 |
| **web/** | 🟡 代码就位 | Flask 35 路由 + Vue 3 Dashboard, 前端 dist 完整 |
| **trading/** | ✅ 就位 | 持仓管理 + 每日净值, positions 脚本已接入调度器 |
| **review/** | ✅ 完整 | 每日 HTML+PNG 复盘报告 (collector/analyzer/narrative/renderer) |
| **scripts/** | ✅ 完整 | 60+ 脚本 (全量/增量/补数/信号/回测/调度/事件) |
| **tools/** | ✅ 就位 | visualization/charts.py ChartPlotter |
| **factor/** | 🔴 骨架 | 仅 `__init__.py` |
| **risk/** | 🔴 骨架 | 仅 `__init__.py` |
| **gateway/** | 🔴 骨架 | 仅 `__init__.py`, QMT 未实现 |
| **live/** | 🔴 骨架 | 仅 `__init__.py` |

---

## 四、定时调度

### 本地调度器（APScheduler 常驻后台, PID 73353）

| 时间 | 任务 | 频率 |
|---|---|---|
| 20:30 | backfill_day (日线+基本指标) | 周一~五 |
| 20:45 | backfill_day (涨停板+资金流) | 周一~五 |
| 21:00 | backfill_day (龙虎榜 T+1) | 周一~五 |
| 22:07 | batch_scan (全市场信号扫描) | 周一~五 |
| 22:17 | populate_signal_events (信号→事件) | 周一~五 |
| 22:30 | factor_compute (因子计算) | 周一~五 |
| 22:35 | auto_factor_mine (因子自动挖掘) | 周一~五 |
| 22:45 | risk_check (风险检查) | 周一~五 |
| 22:50 | feishu_notify (飞书卡片推送) | 周一~五 |
| 22:55 | build_positions (信号→持仓建仓) | 周一~五 |
| 08:07 | backfill_day (周度更新) | 周日 |

管理：`pkill -f run_scheduler` 停止 · `tail -f logs/scheduler.log` 查看

### cc-connect 定时（远程触发, 3 条）

| ID | 时间 | 任务 |
|---|---|---|
| e88c54c0 | 一~五 17:37 | 补数+扫描+事件 |
| 7c12e968 | 一~五 22:07 | 信号事件填充 |
| ea47fd45 | 周日 08:07 | 周更 |

---

## 五、关键命令

```bash
cd /Volumes/quant-ssd/projects/xy_quant
export PYTHONPATH=$PWD

# === 数据运维 ===
.venv/bin/python scripts/backfill_day.py --trade-date 2026-07-14           # 单日补数
.venv/bin/python scripts/backfill_history.py --start 2026-07-01 --end 2026-07-14 --resume  # 范围补数
.venv/bin/python scripts/full_load_minute_bar.py --missing-only --batch-run --start 2026-05-06 --end 2026-07-14  # 分钟线补全

# === 信号扫描 ===
.venv/bin/python scripts/batch_scan.py --date 20260714                      # 批量版（22min）
.venv/bin/python scripts/run_signal_scan.py --date 20260714 --limit 100     # 单股版
.venv/bin/python scripts/populate_signal_events.py                          # 信号→事件

# === 回测 ===
.venv/bin/python scripts/run_backtest_b1.py                                 # B1 策略批量回测
.venv/bin/python scripts/run_backtest_b1.py --dry-run                       # 预览
.venv/bin/python scripts/run_backtest.py --strategy caimadama_jq --start 20260101 --end 20260717  # JQ 引擎回测（聚宽格式策略）
.venv/bin/python scripts/run_backtest.py --strategy lightgbm_small_cap --start 20260101 --end 20260717  # LightGBM 滚动训练回测

# === 调度器 ===
.venv/bin/python scripts/run_scheduler.py --list                            # 查看任务
.venv/bin/python scripts/run_scheduler.py --run-now backfill_day            # 手动触发
nohup .venv/bin/python scripts/run_scheduler.py > logs/scheduler.log 2>&1 & # 后台启动

# === 复盘 ===
.venv/bin/python scripts/run_review.py                                      # 生成当日复盘

# === Dashboard ===
.venv/bin/python web/app.py                                                 # → http://localhost:5004

# === 数据快照 ===
.venv/bin/python -c "
import duckdb
c=duckdb.connect('data_store/market.duckdb',read_only=1)
for t in ['daily_bar','daily_basic','adj_factor','minute_bar','daily_signals','signal_events']:
    r=c.execute(f'SELECT MIN(trade_date) FROM {t}').fetchone() if t!='minute_bar' else c.execute('SELECT MIN(datetime),MAX(datetime) FROM minute_bar').fetchone()
    print(f'{t:20s} {r}')
c.close()
"
```

---

## 六、已落地 vs 待补齐 (2026-07-14 更新)

### 已完成 ✅

- 日线/分钟线/财务数据完整到 2026-07-14
- 7 策略全市场信号扫描可用
- signal_events 填充脚本可用
- `lightgbm_small_cap.py` LightGBM 滚动训练多因子策略（双平台：xy_quant 本地 + 聚宽原版）
- caimadama_jq JQ 引擎回测平价验证通过（持仓 0 差异、期末权益 0.000% 偏差）
- B1 策略回测已验证（7 只股票, backtest_run/performance 有数据）
- 策略注册表 8 策略已入库
- APScheduler 本地调度器已启动, 6 个 cron job
- cc-connect 3 条定时任务
- P0 阻塞修复完成（strategy base 类、registry DB 依赖、visualization 路径、baostock）

### 代码存在但端到端未验证 🟡

- 回测引擎 Backtrader 封装 (engine.py)：B1 用向量化跑通了，Backtrader 版没跑
- Agent 分析系统 (49 .py)：DeepSeek/MiniMax 适配器就位，从未实际调用
- Web Dashboard：Flask 可启动，前端 dist 缺失、多页面依赖空表
- 交易层持仓/净值为空

### 完全未开始 🔴

- 因子引擎 (factor/)：P3, 0 个因子
- 风控引擎 (risk/)：P4, 无独立风控模块
- 实盘网关 (gateway/)：P6, QMT/CTP 未实现
- 通知推送：无钉钉/飞书自动通知
- 历史数据缺失：daily_signals 仅 2 天，signal_events 同上
- `multi_factor_strategy.py` 从 SilverM 搬来但未适配方向

---

## 七、环境信息

| 项目 | 值 |
|---|---|
| 项目路径 | /Volumes/quant-ssd/projects/xy_quant |
| Python | 3.14 (.venv/bin/python) |
| DuckDB 数据文件 | data_store/market.duckdb |
| PostgreSQL | Docker quant_postgres:55432 |
| Docker 管理 | docker compose -f deploy/docker-compose.yml up -d |
| Tushare Token | 2000 积分 |
| Web Dashboard | port 5004 |
| 调度器进程 | PID 73353 (APScheduler) |

---

## 八、后续路线

### 高优先级（本周）
1. **历史信号扫描**：从 2020 年开始逐日扫描，填充 daily_signals 历史
2. **多策略回测**：B2/BLK/SCB/DZ30 策略批量回测
3. **Backtrader 引擎端到端验证**：用 B1 策略跑一遍真实 engine.py

### 中优先级（本月）
4. **Dashboard 可访问**：修复前端 dist，填充关键表数据
5. **Agent 端到端验证**：用 DeepSeek 跑一次单股分析
6. **通知推送**：飞书/钉钉 Webhook 实现

### 低优先级（下个 Phase）
7. **因子引擎**：P3 从 0 建设
8. **风控引擎**：独立风控模块
9. **实盘网关**：QMT 对接
