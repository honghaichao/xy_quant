
"""Shared helpers for P0.9 update scripts."""

from __future__ import annotations

import argparse
from datetime import date
from typing import Any, cast

from utils.logger import get_logger


def parse_date(value: str) -> date:
    """Parse an ISO date string for CLI arguments."""
    return date.fromisoformat(value)


def parse_csv_list(value: str | None) -> list[str]:
    """Parse a comma-separated CLI argument into a list of non-empty strings."""
    if value is None:
        return []
    return [item.strip() for item in value.split(',') if item.strip()]


def add_date_range_arguments(parser: argparse.ArgumentParser, *, required: bool = True) -> None:
    parser.add_argument('--start-date', '--start', dest='start_date', type=parse_date, required=required)
    parser.add_argument('--end-date', '--end', dest='end_date', type=parse_date, required=required)


def add_trade_date_argument(parser: argparse.ArgumentParser, *, required: bool = True) -> None:
    parser.add_argument('--trade-date', '--date', dest='trade_date', type=parse_date, required=required)


def add_ts_codes_argument(parser: argparse.ArgumentParser, *, required: bool = True) -> None:
    parser.add_argument('--ts-codes', type=parse_csv_list, required=required, default=[])


def add_index_codes_argument(parser: argparse.ArgumentParser, *, required: bool = False) -> None:
    parser.add_argument('--index-codes', type=parse_csv_list, required=required, default=[])


def add_concept_codes_argument(parser: argparse.ArgumentParser, *, required: bool = False) -> None:
    parser.add_argument('--concept-codes', type=parse_csv_list, required=required, default=[])


def add_industry_codes_argument(parser: argparse.ArgumentParser, *, required: bool = False) -> None:
    parser.add_argument('--industry-codes', type=parse_csv_list, required=required, default=[])


def add_progress_file_argument(
    parser: argparse.ArgumentParser,
    *,
    default: str | None = None,
    help_text: str = 'Append JSONL progress records to this file.',
) -> None:
    parser.add_argument('--progress-file', default=default, help=help_text)


def run_updater_job(job_name: str, updater_cls: type[Any], kwargs: dict[str, Any], logger: Any) -> dict[str, int]:
    logger.info(f'Starting incremental update: {job_name}.')
    updater = updater_cls()
    try:
        counts = cast(dict[str, int], updater.run(**kwargs))
        logger.info(f'Rows loaded: {counts}')
        logger.info(f'Incremental update complete: {job_name}.')
        return counts
    finally:
        updater.close()


def build_logger(job_name: str) -> Any:
    return get_logger(f'update_{job_name}')
