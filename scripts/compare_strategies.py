#!/usr/bin/env python3
"""Cross-strategy backtest comparison report.

Queries ``backtest_performance`` for the latest run of each strategy and
prints a side-by-side comparison table.

Usage:
    .venv/bin/python scripts/compare_strategies.py
    .venv/bin/python scripts/compare_strategies.py --format json
    .venv/bin/python scripts/compare_strategies.py --format csv --output strategy_report.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import csv
import json
import io
from datetime import date

import duckdb

from config.settings import settings

DB_PATH = str(Path(settings.duckdb_path))

COLUMN_LABELS: dict[str, str] = {
    "strategy_name":     "策略",
    "runs":              "回测数",
    "total_return":      "总收益%",
    "annual_return":     "年化收益%",
    "max_drawdown":      "最大回撤%",
    "sharpe_ratio":      "Sharpe",
    "sortino_ratio":     "Sortino",
    "calmar_ratio":      "Calmar",
    "win_rate":          "胜率%",
    "total_trades":      "交易次数",
    "avg_holding_days":  "持仓天数",
    "annual_volatility": "年化波动%",
}

ORDERED_COLS = [
    "strategy_name", "runs", "total_return", "annual_return", "max_drawdown",
    "sharpe_ratio", "sortino_ratio", "calmar_ratio", "annual_volatility",
    "win_rate", "total_trades", "avg_holding_days",
]


def _query_latest() -> list[dict]:
    """Return aggregated backtest results per strategy, using latest runs."""
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        # Get the most recent end_date per strategy (all run-ids grouped)
        rows = conn.execute("""
            WITH ranked AS (
                SELECT
                    bp.*,
                    br.strategy_name,
                    br.completed_at,
                    ROW_NUMBER() OVER (
                        PARTITION BY br.strategy_name
                        ORDER BY br.completed_at DESC
                    ) AS rn
                FROM backtest_performance bp
                JOIN backtest_run br USING (run_id)
            )
            SELECT
                strategy_name,
                COUNT(*)               AS runs,
                AVG(total_return)      AS total_return,
                AVG(annual_return)     AS annual_return,
                AVG(max_drawdown)      AS max_drawdown,
                AVG(sharpe_ratio)      AS sharpe_ratio,
                AVG(sortino_ratio)     AS sortino_ratio,
                AVG(calmar_ratio)      AS calmar_ratio,
                AVG(annual_volatility) AS annual_volatility,
                AVG(win_rate)          AS win_rate,
                SUM(total_trades)      AS total_trades,
                AVG(avg_holding_days)  AS avg_holding_days
            FROM ranked
            WHERE rn <= 20   -- top 20 latest runs per strategy
            GROUP BY strategy_name
            ORDER BY AVG(sharpe_ratio) DESC NULLS LAST
        """).fetchall()
    finally:
        conn.close()

    results: list[dict] = []
    for row in rows:
        d = dict(zip([
            "strategy_name", "runs", "total_return", "annual_return",
            "max_drawdown", "sharpe_ratio", "sortino_ratio", "calmar_ratio",
            "annual_volatility", "win_rate", "total_trades", "avg_holding_days",
        ], row))
        # Convert decimals to % where appropriate
        for k in ("total_return", "annual_return", "max_drawdown",
                  "win_rate", "annual_volatility"):
            if d.get(k) is not None:
                d[k] = round(float(d[k]) * 100, 2)
        for k in ("sharpe_ratio", "sortino_ratio", "calmar_ratio"):
            if d.get(k) is not None:
                d[k] = round(float(d[k]), 3)
        if d.get("avg_holding_days") is not None:
            d["avg_holding_days"] = round(float(d["avg_holding_days"]), 1)
        if d["runs"] is not None:
            d["runs"] = int(d["runs"])
        if d["total_trades"] is not None:
            d["total_trades"] = int(d["total_trades"])
        results.append(d)
    return results


def _format_table(results: list[dict]) -> str:
    """Pretty-print results as a text table."""
    if not results:
        return "No backtest data found.\n"

    header = [COLUMN_LABELS.get(c, c) for c in ORDERED_COLS if c in results[0]]
    widths = [len(h) for h in header]

    rows_str: list[list[str]] = []
    for r in results:
        row = []
        for c in ORDERED_COLS:
            if c not in r:
                continue
            v = r[c]
            if v is None:
                s = "-"
            elif isinstance(v, float):
                s = f"{v:,.2f}"
            else:
                s = str(v)
            row.append(s)
        rows_str.append(row)
        for i, s in enumerate(row):
            widths[i] = max(widths[i], len(s))

    buf = io.StringIO()
    sep = "  ".join(h.ljust(widths[i]) for i, h in enumerate(header))
    buf.write(sep + "\n")
    buf.write("-" * len(sep) + "\n")
    for row in rows_str:
        buf.write("  ".join(v.ljust(widths[i]) for i, v in enumerate(row)) + "\n")

    # Summary footer
    strategies = [r["strategy_name"] for r in results]
    top_sharpe = max(results, key=lambda r: r.get("sharpe_ratio") or -999)
    top_return = max(results, key=lambda r: r.get("total_return") or -999)
    buf.write(f"\n共 {len(strategies)} 个策略。")
    buf.write(f" 最高 Sharpe: {top_sharpe['strategy_name']} ({top_sharpe['sharpe_ratio']:.3f})。")
    buf.write(f" 最高收益: {top_return['strategy_name']} ({top_return['total_return']:.2f}%)。\n")
    return buf.getvalue()


def run(fmt: str = "table", output: str | None = None) -> dict:
    """Main entry point."""
    results = _query_latest()

    if fmt == "json":
        out = json.dumps(results, ensure_ascii=False, indent=2, default=str)
    elif fmt == "csv":
        buf = io.StringIO()
        if results:
            writer = csv.DictWriter(buf, fieldnames=list(results[0].keys()), extrasaction="ignore")
            writer.writeheader()
            writer.writerows(results)
        out = buf.getvalue()
    else:
        out = _format_table(results)

    if output:
        Path(output).write_text(out, encoding="utf-8")
        print(f"Saved to {output}")
    else:
        print(out)

    return {"strategies": len(results), "format": fmt}


def main() -> int:
    p = argparse.ArgumentParser(description="Cross-strategy backtest comparison")
    p.add_argument("--format", type=str, default="table",
                   choices=["table", "json", "csv"],
                   help="Output format (default: table)")
    p.add_argument("--output", "-o", type=str, default=None,
                   help="Write output to file")
    args = p.parse_args()

    try:
        run(fmt=args.format, output=args.output)
        return 0
    except Exception:
        import logging
        logging.getLogger(__name__).exception("compare_strategies failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
