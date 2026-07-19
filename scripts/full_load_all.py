# ruff: noqa: E402
"""Orchestrated full-load entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
from argparse import Namespace

from scripts.full_load_helpers import (
    add_concept_codes_argument,
    add_date_range_arguments,
    add_index_codes_argument,
    add_industry_codes_argument,
    add_trade_date_argument,
    add_ts_codes_argument,
    build_logger,
    parse_date,
)
from scripts.init_db import main as init_db_main
from scripts.orchestration import FULL_LOAD_JOB_SPECS
from scripts.orchestration import run_subjob as orchestration_run_subjob
from scripts.orchestration_args import normalize_orchestration_kwargs

logger = build_logger('all')


def run_subjob(job_name: str, **kwargs: object) -> dict[str, int]:
    """Backward-compatible wrapper for script-level subjob execution."""
    return orchestration_run_subjob(job_name, script_prefix='full_load', **kwargs)


def run_defined_jobs(args: Namespace) -> dict[str, dict[str, int]]:
    """Run shared full-load job specs while preserving local monkeypatch seam."""
    results: dict[str, dict[str, int]] = {}
    for job in FULL_LOAD_JOB_SPECS:
        results[job.name] = run_subjob(job.name, **job.kwargs_builder(args))
    return results


def parse_args(argv: list[str] | None = None) -> Namespace:
    """Parse CLI arguments for the orchestrated full-load workflow."""
    parser = argparse.ArgumentParser(description='Run all P0.8 full-load jobs.')
    add_date_range_arguments(parser)
    add_trade_date_argument(parser)
    add_ts_codes_argument(parser)
    parser.add_argument('--minute-ts-code')
    parser.add_argument('--minute-freq', default='5min')
    add_index_codes_argument(parser)
    add_concept_codes_argument(parser)
    add_industry_codes_argument(parser)
    parser.add_argument('--holdertrade-ts-code')
    parser.add_argument('--holdertrade-ann-date', type=parse_date)
    return parser.parse_args(argv)


def _run_from_args(args: Namespace) -> dict[str, dict[str, int]]:
    """Execute full-load jobs from a prepared argument namespace."""
    logger.info('Initializing storage before full load.')
    init_db_main([])
    logger.info('Starting orchestrated full load.')
    results = run_defined_jobs(args)
    logger.info('Full load orchestrator complete.')
    return results


def main(argv: list[str] | None = None) -> dict[str, dict[str, int]]:
    """Initialize storage and execute all full-load jobs in order."""
    return _run_from_args(parse_args(argv))


def run_job(**kwargs: object) -> dict[str, dict[str, int]]:
    """Programmatic entrypoint used by the scheduler."""
    return _run_from_args(normalize_orchestration_kwargs(dict(kwargs)))


if __name__ == '__main__':
    main()
