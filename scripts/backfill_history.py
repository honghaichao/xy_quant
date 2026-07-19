# ruff: noqa: E402
"""Backfill all P0 data across a trading-date history range."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import json
from argparse import Namespace
from datetime import date, datetime, timezone
from pathlib import Path as StdPath
from typing import Any

from config.settings import settings
from data.source.factory import get_data_source
from scripts import backfill_day
from scripts.update_helpers import (
    add_concept_codes_argument,
    add_date_range_arguments,
    add_index_codes_argument,
    add_industry_codes_argument,
    add_progress_file_argument,
    add_ts_codes_argument,
    build_logger,
)

DEFAULT_PROGRESS_FILE = PROJECT_ROOT / 'logs' / 'backfill_history_progress.jsonl'
logger = build_logger('backfill_history')


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_progress(progress_file: StdPath | None, payload: dict[str, Any]) -> None:
    if progress_file is None:
        return
    progress_file.parent.mkdir(parents=True, exist_ok=True)
    with progress_file.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + '\n')


def _as_trade_dates(frame: Any) -> list[date]:
    if getattr(frame, 'empty', True):
        return []
    open_col = 'is_open' if 'is_open' in frame.columns else None
    date_col = 'cal_date' if 'cal_date' in frame.columns else None
    if date_col is None:
        return []
    filtered = frame
    if open_col is not None:
        filtered = frame.loc[frame[open_col].astype(str) == '1']
    values: list[date] = []
    for raw in filtered[date_col].tolist():
        text = str(raw)
        if len(text) == 8 and text.isdigit():
            values.append(date.fromisoformat(f'{text[:4]}-{text[4:6]}-{text[6:8]}'))
        else:
            values.append(date.fromisoformat(text))
    return sorted(set(values))


def _load_trade_dates(start_date: date, end_date: date) -> list[date]:
    data_source = get_data_source(settings.primary_data_source)
    frame = data_source.fetch_trade_calendar(start_date=start_date, end_date=end_date)
    return _as_trade_dates(frame)


def _read_completed_dates(progress_file: StdPath | None) -> set[date]:
    if progress_file is None or not progress_file.exists():
        return set()
    completed: set[date] = set()
    for line in progress_file.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get('event') != 'completed':
            continue
        trade_date = payload.get('trade_date')
        if not trade_date:
            continue
        completed.add(date.fromisoformat(str(trade_date)))
    return completed


def _normalize_args(args: Namespace) -> Namespace:
    normalized = Namespace(**vars(args))
    if normalized.progress_file:
        normalized.progress_file = StdPath(str(normalized.progress_file))
    else:
        normalized.progress_file = None
    if getattr(normalized, 'resume', False):
        normalized.completed_dates = _read_completed_dates(normalized.progress_file)
    else:
        normalized.completed_dates = set()
    return normalized


def parse_args(argv: list[str] | None = None) -> Namespace:
    parser = argparse.ArgumentParser(description='Backfill all P0 data across a trading-date history range.')
    add_date_range_arguments(parser, required=True)
    add_ts_codes_argument(parser, required=False)
    add_index_codes_argument(parser, required=False)
    add_concept_codes_argument(parser, required=False)
    add_industry_codes_argument(parser, required=False)
    add_progress_file_argument(parser, default=str(DEFAULT_PROGRESS_FILE))
    parser.add_argument('--resume', action='store_true', help='Skip trade dates already marked completed in the progress log.')
    parser.add_argument('--stop-on-error', action='store_true', help='Abort immediately when a trade date backfill fails.')
    return parser.parse_args(argv)


def _run_trade_date(trade_date: date, args: Namespace) -> dict[str, dict[str, int]]:
    return backfill_day.run_job(
        trade_date=trade_date,
        start_date=trade_date,
        end_date=trade_date,
        ts_codes=args.ts_codes,
        index_codes=args.index_codes,
        concept_codes=args.concept_codes,
        industry_codes=args.industry_codes,
    )


def _serialize_error(error: Exception) -> str:
    return f'{type(error).__name__}: {error}'


def _run_from_args(args: Namespace) -> dict[str, Any]:
    normalized = _normalize_args(args)
    trade_dates = _load_trade_dates(normalized.start_date, normalized.end_date)
    pending_dates = [d for d in trade_dates if d not in normalized.completed_dates]
    _append_progress(
        normalized.progress_file,
        {
            'event': 'started',
            'timestamp': _utc_now_iso(),
            'start_date': normalized.start_date.isoformat(),
            'end_date': normalized.end_date.isoformat(),
            'trade_dates': len(trade_dates),
            'pending_dates': len(pending_dates),
            'resume': bool(getattr(normalized, 'resume', False)),
        },
    )
    logger.info('Starting history backfill.')
    completed = 0
    failed = 0
    failures: list[dict[str, str]] = []
    for trade_date in pending_dates:
        _append_progress(
            normalized.progress_file,
            {'event': 'running', 'timestamp': _utc_now_iso(), 'trade_date': trade_date.isoformat()},
        )
        try:
            result = _run_trade_date(trade_date, normalized)
            completed += 1
            _append_progress(
                normalized.progress_file,
                {
                    'event': 'completed',
                    'timestamp': _utc_now_iso(),
                    'trade_date': trade_date.isoformat(),
                    'result': result,
                },
            )
        except Exception as exc:
            failed += 1
            failure = {'trade_date': trade_date.isoformat(), 'error': _serialize_error(exc)}
            failures.append(failure)
            _append_progress(
                normalized.progress_file,
                {'event': 'failed', 'timestamp': _utc_now_iso(), **failure},
            )
            if normalized.stop_on_error:
                logger.exception('History backfill aborted on trade date %s.', trade_date.isoformat())
                raise
    summary = {
        'trade_dates': len(trade_dates),
        'pending_dates': len(pending_dates),
        'completed_dates': completed,
        'failed_dates': failed,
        'failures': failures,
    }
    _append_progress(normalized.progress_file, {'event': 'summary', 'timestamp': _utc_now_iso(), **summary})
    logger.info('History backfill complete.')
    return summary


def main(argv: list[str] | None = None) -> dict[str, Any]:
    return _run_from_args(parse_args(argv))


def run_job(**kwargs: object) -> dict[str, Any]:
    return _run_from_args(Namespace(**kwargs))


if __name__ == '__main__':
    main()
