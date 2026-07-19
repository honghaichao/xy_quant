
"""Shared helpers for P0.8 full-load scripts."""

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


def add_date_range_arguments(parser: argparse.ArgumentParser) -> None:
    """Add start/end date arguments to a parser."""
    parser.add_argument('--start-date', type=parse_date, required=True)
    parser.add_argument('--end-date', type=parse_date, required=True)


def add_trade_date_argument(parser: argparse.ArgumentParser, *, required: bool = True) -> None:
    """Add trade-date argument to a parser."""
    parser.add_argument('--trade-date', type=parse_date, required=required)


def add_ts_codes_argument(parser: argparse.ArgumentParser, *, required: bool = True) -> None:
    """Add a comma-separated ts-code list argument."""
    parser.add_argument('--ts-codes', type=parse_csv_list, required=required)


def add_index_codes_argument(parser: argparse.ArgumentParser, *, required: bool = False) -> None:
    """Add a comma-separated index-code list argument."""
    parser.add_argument('--index-codes', type=parse_csv_list, required=required, default=[])


def add_concept_codes_argument(parser: argparse.ArgumentParser, *, required: bool = False) -> None:
    """Add a comma-separated concept-code list argument."""
    parser.add_argument('--concept-codes', type=parse_csv_list, required=required, default=[])


def add_industry_codes_argument(parser: argparse.ArgumentParser, *, required: bool = False) -> None:
    """Add a comma-separated industry-code list argument."""
    parser.add_argument('--industry-codes', type=parse_csv_list, required=required, default=[])


def run_updater_job(job_name: str, updater_cls: type[Any], kwargs: dict[str, Any], logger: Any) -> dict[str, int]:
    """Instantiate an updater, execute it, and emit standard logs."""
    logger.info(f'Starting full load: {job_name}.')
    updater = updater_cls()
    try:
        counts = cast(dict[str, int], updater.run(**kwargs))
        logger.info(f'Rows loaded: {counts}')
        logger.info(f'Full load complete: {job_name}.')
        return counts
    finally:
        updater.close()


def build_logger(job_name: str) -> Any:
    """Create a standard logger for a full-load job."""
    return get_logger(f'full_load_{job_name}')
