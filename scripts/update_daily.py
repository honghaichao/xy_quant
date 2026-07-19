# ruff: noqa: E402
"""Incremental update script for daily."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
from argparse import Namespace

from data.updater import DailyUpdater
from scripts.update_helpers import (
    add_index_codes_argument,
    add_trade_date_argument,
    add_ts_codes_argument,
    build_logger,
    run_updater_job,
)

logger = build_logger('daily')


def parse_args() -> Namespace:
    """Parse CLI arguments for the daily update script."""
    parser = argparse.ArgumentParser(description='Update daily.')
    add_trade_date_argument(parser)
    add_ts_codes_argument(parser)
    add_index_codes_argument(parser)
    return parser.parse_args()


def build_run_kwargs(args: Namespace) -> dict[str, object]:
    """Convert CLI arguments into updater.run keyword arguments."""
    return {'trade_date': args.trade_date, 'ts_codes': args.ts_codes, 'index_codes': args.index_codes}


def main() -> dict[str, int]:
    """Run the daily incremental update job."""
    args = parse_args()
    return run_updater_job('daily', DailyUpdater, build_run_kwargs(args), logger)


def run_job(**kwargs: object) -> dict[str, int]:
    """Programmatic entrypoint used by the incremental orchestrator."""
    return run_updater_job('daily', DailyUpdater, dict(kwargs), logger)


if __name__ == '__main__':
    main()
