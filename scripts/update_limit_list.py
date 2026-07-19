# ruff: noqa: E402
"""Incremental update script for limit_list."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
from argparse import Namespace

from data.updater import LimitListUpdater
from scripts.update_helpers import (
    add_trade_date_argument,
    build_logger,
    run_updater_job,
)

logger = build_logger('limit_list')


def parse_args() -> Namespace:
    """Parse CLI arguments for the limit_list update script."""
    parser = argparse.ArgumentParser(description='Update limit_list.')
    add_trade_date_argument(parser)
    parser.add_argument('--kind', default='U')
    return parser.parse_args()


def build_run_kwargs(args: Namespace) -> dict[str, object]:
    """Convert CLI arguments into updater.run keyword arguments."""
    return {'trade_date': args.trade_date, 'kind': args.kind}


def main() -> dict[str, int]:
    """Run the limit_list incremental update job."""
    args = parse_args()
    return run_updater_job('limit_list', LimitListUpdater, build_run_kwargs(args), logger)


def run_job(**kwargs: object) -> dict[str, int]:
    """Programmatic entrypoint used by the incremental orchestrator."""
    return run_updater_job('limit_list', LimitListUpdater, dict(kwargs), logger)


if __name__ == '__main__':
    main()
