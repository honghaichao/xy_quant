#!/usr/bin/env python3
"""
统一回测入口 — 一个脚本跑所有策略。

用法：
    # 菜场大妈选股法（全市场组合策略）
    .venv/bin/python scripts/run_backtest.py --strategy caimadama \\
        --start 20250101 --end 20260714 --top-n 5 --initial-cash 500000

    # 信号策略（B1/B2/BLK/...）
    .venv/bin/python scripts/run_backtest.py --strategy b1 \\
        --signal-date 20260714 --stock-count 20

    # 全部策略
    .venv/bin/python scripts/run_backtest.py --strategy all \\
        --signal-date 20260714

    # 只生成报告不存数据库
    .venv/bin/python scripts/run_backtest.py --strategy caimadama \\
        --start 20250101 --end 20260714 --no-save-db

输出（每个策略一个子目录，在 reports/<strategy_name>_<timestamp>/）：
    trades.csv              — 交易记录（中文：日期,代码,名称,方向,价格,数量,金额,佣金,盈亏,盈亏%）
    daily_positions.csv     — 每日持仓（中文：日期,持仓代码,持仓数）
    report_summary.txt      — 完整中文汇总报告
    equity_curve.png         — 权益曲线 + 回撤子图
    metrics_dashboard.png   — KPI 瓦片 + 月度收益热力图
    trade_pnl_dist.png      — 交易盈亏分布图
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import duckdb
import pandas as pd

from config.settings import settings
from utils.logger import get_logger

from backtest.runner import BacktestRunner
from backtest.reporter import generate_all_reports
from backtest.execution import load_benchmark, load_name_map

logger = get_logger("run_backtest")

DB_PATH = str(PROJECT_ROOT / "data_store" / "market.duckdb")

# ═══════════════════════════════════════════════════════════════
# 策略注册表
# ═══════════════════════════════════════════════════════════════

STRATEGIES: dict[str, dict] = {
    "caimadama": {
        "type": "portfolio",
        "display": "菜场大妈选股法",
        "description": "高股息+小市值，等权每日调仓",
    },
    "caimadama_jq": {
        "type": "jq",
        "display": "菜场大妈(JQ引擎)",
        "module": "strategies.jq.caimadama",
    },
    "factor_value": {
        "type": "jq",
        "display": "因子增强选股(JQ引擎)",
        "module": "strategies.jq.factor_value",
    },
    "lightgbm_small_cap": {
        "type": "jq",
        "display": "LightGBM多因子小市值",
        "module": "strategies.jq.lightgbm_small_cap",
    },
    "b1": {
        "type": "signal",
        "display": "天宫B1策略v1",
        "key": "B1",
        "hold_days": 5,
        "score_col": "score_b1",
    },
    "b2": {
        "type": "signal",
        "display": "天宫B2策略v1",
        "key": "B2",
        "hold_days": 5,
        "score_col": "score_b2",
    },
    "blk": {
        "type": "signal",
        "display": "暴力K策略v1",
        "key": "BLK",
        "hold_days": 3,
        "score_col": "score_blk",
    },
    "blkb2": {
        "type": "signal",
        "display": "暴力K+B2策略v1",
        "key": "BLKB2",
        "hold_days": 5,
        "score_col": "score_blkB2",
    },
    "scb": {
        "type": "signal",
        "display": "沙尘暴策略v1",
        "key": "SCB",
        "hold_days": 5,
        "score_col": "score_scb",
    },
    "dz30": {
        "type": "signal",
        "display": "单针30策略v1",
        "key": "DZ30",
        "hold_days": 3,
        "score_col": "score_dz30",
    },
}
ALL_STRATEGY_KEYS = [k for k in STRATEGIES if k != "all"]
SIGNAL_STRATEGIES = [k for k, v in STRATEGIES.items() if v.get("type") == "signal"]
PORTFOLIO_STRATEGIES = [k for k, v in STRATEGIES.items() if v.get("type") == "portfolio"]


def _code_to_ts_code(code: str) -> str:
    code = code.strip()
    if "." in code:
        return code
    if code.startswith(("688", "600", "601", "603", "605")):
        return f"{code}.SH"
    if code.startswith(("920",)):
        return f"{code}.BJ"
    return f"{code}.SZ"


# ═══════════════════════════════════════════════════════════════
# 信号策略
# ═══════════════════════════════════════════════════════════════

def run_signal_strategy(
    strategy_key: str,
    signal_date: date,
    stock_count: int = 0,
    start_date: date | None = None,
    end_date: date | None = None,
    hold_days: int | None = None,
    initial_cash: float = 100_000.0,
    **kwargs,
) -> dict:
    """运行信号型策略（B1/B2/BLK 等）— 简化向量化回测"""
    cfg = STRATEGIES[strategy_key]
    key = cfg["key"]
    hd = hold_days if hold_days is not None else cfg["hold_days"]
    score_col = cfg["score_col"]
    sig_col = f"signal_buy_{key.lower()}"

    if start_date is None:
        start_date = signal_date - timedelta(days=365)
    if end_date is None:
        end_date = signal_date

    # 读取信号
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        signals = conn.execute(f"""
            SELECT code, name, {score_col} AS score, close
            FROM daily_signals
            WHERE "date" = ? AND "{sig_col}" = true
            ORDER BY score DESC
        """, [signal_date.isoformat()]).fetchdf()
    finally:
        conn.close()

    if stock_count > 0:
        signals = signals.head(stock_count)

    codes = signals["code"].tolist()
    if not codes:
        return {"error": f"{strategy_key}: 无信号"}

    # 加载价格数据
    ts_codes = [_code_to_ts_code(c) for c in codes]
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        df = conn.execute(f"""
            SELECT trade_date, ts_code, open, high, low, close, vol
            FROM daily_bar
            WHERE ts_code IN ({','.join(['?' for _ in ts_codes])})
              AND trade_date >= ? AND trade_date <= ?
            ORDER BY trade_date
        """, ts_codes + [start_date.isoformat(), end_date.isoformat()]).fetchdf()
    finally:
        conn.close()

    if df.empty:
        return {"error": f"{strategy_key}: 无价格数据"}

    df["code"] = df["ts_code"].str[:6]

    name_map = load_name_map()
    cash = initial_cash
    position = 0
    buy_price = 0.0
    trades: list[dict] = []
    equity_curve: list[dict] = []

    for code in codes:
        code_df = df[df["code"] == code].sort_values("trade_date").reset_index(drop=True)
        if len(code_df) < max(20, hd * 2):
            continue
        code_df["trade_date"] = pd.to_datetime(code_df["trade_date"])
        idx = 0
        while idx < len(code_df):
            row = code_df.iloc[idx]
            cur_date = row["trade_date"]
            cur_close = float(row["close"])
            if position > 0 and idx + hd < len(code_df):
                sell_price = float(code_df.iloc[idx + hd]["open"])
                sell_value = position * sell_price * 0.9987
                pnl = sell_value - (position * buy_price)
                pnl_pct = (pnl / (position * buy_price) * 100) if position and buy_price else 0
                trades.append({
                    "date": code_df.iloc[idx + hd]["trade_date"].to_pydatetime().date(),
                    "code": code, "name": name_map.get(code, code),
                    "action": "卖出", "price": round(sell_price, 3),
                    "shares": position, "amount": round(sell_value, 2),
                    "commission": round(position * sell_price * 0.0013, 2),
                    "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
                })
                cash += sell_value
                position = 0
            if position == 0 and idx + hd < len(code_df):
                buy_price = float(code_df.iloc[idx]["open"])
                size = int((cash * 0.9997) / buy_price / 100) * 100
                if size >= 100:
                    cost = size * buy_price * 1.0003
                    cash -= cost
                    position = size
                    trades.append({
                        "date": cur_date.to_pydatetime().date() if hasattr(cur_date, "to_pydatetime") else cur_date,
                        "code": code, "name": name_map.get(code, code),
                        "action": "买入", "price": round(buy_price, 3),
                        "shares": size, "amount": round(cost, 2),
                        "commission": round(size * buy_price * 0.0003, 2),
                        "pnl": 0.0, "pnl_pct": 0.0,
                    })
            total_value = cash + position * cur_close
            equity_curve.append({
                "date": cur_date.to_pydatetime().date() if hasattr(cur_date, "to_pydatetime") else cur_date,
                "total": total_value, "cash": cash, "position_value": position * cur_close,
                "total_return": total_value / initial_cash - 1, "positions": 1 if position > 0 else 0,
            })
            idx += 1
    if position > 0:
        cash += position * float(code_df.iloc[-1]["close"]) * 0.9987
    final_value = cash

    # 调用统一 metrics
    from backtest.metrics import compute_metrics
    m = compute_metrics(equity_curve, trades, initial_cash)

    return {
        "start": start_date.isoformat(), "end": end_date.isoformat(),
        "strategy_name": cfg["display"], "initial_cash": initial_cash,
        "final_value": round(final_value, 2), "metrics": m,
        "trades": trades, "equity_curve": equity_curve,
        "daily_positions": [],  # 信号策略不追踪每日持仓
    }


# ═══════════════════════════════════════════════════════════════
# 组合策略
# ═══════════════════════════════════════════════════════════════

def run_jq_strategy(
    strategy_key: str,
    start: date,
    end: date,
    initial_cash: float = 500_000.0,
    parity_mode: bool = False,
    **kwargs,
) -> dict:
    """运行 JQ 引擎策略（聚宽格式策略文件）"""
    from engine.backtest_engine import BacktestEngine

    cfg = STRATEGIES[strategy_key]
    eng = BacktestEngine(
        strategy=cfg["module"],
        start=start,
        end=end,
        initial_cash=initial_cash,
        strategy_name=cfg["display"],
        run_params={"parity_mode": parity_mode,
                    "div_ref_date": end if parity_mode else None},
        bootstrap_first_day=parity_mode,
    )
    return eng.run()


def run_portfolio_strategy(
    strategy_key: str,
    start: date,
    end: date,
    top_n: int = 5,
    initial_cash: float = 500_000.0,
    **kwargs,
) -> dict:
    """运行组合策略（菜场大妈等）"""
    if strategy_key == "caimadama":
        from strategies.caimadama import CaiMaDamaStrategy
        strategy = CaiMaDamaStrategy(top_n=top_n)
    else:
        raise ValueError(f"未知组合策略: {strategy_key}")

    strategy.load_context_data(start, end)
    runner = BacktestRunner(strategy, start=start, end=end, initial_cash=initial_cash)
    return runner.run()


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

def run_backtest(
    strategy: str = "caimadama",
    signal_date: date | None = None,
    start: date | None = None,
    end: date | None = None,
    stock_count: int = 0,
    hold_days: int | None = None,
    top_n: int = 5,
    initial_cash: float = 500_000.0,
    report_dir: str | None = None,
    save_to_db: bool = True,
    parity_mode: bool = False,
) -> dict[str, dict]:
    """运行指定策略的回测并生成完整报告。

    Returns:
        {"<strategy_key>": result_dict, ...}
    """
    strategies_to_run = ALL_STRATEGY_KEYS if strategy == "all" else [strategy]

    if signal_date is None:
        conn = duckdb.connect(DB_PATH, read_only=True)
        try:
            row = conn.execute('SELECT "date" FROM daily_signals ORDER BY "date" DESC LIMIT 1').fetchone()
        finally:
            conn.close()
        signal_date = date.fromisoformat(str(row[0])) if row else date.today()

    if start is None:
        start = signal_date - timedelta(days=365)
    if end is None:
        end = signal_date

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    base_dir = report_dir or str(PROJECT_ROOT / "reports" / f"backtest_{timestamp}")
    os.makedirs(base_dir, exist_ok=True)

    all_results = {}

    for sk in strategies_to_run:
        cfg = STRATEGIES.get(sk)
        if cfg is None:
            logger.warning(f"未知策略: {sk}")
            continue

        logger.info(f"\n{'='*60}")
        logger.info(f"策略: {cfg['display']}")
        logger.info(f"{'='*60}")

        strat_type = cfg.get("type", "signal")
        strat_dir = os.path.join(base_dir, sk)

        try:
            if strat_type == "jq":
                result = run_jq_strategy(sk, start=start, end=end,
                                         initial_cash=initial_cash, parity_mode=parity_mode)
                strategy_params = {"module": cfg["module"], "parity_mode": parity_mode}
            elif strat_type == "portfolio":
                result = run_portfolio_strategy(sk, start=start, end=end,
                                                top_n=top_n, initial_cash=initial_cash)
                strategy_params = {"top_n": top_n}
            else:
                result = run_signal_strategy(sk, signal_date=signal_date, stock_count=stock_count,
                                            start_date=start, end_date=end, hold_days=hold_days,
                                            initial_cash=initial_cash)
                strategy_params = {"signal_date": signal_date.isoformat(), "stock_count": stock_count,
                                  "hold_days": hold_days or cfg.get("hold_days", 5)}

            if "error" in result:
                logger.warning(f"{sk}: {result['error']}")
                all_results[sk] = result
                continue

            # 加载基准
            benchmark_df = load_benchmark("000300.SH", start, end)

            # 统一报告输出
            run_id = generate_all_reports(
                result=result,
                strategy_name=cfg["display"],
                report_dir=strat_dir,
                benchmark_df=benchmark_df,
                save_db=save_to_db,
                strategy_params=strategy_params,
                start_dt=start,
                end_dt=end,
            )

            all_results[sk] = {**result, "run_id": run_id}

        except Exception:
            import traceback
            logger.exception(f"{sk} 回测失败")
            all_results[sk] = {"error": traceback.format_exc()}

    return all_results


def main():
    parser = argparse.ArgumentParser(
        description="统一回测入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  .venv/bin/python scripts/run_backtest.py --strategy caimadama --start 20250101 --end 20260714
  .venv/bin/python scripts/run_backtest.py --strategy b1 --signal-date 20260714
  .venv/bin/python scripts/run_backtest.py --strategy all --signal-date 20260714
  .venv/bin/python scripts/run_backtest.py --strategy caimadama --top-n 10
  .venv/bin/python scripts/run_backtest.py --strategy caimadama --no-save-db
        """,
    )
    parser.add_argument("--parity-mode", action="store_true",
                        help="平价验证模式：复刻旧 runner 首日口径并关闭盘中槽")
    parser.add_argument("--strategy", "-s", type=str, default="caimadama",
                       choices=["all"] + ALL_STRATEGY_KEYS,
                       help="策略名称")
    parser.add_argument("--start", type=str, default=None,
                       help="回测起始日期 YYYYMMDD（组合策略需要；信号策略默认 signal-date 前一年）")
    parser.add_argument("--end", type=str, default=None,
                       help="回测结束日期 YYYYMMDD（默认 signal-date 或今天）")
    parser.add_argument("--signal-date", type=str, default=None,
                       help="信号日期 YYYYMMDD（信号策略用）")
    parser.add_argument("--stock-count", type=int, default=0,
                       help="最多回测股票数（信号策略，0=全部）")
    parser.add_argument("--hold-days", type=int, default=None,
                       help="持仓天数（信号策略，默认策略自带值）")
    parser.add_argument("--top-n", type=int, default=5,
                       help="持仓数（组合策略）")
    parser.add_argument("--initial-cash", type=float, default=500_000.0,
                       help="初始资金")
    parser.add_argument("--report-dir", type=str, default=None,
                       help="报告输出目录")
    parser.add_argument("--no-save-db", action="store_true",
                       help="不保存到数据库")
    args = parser.parse_args()

    start_dt = datetime.strptime(args.start, "%Y%m%d").date() if args.start else None
    end_dt = datetime.strptime(args.end, "%Y%m%d").date() if args.end else None
    signal_dt = datetime.strptime(args.signal_date, "%Y%m%d").date() if args.signal_date else None

    results = run_backtest(
        strategy=args.strategy,
        parity_mode=args.parity_mode,
        signal_date=signal_dt,
        start=start_dt,
        end=end_dt,
        stock_count=args.stock_count,
        hold_days=args.hold_days,
        top_n=args.top_n,
        initial_cash=args.initial_cash,
        report_dir=args.report_dir,
        save_to_db=not args.no_save_db,
    )

    # 终端输出摘要
    for sk, r in results.items():
        if "error" in r:
            print(f"\n{sk}: ❌ {r['error']}")
        else:
            m = r.get("metrics", {})
            print(f"\n{sk}: ✅ 收益率={m.get('total_return', 0)*100:+.2f}%  "
                  f"夏普={m.get('sharpe_ratio', 0):.2f}  回撤={m.get('max_drawdown', 0)*100:.2f}%  "
                  f"胜率={m.get('win_rate', 0)*100:.1f}%")

    return 0


if __name__ == "__main__":
    sys.exit(main())
