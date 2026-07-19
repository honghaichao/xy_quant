# xy_quant — 完成状态与后续路线图

> 2026-07-14 | 从 SilverM 完成整合

## 整合成果 (1753 files)

| 模块 | 状态 | 说明 |
|---|---|---|
| 数据层 | ✅ | daily_bar 777万行, 分钟线16.9亿行, 17张新表 |
| 信号层 | ✅ | 7策略全市场扫描, 5,493只股票信号 |
| 回测引擎 | ✅ | Backtrader封装, 代码移植完成 |
| 策略注册表 | ✅ | Registry + BaseStrategy |
| Agent | ✅ | 33 .py, DeepSeek/MiniMax |
| Web Dashboard | ✅ | Flask 35路由, Vue前端 |
| 交易层 | ✅ | portfolio模块 |
| 复盘报告 | ✅ | HTML+PNG输出 |

## 当前能力 vs 成熟标准

### 已有 ✅ (12/33 = 36%)
- 日线/分钟线/财务/资金流全量数据，每日自动补数
- 7策略买卖信号，全市场22分钟扫描
- HTML+PNG每日复盘

### 部分可用 🔶 (10/33 = 30%)
- 回测代码存在但**从未实际跑过**
- 持仓/净值/交易审计表全空
- signal_events/strategy_registry 表空

### 完全缺失 ⬜ (11/33 = 33%)
- 历史信号回溯(只有2026-07-14一天)
- 自动信号推送(飞书/钉钉)
- 独立风控模块
- 因子引擎 (factor_*表空)
- 实盘交易网关

## 路线图

### Phase A: 跑通回测流水线 (1-2天) ← 下一步
1. 扫描历史信号(2024-2026, 给回测提供数据)
2. B1策略完整回测, 结果入库 backtest_*
3. 验证收益率/夏普/最大回撤计算正确

### Phase B: 持仓+净值+通知 (1-2天)
1. 从信号生成模拟持仓
2. 每日净值流水线
3. 飞书自动推送信号摘要

### Phase C: 风控+策略管理 (1-2天)
1. 独立风控规则引擎
2. 策略注册表填充
3. 回测对比+版本管理

### Phase D: 因子+实盘 (长期)
1. 因子引擎
2. 仿真交易
3. QMT实盘

## 当前核心命令

```bash
cd /Volumes/quant-ssd/projects/xy_quant

# 每日补数
PYTHONPATH=$PWD TUSHARE_TOKEN=xxx .venv/bin/python scripts/backfill_day.py --trade-date YYYY-MM-DD

# 信号扫描
PYTHONPATH=$PWD .venv/bin/python scripts/run_signal_scan.py --date YYYYMMDD

# Dashboard
PYTHONPATH=$PWD .venv/bin/python web/app.py  # → http://localhost:5004
```
