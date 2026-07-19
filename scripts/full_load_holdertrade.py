# ruff: noqa: E402
"""Full-load script for holdertrade."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
from argparse import Namespace

from data.updater import HoldertradeUpdater
from scripts.full_load_helpers import (
    build_logger,
    parse_date,
    run_updater_job,
)

logger = build_logger('holdertrade')


def parse_args() -> Namespace:
    """Parse CLI arguments for the holdertrade full-load script."""
    parser = argparse.ArgumentParser(description='Full load holdertrade.')
    parser.add_argument('--ts-code')
    parser.add_argument('--ann-date', type=parse_date)
    return parser.parse_args()


def build_run_kwargs(args: Namespace) -> dict[str, object]:
    """Convert CLI arguments into updater.run keyword arguments."""
    return {'ts_code': args.ts_code, 'ann_date': args.ann_date}


def main() -> dict[str, int]:
    """Run the holdertrade full-load job."""
    args = parse_args()
    return run_updater_job('holdertrade', HoldertradeUpdater, build_run_kwargs(args), logger)


def run_job(**kwargs: object) -> dict[str, int]:
    """Programmatic entrypoint used by the full-load orchestrator."""
    return run_updater_job('holdertrade', HoldertradeUpdater, dict(kwargs), logger)


if __name__ == '__main__':
    main()
