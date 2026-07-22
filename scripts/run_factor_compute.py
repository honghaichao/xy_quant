"""Factor compute script entrypoint.

Usage:
    .venv/bin/python scripts/run_factor_compute.py --date 20260714
    .venv/bin/python scripts/run_factor_compute.py --start-date 20260701 --end-date 20260714
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
from datetime import date, datetime

from factor.updater import FactorDataUpdater
from utils.logger import get_logger

logger = get_logger("run_factor_compute")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Compute daily factor data")
    p.add_argument("--date", type=str, default=None, help="Target date YYYYMMDD")
    p.add_argument("--start-date", type=str, default=None, help="Start date YYYYMMDD")
    p.add_argument("--end-date", type=str, default=None, help="End date YYYYMMDD")
    p.add_argument("--ts-codes", type=str, default=None, help="Stock codes, comma-separated")
    return p.parse_args()


def _parse_date(raw: str | None) -> date | None:
    if raw is None:
        return None
    return datetime.strptime(raw, "%Y%m%d").date()


def run_job(**kwargs) -> dict[str, int]:
    """Orchestratible entrypoint for scheduler."""
    updater = FactorDataUpdater()
    try:
        target_date = kwargs.get("target_date")
        start_date = kwargs.get("start_date")
        end_date = kwargs.get("end_date")
        ts_codes = kwargs.get("ts_codes")
        return updater.run(
            target_date=target_date,
            start_date=start_date,
            end_date=end_date,
            ts_codes=ts_codes,
        )
    finally:
        updater.close()


def main() -> int:
    args = parse_args()
    target_date = _parse_date(args.date)
    start_date = _parse_date(args.start_date)
    end_date = _parse_date(args.end_date)
    ts_codes = args.ts_codes.split(",") if args.ts_codes else None

    updater = FactorDataUpdater()
    try:
        result = updater.run(
            target_date=target_date,
            start_date=start_date,
            end_date=end_date,
            ts_codes=ts_codes,
        )
        logger.info(f"Done: {result}")
        return 0
    except Exception:
        logger.exception("run_factor_compute failed")
        return 1
    finally:
        updater.close()


if __name__ == "__main__":
    sys.exit(main())
