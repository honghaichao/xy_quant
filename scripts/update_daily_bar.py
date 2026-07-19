# ruff: noqa: E402
"""Incremental update script for daily_bar."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
from argparse import ArgumentParser, Namespace

from data.updater import DailyBarUpdater
from scripts.update_helpers import (
    add_date_range_arguments,
    add_trade_date_argument,
    add_ts_codes_argument,
    build_logger,
    run_updater_job,
)

logger = build_logger('daily_bar')


def parse_args() -> Namespace:
    """Parse CLI arguments for the daily_bar update script."""
    parser = argparse.ArgumentParser(description='Update daily_bar.')
    add_ts_codes_argument(parser, required=False)
    add_trade_date_argument(parser, required=False)
    add_date_range_arguments(parser, required=False)
    parser.add_argument('--force', action='store_true', help='Force a targeted backfill for the requested date/date range.')
    args = parser.parse_args()
    _validate_precise_backfill_args(parser, args)
    if args.trade_date is not None:
        args.start_date = args.trade_date
        args.end_date = args.trade_date
    return args


def _validate_precise_backfill_args(parser: ArgumentParser, args: Namespace) -> None:
    has_trade_date = args.trade_date is not None
    has_range = args.start_date is not None or args.end_date is not None
    if has_trade_date and has_range:
        parser.error('Use either --date or --start/--end, not both.')
    if has_trade_date:
        return
    if args.start_date is None and args.end_date is None:
        parser.error('Provide either --date or both --start/--end.')
    if args.start_date is None or args.end_date is None:
        parser.error('Both --start and --end are required when --date is not provided.')
    if args.start_date > args.end_date:
        parser.error('--start must be earlier than or equal to --end.')


def build_run_kwargs(args: Namespace) -> dict[str, object]:
    """Convert CLI arguments into updater.run keyword arguments."""
    return {'ts_codes': args.ts_codes or None, 'start_date': args.start_date, 'end_date': args.end_date}


def main() -> dict[str, int]:
    """Run the daily_bar incremental update job."""
    args = parse_args()
    return run_updater_job('daily_bar', DailyBarUpdater, build_run_kwargs(args), logger)


def run_job(**kwargs: object) -> dict[str, int]:
    """Programmatic entrypoint used by the incremental orchestrator."""
    return run_updater_job('daily_bar', DailyBarUpdater, dict(kwargs), logger)


if __name__ == '__main__':
    main()
