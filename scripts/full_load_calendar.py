# ruff: noqa: E402
"""Full-load script for calendar."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
from argparse import Namespace

from data.updater import CalendarUpdater
from scripts.full_load_helpers import (
    add_date_range_arguments,
    build_logger,
    run_updater_job,
)

logger = build_logger('calendar')


def parse_args() -> Namespace:
    """Parse CLI arguments for the calendar full-load script."""
    parser = argparse.ArgumentParser(description='Full load calendar.')
    add_date_range_arguments(parser)
    return parser.parse_args()


def build_run_kwargs(args: Namespace) -> dict[str, object]:
    """Convert CLI arguments into updater.run keyword arguments."""
    return {'start_date': args.start_date, 'end_date': args.end_date}


def main() -> dict[str, int]:
    """Run the calendar full-load job."""
    args = parse_args()
    return run_updater_job('calendar', CalendarUpdater, build_run_kwargs(args), logger)


def run_job(**kwargs: object) -> dict[str, int]:
    """Programmatic entrypoint used by the full-load orchestrator."""
    return run_updater_job('calendar', CalendarUpdater, dict(kwargs), logger)


if __name__ == '__main__':
    main()
