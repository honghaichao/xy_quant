# ruff: noqa: E402
"""Full-load script for hk_hold."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
from argparse import Namespace

from data.updater import HkHoldUpdater
from scripts.full_load_helpers import (
    add_trade_date_argument,
    build_logger,
    run_updater_job,
)

logger = build_logger('hk_hold')


def parse_args() -> Namespace:
    """Parse CLI arguments for the hk_hold full-load script."""
    parser = argparse.ArgumentParser(description='Full load hk_hold.')
    add_trade_date_argument(parser, required=False)
    parser.add_argument('--ts-code')
    return parser.parse_args()


def build_run_kwargs(args: Namespace) -> dict[str, object]:
    """Convert CLI arguments into updater.run keyword arguments."""
    return {'trade_date': args.trade_date, 'ts_code': args.ts_code}


def main() -> dict[str, int]:
    """Run the hk_hold full-load job."""
    args = parse_args()
    return run_updater_job('hk_hold', HkHoldUpdater, build_run_kwargs(args), logger)


def run_job(**kwargs: object) -> dict[str, int]:
    """Programmatic entrypoint used by the full-load orchestrator."""
    return run_updater_job('hk_hold', HkHoldUpdater, dict(kwargs), logger)


if __name__ == '__main__':
    main()
