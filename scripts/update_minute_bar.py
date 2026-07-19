# ruff: noqa: E402
"""Incremental update script for minute_bar."""

from __future__ import annotations

import json
import sys
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse

from config.settings import settings
from data.updater import MinuteBarUpdater
from scripts.update_helpers import (
    add_date_range_arguments,
    add_progress_file_argument,
    build_logger,
    run_updater_job,
)

logger = build_logger('minute_bar')


def parse_args() -> Namespace:
    """Parse CLI arguments for the minute_bar update script."""
    parser = argparse.ArgumentParser(description='Update minute_bar.')
    parser.add_argument('--ts-code', required=True)
    add_date_range_arguments(parser)
    parser.add_argument('--freq', default='1min')
    add_progress_file_argument(parser, default=str(Path(settings.log_dir_path) / 'minute_bar_progress.jsonl'))
    return parser.parse_args()


def build_run_kwargs(args: Namespace) -> dict[str, object]:
    """Convert CLI arguments into updater.run keyword arguments."""
    return {'ts_code': args.ts_code, 'start_date': args.start_date, 'end_date': args.end_date, 'freq': args.freq}


def _write_progress_record(progress_file: str | None, payload: dict[str, object]) -> None:
    """Append a single JSONL progress record when a progress file is configured."""
    if not progress_file:
        return
    path = Path(progress_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    with path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str))
        handle.write('\n')


def main() -> dict[str, int]:
    """Run the minute_bar incremental update job."""
    args = parse_args()
    run_kwargs = build_run_kwargs(args)
    _write_progress_record(args.progress_file, {'job': 'minute_bar', 'event': 'started', 'run_kwargs': run_kwargs})
    try:
        counts = run_updater_job('minute_bar', MinuteBarUpdater, run_kwargs, logger)
    except Exception as exc:
        _write_progress_record(
            args.progress_file,
            {'job': 'minute_bar', 'event': 'failed', 'run_kwargs': run_kwargs, 'error': repr(exc)},
        )
        raise
    _write_progress_record(
        args.progress_file,
        {'job': 'minute_bar', 'event': 'completed', 'run_kwargs': run_kwargs, 'counts': counts},
    )
    return counts


def run_job(**kwargs: object) -> dict[str, int]:
    """Programmatic entrypoint used by the incremental orchestrator."""
    return run_updater_job('minute_bar', MinuteBarUpdater, dict(kwargs), logger)


if __name__ == '__main__':
    main()
