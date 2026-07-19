# ruff: noqa: E402
"""Incremental update script for index_daily."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
from argparse import Namespace

from data.updater import IndexDailyUpdater
from scripts.update_helpers import (
    add_date_range_arguments,
    add_index_codes_argument,
    build_logger,
    run_updater_job,
)

logger = build_logger('index_daily')


def parse_args() -> Namespace:
    """Parse CLI arguments for the index_daily update script."""
    parser = argparse.ArgumentParser(description='Update index_daily.')
    add_index_codes_argument(parser, required=True)
    add_date_range_arguments(parser)
    return parser.parse_args()


def build_run_kwargs(args: Namespace) -> dict[str, object]:
    """Convert CLI arguments into updater.run keyword arguments."""
    return {'index_codes': args.index_codes, 'start_date': args.start_date, 'end_date': args.end_date}


def main() -> dict[str, int]:
    """Run the index_daily incremental update job."""
    args = parse_args()
    return run_updater_job('index_daily', IndexDailyUpdater, build_run_kwargs(args), logger)


def run_job(**kwargs: object) -> dict[str, int]:
    """Programmatic entrypoint used by the incremental orchestrator."""
    return run_updater_job('index_daily', IndexDailyUpdater, dict(kwargs), logger)


if __name__ == '__main__':
    main()
