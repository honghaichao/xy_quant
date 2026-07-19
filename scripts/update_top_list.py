# ruff: noqa: E402
"""Incremental update script for top_list."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
from argparse import Namespace

from data.updater import TopListUpdater
from scripts.update_helpers import (
    add_trade_date_argument,
    build_logger,
    run_updater_job,
)

logger = build_logger('top_list')


def parse_args() -> Namespace:
    """Parse CLI arguments for the top_list update script."""
    parser = argparse.ArgumentParser(description='Update top_list.')
    add_trade_date_argument(parser)
    return parser.parse_args()


def build_run_kwargs(args: Namespace) -> dict[str, object]:
    """Convert CLI arguments into updater.run keyword arguments."""
    return {'trade_date': args.trade_date}


def main() -> dict[str, int]:
    """Run the top_list incremental update job."""
    args = parse_args()
    return run_updater_job('top_list', TopListUpdater, build_run_kwargs(args), logger)


def run_job(**kwargs: object) -> dict[str, int]:
    """Programmatic entrypoint used by the incremental orchestrator."""
    return run_updater_job('top_list', TopListUpdater, dict(kwargs), logger)


if __name__ == '__main__':
    main()
