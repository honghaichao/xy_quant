"""Today's industry fund flow — fetch from Tushare and save to DuckDB.

Usage:
    .venv/bin/python scripts/fetch_intraday_fundflow.py            # display only
    .venv/bin/python scripts/fetch_intraday_fundflow.py --save     # save to DuckDB
    .venv/bin/python scripts/fetch_intraday_fundflow.py --json     # JSON output for API
    .venv/bin/python scripts/fetch_intraday_fundflow.py --chart    # ASCII chart
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import json
from datetime import date, datetime

import duckdb
import pandas as pd

from config.settings import settings
from data.source.tushare_source import TushareSource
from utils.logger import get_logger

logger = get_logger("fetch_intraday_fundflow")
DB_PATH = str(Path(settings.duckdb_path))


def fetch_tushare_flow(trade_date: date | None = None) -> dict[str, pd.DataFrame]:
    """Fetch industry and concept fund flow from Tushare."""
    if trade_date is None:
        trade_date = date.today()

    source = TushareSource()
    result = {}

    try:
        df_ind = source.fetch_industry_money_flow(trade_date)
        if not df_ind.empty:
            result["industry"] = df_ind
            logger.info(f"Industry: {len(df_ind)} entries")
    except Exception as e:
        logger.error(f"Industry flow failed: {e}")

    try:
        df_con = source.fetch_concept_money_flow(trade_date)
        if not df_con.empty:
            result["concept"] = df_con
            logger.info(f"Concept: {len(df_con)} entries")
    except Exception as e:
        logger.error(f"Concept flow failed: {e}")

    return result


def display_top(df: pd.DataFrame, label: str, n: int = 10):
    """Display top/bottom sectors by main_inflow."""
    if df.empty:
        return

    top_in = df.nlargest(n, "main_inflow")
    print(f"\n=== {label} — TOP {n} 主力净流入 ===")
    print(f"{'名称':<20s} {'涨跌幅':>8s} {'主力净流入':>12s}")
    print("-" * 50)
    for _, r in top_in.iterrows():
        name = r.get("industry_name") or r.get("concept_name") or "?"
        print(
            f"{name:<20s} {r.get('pct_chg', 0):>+7.2f}% "
            f"{r.get('main_inflow', 0)/1e8:>+10.1f}亿"
        )

    top_out = df.nsmallest(n, "main_inflow")
    print(f"\n=== {label} — TOP {n} 主力净流出 ===")
    for _, r in top_out.iterrows():
        name = r.get("industry_name") or r.get("concept_name") or "?"
        print(
            f"{name:<20s} {r.get('pct_chg', 0):>+7.2f}% "
            f"{r.get('main_inflow', 0)/1e8:>+10.1f}亿"
        )


def display_chart(df: pd.DataFrame, label: str):
    """Simple ASCII bar chart of top inflows/outflows."""
    if df.empty:
        return

    top_in = df.nlargest(10, "main_inflow")
    top_out = df.nsmallest(10, "main_inflow")

    print(f"\n┌{'─'*50}┐")
    print(f"│ {label:^48s} │")
    print(f"├{'─'*50}┤")

    max_bar = max(
        abs(top_in.iloc[0]["main_inflow"]),
        abs(top_out.iloc[-1]["main_inflow"]),
        1,
    )
    bar_width = 30

    print("│ 🟢 流入 TOP 10" + " " * 35 + "│")
    for _, r in top_in.iterrows():
        name = (r.get("industry_name") or r.get("concept_name") or "?")[:12]
        inflow = r.get("main_inflow", 0) / 1e8
        bar_len = int(abs(inflow) / max_bar * bar_width)
        bar = "█" * bar_len
        print(
            f"│ {name:<12s} {r.get('pct_chg', 0):>+6.1f}% "
            f"{inflow:>+8.1f}亿 {bar:<{bar_width}} │"
        )

    print("│" + " " * 50 + "│")
    print("│ 🔴 流出 TOP 10" + " " * 35 + "│")
    for _, r in top_out.iterrows():
        name = (r.get("industry_name") or r.get("concept_name") or "?")[:12]
        outflow = r.get("main_inflow", 0) / 1e8
        bar_len = int(abs(outflow) / max_bar * bar_width)
        bar = "▓" * bar_len
        print(
            f"│ {name:<12s} {r.get('pct_chg', 0):>+6.1f}% "
            f"{outflow:>+8.1f}亿 {bar:<{bar_width}} │"
        )

    print(f"└{'─'*50}┘")


def main():
    parser = argparse.ArgumentParser(description="Fetch today sector fund flow")
    parser.add_argument("--date", type=str, default=None, help="Trade date (default: 2026-07-14)")
    parser.add_argument("--save", action="store_true", help="Save to DuckDB intraday_sector_flow")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--chart", action="store_true", help="ASCII bar chart")
    parser.add_argument("--sector", choices=["industry", "concept", "both"], default="both")
    args = parser.parse_args()

    trade_date = date.fromisoformat(args.date) if args.date else date(2026, 7, 14)
    results = fetch_tushare_flow(trade_date)

    if not results:
        print("No data fetched — check Tushare API availability")
        return 1

    all_data = []
    for sector_type, df in results.items():
        if sector_type == "industry":
            df["sector_name"] = df["industry_name"]
        else:
            df["sector_name"] = df["concept_name"]
        df["sector_type"] = sector_type
        all_data.append(df)

    full_df = pd.concat(all_data, ignore_index=True)

    if args.chart:
        for sector_type, df in results.items():
            display_chart(df, sector_type.upper())

    for sector_type, df in results.items():
        if args.sector == "both" or args.sector == sector_type:
            display_top(df, sector_type.upper())

    if args.save:
        conn = duckdb.connect(DB_PATH, read_only=False)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS intraday_sector_flow (
                fetch_time TIMESTAMP, sector_name VARCHAR, sector_type VARCHAR,
                trade_date DATE, pct_chg DOUBLE, main_inflow DOUBLE,
                sector_code VARCHAR,
                PRIMARY KEY (sector_name, sector_type, trade_date)
            )"""
        )
        save_df = full_df.copy()
        save_df["fetch_time"] = datetime.now()
        save_df["trade_date"] = trade_date
        # Only keep columns that match the table schema
        table_cols = ["fetch_time", "sector_name", "sector_type", "trade_date",
                      "pct_chg", "main_inflow", "sector_code"]
        save_df = save_df[table_cols]
        conn.register("_df", save_df)
        conn.execute("INSERT OR REPLACE INTO intraday_sector_flow BY NAME SELECT * FROM _df")
        cnt = conn.execute("SELECT COUNT(*) FROM intraday_sector_flow").fetchone()[0]
        conn.close()
        logger.info(f"Saved {cnt} rows to intraday_sector_flow")

    if args.json:
        result_json = {}
        for sector_type, df in results.items():
            top_in = df.nlargest(10, "main_inflow")
            top_out = df.nsmallest(10, "main_inflow")
            name_col = "industry_name" if sector_type == "industry" else "concept_name"
            result_json[sector_type] = {
                "top_inflow": [
                    {
                        "name": r[name_col],
                        "pct_chg": float(r["pct_chg"]),
                        "main_inflow_yi": float(r["main_inflow"]) / 1e8,
                    }
                    for _, r in top_in.iterrows()
                ],
                "top_outflow": [
                    {
                        "name": r[name_col],
                        "pct_chg": float(r["pct_chg"]),
                        "main_inflow_yi": float(r["main_inflow"]) / 1e8,
                    }
                    for _, r in top_out.iterrows()
                ],
            }
        print(json.dumps(result_json, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
