# ruff: noqa: E402
"""Full-load script for adj_factor."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
from argparse import Namespace

from data.updater import AdjFactorUpdater
from scripts.full_load_helpers import (
    add_date_range_arguments,
    add_ts_codes_argument,
    build_logger,
    run_updater_job,
)

logger = build_logger('adj_factor')


def parse_args() -> Namespace:
    """Parse CLI arguments for the adj_factor full-load script."""
    parser = argparse.ArgumentParser(description='Full load adj_factor.')
    add_ts_codes_argument(parser)
    add_date_range_arguments(parser)
    return parser.parse_args()


def build_run_kwargs(args: Namespace) -> dict[str, object]:
    """Convert CLI arguments into updater.run keyword arguments."""
    return {'ts_codes': args.ts_codes, 'start_date': args.start_date, 'end_date': args.end_date}


def main() -> dict[str, int]:
    """Run the adj_factor full-load job."""
    args = parse_args()
    return run_updater_job('adj_factor', AdjFactorUpdater, build_run_kwargs(args), logger)


def run_job(**kwargs: object) -> dict[str, int]:
    """Programmatic entrypoint used by the full-load orchestrator."""
    return run_updater_job('adj_factor', AdjFactorUpdater, dict(kwargs), logger)


if __name__ == '__main__':
    main()
