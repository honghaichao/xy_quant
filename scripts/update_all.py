# ruff: noqa: E402
"""Orchestrated incremental update entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
from argparse import Namespace

from config.settings import settings
from data.source.factory import get_data_source
from scripts.orchestration import INCREMENTAL_JOB_SPECS
from scripts.orchestration import run_subjob as orchestration_run_subjob
from scripts.orchestration_args import normalize_orchestration_namespace
from scripts.update_calendar import run_job as run_calendar_update
from scripts.update_helpers import (
    add_concept_codes_argument,
    add_date_range_arguments,
    add_index_codes_argument,
    add_industry_codes_argument,
    add_trade_date_argument,
    add_ts_codes_argument,
    build_logger,
)

logger = build_logger('all')


def _default_ts_codes() -> list[str]:
    """Load active stock codes for date-only CLI smoke runs."""
    frame = get_data_source(settings.primary_data_source).fetch_stock_basic()
    if 'ts_code' not in frame.columns:
        return []
    return [str(code) for code in frame['ts_code'].dropna().tolist()]


def _normalize_args(args: Namespace) -> Namespace:
    """Fill shorthand CLI defaults such as --date-only smoke runs."""
    normalized = normalize_orchestration_namespace(args)
    if getattr(normalized, 'start_date', None) is None and getattr(normalized, 'trade_date', None) is not None:
        normalized.start_date = normalized.trade_date
    if getattr(normalized, 'end_date', None) is None and getattr(normalized, 'trade_date', None) is not None:
        normalized.end_date = normalized.trade_date
    if not getattr(normalized, 'ts_codes', None):
        normalized.ts_codes = _default_ts_codes()
    return normalized


def run_subjob(job_name: str, **kwargs: object) -> dict[str, int]:
    """Backward-compatible wrapper for script-level subjob execution."""
    return orchestration_run_subjob(job_name, script_prefix='update', **kwargs)


def run_defined_jobs(args: Namespace) -> dict[str, dict[str, int]]:
    """Run shared incremental job specs while preserving local monkeypatch seam."""
    results: dict[str, dict[str, int]] = {}
    for job in INCREMENTAL_JOB_SPECS:
        results[job.name] = run_subjob(job.name, **job.kwargs_builder(args))
    return results


def parse_args(argv: list[str] | None = None) -> Namespace:
    """Parse CLI arguments for the orchestrated incremental workflow."""
    parser = argparse.ArgumentParser(description='Run all P0.9 incremental update jobs.')
    add_trade_date_argument(parser)
    add_date_range_arguments(parser, required=False)
    add_ts_codes_argument(parser, required=False)
    add_index_codes_argument(parser)
    add_concept_codes_argument(parser)
    add_industry_codes_argument(parser)
    return parser.parse_args(argv)


def _run_from_args(args: Namespace) -> dict[str, dict[str, int]]:
    """Execute the orchestrated incremental workflow."""
    logger.info('Starting orchestrated incremental update.')
    calendar_result = run_calendar_update(start_date=args.start_date, end_date=args.end_date)
    logger.info('Calendar pre-sync complete for orchestrated incremental update.')
    results = {'calendar': calendar_result, **run_defined_jobs(args)}
    logger.info('Incremental update orchestrator complete.')
    return results


def main(argv: list[str] | None = None) -> dict[str, dict[str, int]]:
    """Execute the orchestrated incremental workflow."""
    return _run_from_args(_normalize_args(parse_args(argv)))


def run_job(**kwargs: object) -> dict[str, dict[str, int]]:
    """Programmatic entrypoint used by the scheduler."""
    return _run_from_args(_normalize_args(Namespace(**kwargs)))


if __name__ == '__main__':
    main()
