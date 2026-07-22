"""盘中实时数据采集脚本。

Mode 说明:
  spot     全市场实时行情快照 -> intraday_spot
  fundflow 个股资金流排名 -> intraday_fund_flow
  sector   行业/概念资金流 -> intraday_fund_flow (sector_type区分)
  full     以上全部一次拉取
  minute   指定个股当日分钟K线 (直接写入 minute_bar 分区)

Usage:
  .venv/bin/python scripts/fetch_intraday.py --mode spot
  .venv/bin/python scripts/fetch_intraday.py --mode full
  .venv/bin/python scripts/fetch_intraday.py --mode minute --code 000001
  .venv/bin/python scripts/fetch_intraday.py --mode full --loop --interval 300  # 每5分钟轮询
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import json
import time
from datetime import datetime, timezone

import duckdb

from config.settings import settings
from data.source.intraday_source import IntradayFetcher
from utils.logger import get_logger

logger = get_logger("fetch_intraday")
DB_PATH = str(Path(settings.duckdb_path))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch intraday data")
    p.add_argument("--mode", required=True,
                   choices=["spot", "fundflow", "sector", "full", "minute", "tick"])
    p.add_argument("--code", default=None, help="Stock code for minute/tick mode")
    p.add_argument("--loop", action="store_true", help="Keep polling until market close")
    p.add_argument("--interval", type=int, default=300, help="Polling interval in seconds")
    p.add_argument("--dry-run", action="store_true", help="Print without writing")
    return p.parse_args()


def _upsert(df, table: str) -> int:
    if df.empty:
        return 0
    conn = duckdb.connect(DB_PATH, read_only=False)
    try:
        conn.register("_tmp_intraday", df)
        conn.execute(f"INSERT OR REPLACE INTO {table} BY NAME SELECT * FROM _tmp_intraday")
        conn.unregister("_tmp_intraday")
        return len(df)
    finally:
        conn.close()


def run_spot(fetcher: IntradayFetcher, dry: bool = False) -> int:
    logger.info("Fetching spot snapshot...")
    df = fetcher.fetch_spot()
    if df.empty:
        logger.warning("spot returned empty")
        return 0
    logger.info(f"spot: {len(df)} stocks, cols={list(df.columns)}")
    if dry:
        print(df.head(3).to_string())
        return len(df)
    return _upsert(df, "intraday_spot")


def run_fundflow(fetcher: IntradayFetcher, dry: bool = False) -> int:
    logger.info("Fetching fund flow rank...")
    df = fetcher.fetch_fund_flow_rank()
    if df.empty:
        logger.warning("fundflow returned empty")
        return 0
    logger.info(f"fundflow: {len(df)} stocks")
    if dry:
        print(df.head(3).to_string())
        return len(df)
    return _upsert(df, "intraday_fund_flow")


def run_sector(fetcher: IntradayFetcher, dry: bool = False) -> int:
    logger.info("Fetching sector flow...")
    df = fetcher.fetch_sector_fund_flow()
    if df.empty:
        logger.warning("sector flow returned empty")
        return 0
    logger.info(f"sector flow: {len(df)} entries (industry+concept)")
    if dry:
        print(df.head(5).to_string())
        return len(df)
    return _upsert(df, "intraday_fund_flow")


def run_full(fetcher: IntradayFetcher, dry: bool = False) -> dict[str, int]:
    counts = {}
    for label, fn in [("spot", run_spot), ("fundflow", run_fundflow), ("sector", run_sector)]:
        try:
            counts[label] = fn(fetcher, dry)
        except Exception as e:
            logger.error(f"{label} failed: {e}")
            counts[label] = 0
    return counts


def run_minute(code: str, fetcher: IntradayFetcher, dry: bool = False) -> int:
    logger.info(f"Fetching minute bars for {code}...")
    df = fetcher.fetch_minute_today(code, period="1")
    if df.empty:
        logger.warning(f"minute {code}: empty")
        return 0
    logger.info(f"minute {code}: {len(df)} bars")
    if dry:
        print(df.head(5).to_string())
        return len(df)
    conn = duckdb.connect(DB_PATH, read_only=False)
    try:
        # Write through existing minute_bar infrastructure
        month_str = df["datetime"].iloc[0][:7].replace("-", "_")
        table = f"minute_bar_{month_str}"
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {table} AS SELECT * FROM minute_bar WHERE 1=0"
        )
        conn.register("_tmp_min", df)
        conn.execute(f"INSERT OR REPLACE INTO {table} BY NAME SELECT * FROM _tmp_min")
        conn.unregister("_tmp_min")
        return len(df)
    finally:
        conn.close()


def run_tick(code: str, fetcher: IntradayFetcher, dry: bool = False) -> int:
    logger.info(f"Fetching ticks for {code}...")
    df = fetcher.fetch_tick(code)
    if df.empty:
        logger.warning(f"tick {code}: empty")
        return 0
    logger.info(f"tick {code}: {len(df)} trades")
    if dry:
        print(df.head(10).to_string())
    return len(df)


def main() -> int:
    args = parse_args()
    fetcher = IntradayFetcher()

    if args.loop:
        logger.info(f"Loop mode: every {args.interval}s, mode={args.mode}")
        while True:
            # Check if market is open
            now = datetime.now()
            if now.weekday() >= 5:
                logger.info("Weekend — stopping")
                break
            if now.hour < 9 or (now.hour == 9 and now.minute < 25):
                logger.info("Before market open — skipping")
                time.sleep(args.interval)
                continue
            if now.hour >= 15 and now.minute >= 5:
                logger.info("After market close — stopping")
                break

            try:
                if args.mode == "full":
                    result = run_full(fetcher)
                elif args.mode == "spot":
                    result = run_spot(fetcher)
                elif args.mode == "fundflow":
                    result = run_fundflow(fetcher)
                elif args.mode == "sector":
                    result = run_sector(fetcher)
                else:
                    logger.error(f"Unknown mode: {args.mode}")
                    return 1
                logger.info(f"loop result: {json.dumps(result) if isinstance(result, dict) else result}")
            except Exception as e:
                logger.error(f"loop iteration failed: {e}")

            time.sleep(args.interval)
        return 0

    # Single shot
    mode_map = {
        "spot": lambda: run_spot(fetcher, args.dry_run),
        "fundflow": lambda: run_fundflow(fetcher, args.dry_run),
        "sector": lambda: run_sector(fetcher, args.dry_run),
        "full": lambda: run_full(fetcher, args.dry_run),
    }
    if args.mode in mode_map:
        result = mode_map[args.mode]()
    elif args.mode == "minute":
        if not args.code:
            logger.error("--code required for minute mode")
            return 1
        result = run_minute(args.code, fetcher, args.dry_run)
    elif args.mode == "tick":
        if not args.code:
            logger.error("--code required for tick mode")
            return 1
        result = run_tick(args.code, fetcher, args.dry_run)
    else:
        logger.error(f"Unknown mode: {args.mode}")
        return 1

    logger.info(f"Done: {json.dumps(result) if isinstance(result, dict) else result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
