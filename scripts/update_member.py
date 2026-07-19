# ruff: noqa: E402
"""Incremental update script for member."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
from argparse import Namespace

from data.updater import MemberUpdater
from scripts.update_helpers import (
    add_concept_codes_argument,
    add_index_codes_argument,
    add_industry_codes_argument,
    add_trade_date_argument,
    build_logger,
    run_updater_job,
)

logger = build_logger('member')


def parse_args() -> Namespace:
    """Parse CLI arguments for the member update script."""
    parser = argparse.ArgumentParser(description='Update member.')
    add_concept_codes_argument(parser)
    add_industry_codes_argument(parser)
    add_index_codes_argument(parser)
    add_trade_date_argument(parser, required=False)
    return parser.parse_args()


def build_run_kwargs(args: Namespace) -> dict[str, object]:
    """Convert CLI arguments into updater.run keyword arguments."""
    return {'concept_codes': args.concept_codes, 'industry_codes': args.industry_codes, 'index_codes': args.index_codes, 'trade_date': args.trade_date}


def main() -> dict[str, int]:
    """Run the member incremental update job."""
    args = parse_args()
    return run_updater_job('member', MemberUpdater, build_run_kwargs(args), logger)


def run_job(**kwargs: object) -> dict[str, int]:
    """Programmatic entrypoint used by the incremental orchestrator."""
    return run_updater_job('member', MemberUpdater, dict(kwargs), logger)


if __name__ == '__main__':
    main()
