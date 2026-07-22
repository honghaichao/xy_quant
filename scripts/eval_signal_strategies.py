#!/usr/bin/env python3
"""
信号策略历史批量评估 — 基于 signal_events 全部买入事件的事件驱动回测。

与 run_backtest.py 的单信号日模式不同，本脚本扫描历史上所有信号日：
每个买入事件在 T+1 开盘买入、持有 hold_days 个交易日后在开盘卖出，
计算净收益（含双边费用），按策略汇总胜率/均值/分月表现，并对比同窗口上证指数。

用法：
    .venv/bin/python scripts/eval_signal_strategies.py
    .venv/bin/python scripts/eval_signal_strategies.py --start 2026-03-17 --end 2026-07-17
    .venv/bin/python scripts/eval_signal_strategies.py --strategies B1,B2,BLK
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import duckdb
import pandas as pd

from config.settings import settings
from utils.logger import get_logger

logger = get_logger("eval_signal_strategies")

DB_PATH = str(Path(settings.duckdb_path))

# 与 scripts/run_backtest.py STRATEGIES 保持一致的持有期
HOLD_DAYS = {"B1": 5, "B2": 5, "BLK": 3, "BLKB2": 5, "SCB": 5, "DZ30": 3}

BUY_FEE = 1.0003   # 买入含佣金
SELL_FEE = 0.9987  # 卖出含佣金+印花税


def _to_ts_code(code_expr: str) -> str:
    """SQL 表达式：6 位代码 → ts_code 后缀格式"""
    return f"""
        CASE
            WHEN {code_expr} LIKE '6%' OR {code_expr} LIKE '9%' OR {code_expr} LIKE '5%'
                THEN {code_expr} || '.SH'
            WHEN {code_expr} LIKE '4%' OR {code_expr} LIKE '8%'
                THEN {code_expr} || '.BJ'
            ELSE {code_expr} || '.SZ'
        END
    """


def evaluate(start: str, end: str, strategies: list[str]) -> pd.DataFrame:
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        frames = []
        for abbr in strategies:
            hd = HOLD_DAYS[abbr]
            # 每个事件：T+1 开盘买入，再过 hd 个交易日开盘卖出
            df = conn.execute(f"""
                WITH events AS (
                    SELECT date, code, {_to_ts_code('code')} AS ts_code
                    FROM signal_events
                    WHERE signal_abbrev = ? AND signal_type = 'buy'
                      AND date BETWEEN ? AND ?
                ),
                bars AS (
                    SELECT ts_code, trade_date,
                           LEAD(open, 1)      OVER w AS entry_open,
                           LEAD(open, 1 + {hd}) OVER w AS exit_open
                    FROM daily_bar
                    WHERE ts_code IN (SELECT DISTINCT ts_code FROM events)
                      AND trade_date >= CAST(? AS DATE) - INTERVAL 10 DAY
                    WINDOW w AS (PARTITION BY ts_code ORDER BY trade_date)
                ),
                idx AS (
                    SELECT trade_date,
                           LEAD(open, 1)      OVER (ORDER BY trade_date) AS entry_open,
                           LEAD(open, 1 + {hd}) OVER (ORDER BY trade_date) AS exit_open
                    FROM index_daily WHERE ts_code = '000001.SH'
                )
                SELECT e.date, e.code,
                       b.exit_open / b.entry_open * {SELL_FEE} / {BUY_FEE} - 1 AS ret,
                       i.exit_open / i.entry_open - 1                           AS idx_ret
                FROM events e
                JOIN bars b ON b.ts_code = e.ts_code AND b.trade_date = e.date
                JOIN idx  i ON i.trade_date = e.date
                WHERE b.entry_open IS NOT NULL AND b.exit_open IS NOT NULL
                  AND i.entry_open IS NOT NULL AND i.exit_open IS NOT NULL
            """, [abbr, start, end, start]).fetchdf()
            if df.empty:
                logger.warning(f"{abbr}: 区间内无可评估事件")
                continue
            df["strategy"] = abbr
            df["excess"] = df["ret"] - df["idx_ret"]
            frames.append(df)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    finally:
        conn.close()


def summarize(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for abbr, g in trades.groupby("strategy"):
        rows.append({
            "策略": abbr,
            "持有天数": HOLD_DAYS[abbr],
            "事件数": len(g),
            "信号日数": g["date"].nunique(),
            "胜率%": round((g["ret"] > 0).mean() * 100, 1),
            "均收益%": round(g["ret"].mean() * 100, 3),
            "中位%": round(g["ret"].median() * 100, 3),
            "均超额%": round(g["excess"].mean() * 100, 3),
            "超额胜率%": round((g["excess"] > 0).mean() * 100, 1),
            "最大单笔%": round(g["ret"].max() * 100, 2),
            "最小单笔%": round(g["ret"].min() * 100, 2),
        })
    return pd.DataFrame(rows).sort_values("均超额%", ascending=False)


def monthly_table(trades: pd.DataFrame) -> pd.DataFrame:
    t = trades.copy()
    t["month"] = pd.to_datetime(t["date"]).dt.strftime("%Y-%m")
    pivot = t.pivot_table(index="month", columns="strategy", values="ret",
                          aggfunc="mean") * 100
    return pivot.round(3)


def main() -> int:
    parser = argparse.ArgumentParser(description="信号策略历史批量评估")
    parser.add_argument("--start", default="2026-01-01")
    parser.add_argument("--end", default="2026-12-31")
    parser.add_argument("--strategies", default="B1,B2,BLK,BLKB2,SCB,DZ30")
    parser.add_argument("--out", default=None, help="报告输出路径（默认 reports/signal_eval_<start>_<end>.txt）")
    args = parser.parse_args()

    strategies = [s.strip().upper() for s in args.strategies.split(",") if s.strip()]
    unknown = [s for s in strategies if s not in HOLD_DAYS]
    if unknown:
        parser.error(f"未知策略: {unknown}，可选 {list(HOLD_DAYS)}")

    logger.info(f"评估区间 {args.start} ~ {args.end}，策略 {strategies}")
    trades = evaluate(args.start, args.end, strategies)
    if trades.empty:
        logger.error("区间内无任何可评估事件")
        return 1

    summary = summarize(trades)
    monthly = monthly_table(trades)

    lines = [
        "=" * 78,
        f"  信号策略历史批量评估  {args.start} ~ {args.end}",
        f"  规则：信号日 T+1 开盘买入，持有 hold_days 交易日后开盘卖出（含双边费用）",
        f"  基准：上证指数 000001.SH 同窗口收益",
        "=" * 78,
        "",
        summary.to_string(index=False),
        "",
        "-" * 78,
        "  分月平均单笔收益 %（按信号月）",
        "-" * 78,
        monthly.to_string(),
        "",
    ]
    report = "\n".join(lines)
    print(report)

    out = args.out or str(PROJECT_ROOT / "reports" / f"signal_eval_{args.start}_{args.end}.txt")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(report, encoding="utf-8")
    trades_csv = out.replace(".txt", "_trades.csv")
    trades.to_csv(trades_csv, index=False)
    logger.info(f"报告: {out}")
    logger.info(f"明细: {trades_csv} ({len(trades)} 笔)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
