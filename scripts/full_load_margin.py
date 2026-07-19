# ruff: noqa: E402
"""Full-load script for margin."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
from argparse import Namespace

from data.updater import MarginUpdater
from scripts.full_load_helpers import (
    add_trade_date_argument,
    build_logger,
    run_updater_job,
)

logger = build_logger('margin')


def parse_args() -> Namespace:
    """Parse CLI arguments for the margin full-load script."""
    parser = argparse.ArgumentParser(description='Full load margin.')
    add_trade_date_argument(parser)
    return parser.parse_args()


def build_run_kwargs(args: Namespace) -> dict[str, object]:
    """Convert CLI arguments into updater.run keyword arguments."""
    return {'trade_date': args.trade_date}


def main() -> dict[str, int]:
    """Run the margin full-load job."""
    args = parse_args()
    return run_updater_job('margin', MarginUpdater, build_run_kwargs(args), logger)


def run_job(**kwargs: object) -> dict[str, int]:
    """Programmatic entrypoint used by the full-load orchestrator."""
    return run_updater_job('margin', MarginUpdater, dict(kwargs), logger)


if __name__ == '__main__':
    main()
