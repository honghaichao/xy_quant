"""历史信号+因子回溯脚本 — 逐天扫描历史信号和因子数据。

从最新交易日向历史回溯，每天执行: batch_scan → populate_signal_events → factor_compute

Usage:
    .venv/bin/python scripts/backfill_signals_factors.py --days 30           # 最近30个交易日
    .venv/bin/python scripts/backfill_signals_factors.py --start 20260601 --end 20260714
    .venv/bin/python scripts/backfill_signals_factors.py --days 252 --resume # 最近1年
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
from datetime import date, datetime, timedelta

import duckdb

from config.settings import settings
from utils.logger import get_logger

logger = get_logger("backfill_signals_factors")

DB_PATH = str(Path(settings.duckdb_path))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill historical signals and factor data")
    p.add_argument("--days", type=int, default=0, help="Number of trading days to backfill")
    p.add_argument("--start", type=str, default=None, help="Start date YYYYMMDD")
    p.add_argument("--end", type=str, default=None, help="End date YYYYMMDD")
    p.add_argument("--resume", action="store_true", help="Skip dates already in daily_signals")
    p.add_argument("--limit", type=int, default=None, help="Max dates to process")
    return p.parse_args()


def get_trade_days(start: date, end: date) -> list[date]:
    """Get sorted list of trading days from daily_bar (ascending)."""
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        rows = conn.execute(
            "SELECT DISTINCT trade_date FROM daily_bar "
            "WHERE trade_date >= ? AND trade_date <= ? "
            "ORDER BY trade_date",
            [start.isoformat(), end.isoformat()],
        ).fetchall()
        return [date.fromisoformat(str(r[0])) for r in rows]
    finally:
        conn.close()


def has_signals(trade_date: date) -> bool:
    """Check if daily_signals already has data for this date."""
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        r = conn.execute(
            "SELECT COUNT(*) FROM daily_signals WHERE \"date\" = ?",
            [trade_date.isoformat()],
        ).fetchone()
        return r[0] > 0
    finally:
        conn.close()


def run_step(step_name: str, cmd: str) -> bool:
    """Run a single step. Returns True on success."""
    import subprocess

    t0 = time.monotonic()
    logger.info(f"  [{step_name}] running: {cmd}")
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            cwd=str(PROJECT_ROOT), timeout=3600,
        )
        duration = time.monotonic() - t0
        if result.returncode == 0:
            logger.info(f"  [{step_name}] OK ({duration:.0f}s)")
            return True
        else:
            logger.error(f"  [{step_name}] FAILED (rc={result.returncode}): {result.stderr[-200:]}")
            return False
    except subprocess.TimeoutExpired:
        logger.error(f"  [{step_name}] TIMEOUT after 3600s")
        return False
    except Exception as e:
        logger.error(f"  [{step_name}] ERROR: {e}")
        return False


def backfill_one_day(trade_date: date) -> dict[str, bool]:
    """Run all steps for one trading day."""
    date_str = trade_date.strftime("%Y%m%d")
    venv_python = ".venv/bin/python"

    results = {}

    # Step 1: batch_scan
    results["scan"] = run_step(
        "scan",
        f"{venv_python} scripts/batch_scan.py --date {date_str}",
    )

    if not results["scan"]:
        return results

    # Step 2: signal_events
    results["events"] = run_step(
        "events",
        f"{venv_python} scripts/populate_signal_events.py --date {date_str}",
    )

    # Step 3: factor_compute
    results["factor"] = run_step(
        "factor",
        f"{venv_python} scripts/run_factor_compute.py --date {date_str}",
    )

    return results


def main() -> int:
    args = parse_args()

    # Determine date range
    if args.start and args.end:
        start_date = datetime.strptime(args.start, "%Y%m%d").date()
        end_date = datetime.strptime(args.end, "%Y%m%d").date()
    elif args.days > 0:
        end_date = date.today()
        start_date = end_date - timedelta(days=args.days * 2)  # account for weekends
    else:
        # Default: last 20 trading days
        end_date = date.today()
        start_date = end_date - timedelta(days=60)

    logger.info(f"Loading trading days from {start_date} to {end_date}")
    trade_days = get_trade_days(start_date, end_date)

    if args.resume:
        before = len(trade_days)
        trade_days = [d for d in trade_days if not has_signals(d)]
        logger.info(f"Resume mode: {before - len(trade_days)} already done, {len(trade_days)} remaining")

    if args.limit and args.limit > 0:
        trade_days = trade_days[:args.limit]

    logger.info(f"Will backfill {len(trade_days)} trading days")

    if not trade_days:
        logger.info("Nothing to do.")
        return 0

    success_count = 0
    fail_count = 0
    t0 = time.monotonic()

    for i, td in enumerate(trade_days):
        logger.info(f"\n[{i+1}/{len(trade_days)}] {td} ({td.strftime('%A')})")
        results = backfill_one_day(td)
        if results.get("scan"):
            success_count += 1
        else:
            fail_count += 1

        elapsed = time.monotonic() - t0
        avg = elapsed / (i + 1)
        remaining = avg * (len(trade_days) - i - 1)
        logger.info(
            f"  Progress: {success_count} OK, {fail_count} FAIL | "
            f"ETA: {remaining/60:.0f}min remaining"
        )

    total = time.monotonic() - t0
    logger.info(f"\n=== DONE === {success_count}/{len(trade_days)} days in {total/60:.0f}min")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
