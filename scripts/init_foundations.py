# ruff: noqa: E402
"""Bootstrap foundational metadata tables independently from broad full loads."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
from argparse import Namespace

from scripts.full_load_helpers import add_date_range_arguments, build_logger
from scripts.init_db import main as init_db_main
from scripts.orchestration import FOUNDATION_INIT_JOB_SPECS, run_defined_jobs

logger = build_logger("foundations")


def parse_args(argv: list[str] | None = None) -> Namespace:
    parser = argparse.ArgumentParser(description="Initialize foundational tables before broader loads.")
    add_date_range_arguments(parser)
    return parser.parse_args(argv)


def _run_from_args(args: Namespace) -> dict[str, dict[str, int]]:
    logger.info("Initializing storage before foundation bootstrap.")
    init_db_main([])
    logger.info("Starting foundation bootstrap.")
    results = run_defined_jobs(args=args, jobs=FOUNDATION_INIT_JOB_SPECS, script_prefix="full_load")
    logger.info("Foundation bootstrap complete.")
    return results


def main(argv: list[str] | None = None) -> dict[str, dict[str, int]]:
    return _run_from_args(parse_args(argv))


def run_job(**kwargs: object) -> dict[str, dict[str, int]]:
    return _run_from_args(Namespace(**kwargs))


if __name__ == "__main__":
    main()
