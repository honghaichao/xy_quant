# ruff: noqa: E402
"""Incremental update script for holdertrade."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
from argparse import Namespace

from data.updater import HoldertradeUpdater
from scripts.update_helpers import (
    build_logger,
    parse_date,
    run_updater_job,
)

logger = build_logger('holdertrade')


def parse_args() -> Namespace:
    """Parse CLI arguments for the holdertrade update script."""
    parser = argparse.ArgumentParser(description='Update holdertrade.')
    parser.add_argument('--ts-code')
    parser.add_argument('--ann-date', type=parse_date, required=True)
    return parser.parse_args()


def build_run_kwargs(args: Namespace) -> dict[str, object]:
    """Convert CLI arguments into updater.run keyword arguments."""
    return {'ann_date': args.ann_date, **({'ts_code': args.ts_code} if args.ts_code is not None else {})}


def main() -> dict[str, int]:
    """Run the holdertrade incremental update job."""
    args = parse_args()
    return run_updater_job('holdertrade', HoldertradeUpdater, build_run_kwargs(args), logger)


def run_job(**kwargs: object) -> dict[str, int]:
    """Programmatic entrypoint used by the incremental orchestrator."""
    return run_updater_job('holdertrade', HoldertradeUpdater, dict(kwargs), logger)


if __name__ == '__main__':
    main()
