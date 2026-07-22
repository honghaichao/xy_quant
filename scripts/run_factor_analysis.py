"""Factor analysis script entrypoint.

Usage:
    .venv/bin/python scripts/run_factor_analysis.py --factor-names macd_dif,pe_ttm,rsi_6,roe
    .venv/bin/python scripts/run_factor_analysis.py --all-factors
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
from datetime import date, datetime, timedelta

import duckdb

from config.settings import settings
from factor.analysis import run_analysis
from factor.registry import FactorRegistry
from utils.logger import get_logger

logger = get_logger("run_factor_analysis")

DB_PATH = str(settings.duckdb_path)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Factor IC analysis")
    p.add_argument("--factor-names", type=str, default=None, help="Comma-separated factor names")
    p.add_argument("--all-factors", action="store_true", help="Analyze all registered factors")
    p.add_argument("--start-date", type=str, default=None, help="Start date YYYYMMDD")
    p.add_argument("--end-date", type=str, default=None, help="End date YYYYMMDD")
    p.add_argument("--periods", type=str, default="1,5,20", help="Forward periods")
    return p.parse_args()


def _parse_date(raw: str | None) -> date | None:
    if raw is None:
        return None
    return datetime.strptime(raw, "%Y%m%d").date()


def main() -> int:
    args = parse_args()

    # Resolve factor names
    if args.all_factors:
        reg = FactorRegistry()
        factor_names = reg.list()
    elif args.factor_names:
        factor_names = [f.strip() for f in args.factor_names.split(",")]
    else:
        # Default: key technical + fundamental factors
        factor_names = [
            "macd_dif", "kdj_k", "rsi_6", "price_momentum_20d",
            "volatility_20d", "pe_ttm", "pb", "roe",
        ]

    # Check available in factor_data
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        cols = [d[0] for d in conn.execute("DESCRIBE factor_data").fetchall()]
        available = [f for f in factor_names if f in cols]
        missing = [f for f in factor_names if f not in cols]
        if missing:
            logger.warning(f"Factors not in factor_data: {missing}")
        if not available:
            logger.error("No available factors found. Run factor_compute first.")
            return 1
    finally:
        conn.close()

    # Default date range: last 2 years
    if args.end_date is None:
        end_date = date.today()
    else:
        end_date = _parse_date(args.end_date)
    if args.start_date is None:
        start_date = end_date - timedelta(days=365 * 2)
    else:
        start_date = _parse_date(args.start_date)

    periods = [int(p) for p in args.periods.split(",")]

    logger.info(f"Analyzing {len(available)} factors: {available}")
    logger.info(f"Date range: {start_date} ~ {end_date}, periods: {periods}")

    try:
        report = run_analysis(available, start_date, end_date, forward_periods=periods)

        # Print summary
        if "ic_analysis" in report:
            ic_df = report["ic_analysis"]
            print("\n=== IC Analysis ===")
            print(ic_df.to_string())

        if "quantile_returns" in report:
            qr_df = report["quantile_returns"]
            print("\n=== Quantile Returns ===")
            print(qr_df.to_string())

        return 0
    except Exception:
        logger.exception("run_factor_analysis failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
