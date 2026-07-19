# ruff: noqa: E402
"""Real indicator ingestion entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
from argparse import Namespace

from data.updater import AdjFactorUpdater, DailyBarUpdater, DailyBasicUpdater, IndexDailyUpdater
from scripts.orchestration import REAL_INDICATOR_JOB_SPECS
from scripts.orchestration import run_subjob as orchestration_run_subjob
from scripts.update_helpers import (
    add_index_codes_argument,
    add_date_range_arguments,
    add_ts_codes_argument,
    build_logger,
    run_updater_job,
)

logger = build_logger('real_indicator')


def parse_args() -> Namespace:
    """Parse CLI arguments for the real-indicator workflow."""
    parser = argparse.ArgumentParser(description='Load real indicators.')
    add_ts_codes_argument(parser, required=False)
    add_index_codes_argument(parser, required=False)
    add_date_range_arguments(parser)
    return parser.parse_args()


def _normalize_args(args: Namespace) -> Namespace:
    if not getattr(args, 'ts_codes', None):
        args.ts_codes = []
    if not getattr(args, 'index_codes', None):
        args.index_codes = []
    return args


def run_subjob(job_name: str, **kwargs: object) -> dict[str, int]:
    return orchestration_run_subjob(job_name, script_prefix='full_load', **kwargs)


def run_defined_jobs(args: Namespace) -> dict[str, dict[str, int]]:
    results: dict[str, dict[str, int]] = {}
    for job in REAL_INDICATOR_JOB_SPECS:
        results[job.name] = run_subjob(job.name, **job.kwargs_builder(args))
    return results


def main() -> dict[str, dict[str, int]]:
    args = _normalize_args(parse_args())
    logger.info('Starting real-indicator ingestion.')
    results = run_defined_jobs(args)
    logger.info('Real-indicator ingestion complete.')
    return results


def run_job(**kwargs: object) -> dict[str, dict[str, int]]:
    return main()


if __name__ == '__main__':
    main()
