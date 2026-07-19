# ruff: noqa: E402
"""Full-load script for minute_bar."""

from __future__ import annotations

import json
import sys
from argparse import Namespace
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from math import isnan
from pathlib import Path
from threading import Lock
from typing import Any

import argparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from data.source.factory import get_data_source
from data.updater import MinuteBarUpdater
from scripts.full_load_helpers import (
    add_date_range_arguments,
    add_ts_codes_argument,
    build_logger,
    run_updater_job,
)

logger = build_logger('minute_bar')
COMPACT_YYYYMMDD_LENGTH = 8
JOB_WAIT_TIMEOUT_SECONDS = 5


class _ManifestWriteLock:
    def __init__(self) -> None:
        self._lock = Lock()

    def write_json(self, path: str | None, payload: dict[str, object]) -> None:
        if not path:
            return
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding='utf-8')


_MANIFEST_WRITE_LOCK = _ManifestWriteLock()


def parse_args() -> Namespace:
    """Parse CLI arguments for the minute_bar full-load script."""
    parser = argparse.ArgumentParser(description='Full load minute_bar.')
    parser.add_argument('--ts-code')
    add_ts_codes_argument(parser, required=False)
    add_date_range_arguments(parser)
    parser.add_argument('--freq', default='1min')
    parser.add_argument('--batch-run', action='store_true', help='Run codes in single-process batches using updater threads.')
    parser.add_argument('--missing-only', action='store_true', help='Only run stocks with missing trade days after listing.')
    parser.add_argument('--workers', type=int, default=20, help='Updater-internal worker count for minute-bar fetch concurrency.')
    parser.add_argument('--queue-workers', type=int, default=1, help='Outer gap-job queue worker count.')
    parser.add_argument('--shards', type=int, default=1, help='Logical shard count for planned gap jobs.')
    parser.add_argument('--plan-only', action='store_true', help='Only build the minute_bar gap manifest without executing jobs.')
    parser.add_argument('--manifest-file', default=None, help='Write the planned/updated gap manifest JSON to this path.')
    parser.add_argument('--max-gap-jobs', type=int, default=None, help='Optional cap on planned gap jobs for debugging or dry runs.')
    parser.add_argument('--chunk-size', type=int, default=1, help='Number of ts_codes per in-process batch.')
    return parser.parse_args()


def build_run_kwargs(args: Namespace) -> dict[str, object]:
    """Convert CLI arguments into updater.run keyword arguments."""
    kwargs: dict[str, object] = {
        'start_date': args.start_date,
        'end_date': args.end_date,
        'freq': args.freq,
    }
    if getattr(args, 'ts_code', None) is not None:
        kwargs['ts_code'] = args.ts_code
    else:
        kwargs['ts_codes'] = getattr(args, 'ts_codes', [])
    return kwargs


def _write_progress_record(progress_file: str | None, payload: dict[str, object]) -> None:
    if not progress_file:
        return
    path = Path(progress_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {'timestamp': datetime.now(timezone.utc).isoformat(), **payload}
    with path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str))
        handle.write('\n')


def _coerce_yyyymmdd_date(value: object) -> date | None:
    if value is None or (isinstance(value, float) and isnan(value)):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        candidate = value.strip()
        if candidate:
            return (
                datetime.strptime(candidate, '%Y%m%d').date()
                if len(candidate) == COMPACT_YYYYMMDD_LENGTH and candidate.isdigit()
                else date.fromisoformat(candidate)
            )
    return None


def _eligible_codes_for_range(stock_basic: Any, start_date: date, end_date: date) -> list[str]:
    if stock_basic.empty or 'ts_code' not in stock_basic.columns:
        return []
    if 'list_date' not in stock_basic.columns and 'delist_date' not in stock_basic.columns:
        return [code for code in stock_basic.get('ts_code', []).tolist() if isinstance(code, str) and code]
    eligible_codes: list[str] = []
    for row in stock_basic.itertuples(index=False):
        ts_code = getattr(row, 'ts_code', None)
        if not isinstance(ts_code, str) or not ts_code:
            continue
        list_date = _coerce_yyyymmdd_date(getattr(row, 'list_date', None))
        delist_date = _coerce_yyyymmdd_date(getattr(row, 'delist_date', None))
        if list_date is not None and list_date > end_date:
            continue
        if delist_date is not None and delist_date < start_date:
            continue
        eligible_codes.append(ts_code)
    return eligible_codes


def _normalize_requested_codes(updater: MinuteBarUpdater, run_kwargs: dict[str, Any]) -> list[str]:
    ts_code = run_kwargs.get('ts_code')
    if isinstance(ts_code, str) and ts_code:
        return [ts_code]
    ts_codes = run_kwargs.get('ts_codes')
    if isinstance(ts_codes, list) and ts_codes:
        return [code for code in ts_codes if isinstance(code, str) and code]
    stock_basic = updater.source.fetch_stock_basic()
    return _eligible_codes_for_range(stock_basic, run_kwargs['start_date'], run_kwargs['end_date'])


def _require_date(value: object, field_name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f'{field_name} must be a date, got {type(value).__name__}')


def _extract_trade_days(updater: MinuteBarUpdater, start_date: date, end_date: date) -> int:
    return len(_extract_open_trade_days(updater, start_date, end_date))


def _extract_open_trade_days(updater: MinuteBarUpdater, start_date: date, end_date: date) -> list[date]:
    calendar = updater.source.fetch_trade_calendar(start_date, end_date)
    if calendar.empty:
        return []
    opened = calendar.loc[calendar['is_open'].astype(int) == 1] if 'is_open' in calendar.columns else calendar
    if 'cal_date' in opened.columns:
        raw_dates = opened['cal_date'].tolist()
    elif 'trade_date' in opened.columns:
        raw_dates = opened['trade_date'].tolist()
    else:
        raw_dates = []
    trade_days: list[date] = []
    for value in raw_dates:
        normalized = _coerce_yyyymmdd_date(value)
        if normalized is not None:
            trade_days.append(normalized)
    return trade_days


def _listing_bounds_by_code(stock_basic: Any) -> dict[str, tuple[date | None, date | None]]:
    if stock_basic.empty or 'ts_code' not in stock_basic.columns:
        return {}
    bounds: dict[str, tuple[date | None, date | None]] = {}
    for row in stock_basic.itertuples(index=False):
        ts_code = getattr(row, 'ts_code', None)
        if not isinstance(ts_code, str) or not ts_code:
            continue
        bounds[ts_code] = (
            _coerce_yyyymmdd_date(getattr(row, 'list_date', None)),
            _coerce_yyyymmdd_date(getattr(row, 'delist_date', None)),
        )
    return bounds


def _eligible_trade_days_for_code(
    ts_code: str,
    trade_days: list[date],
    listing_bounds: dict[str, tuple[date | None, date | None]],
) -> list[date]:
    list_date, delist_date = listing_bounds.get(ts_code, (None, None))
    return [
        trade_day
        for trade_day in trade_days
        if (list_date is None or trade_day >= list_date)
        and (delist_date is None or trade_day <= delist_date)
    ]


def _load_present_trade_days(
    market_store: Any,
    start_date: date,
    end_date: date,
    requested_codes: list[str],
) -> dict[str, set[date]]:
    if not requested_codes:
        return {}
    if hasattr(market_store, 'connection'):
        query_executor = market_store.connection
        query = (
            'SELECT ts_code, CAST(datetime AS DATE) AS dt '
            'FROM minute_bar '
            'WHERE CAST(datetime AS DATE) BETWEEN ? AND ? '
            f'  AND ts_code IN ({", ".join("?" for _ in requested_codes)}) '
            'GROUP BY ts_code, dt'
        )
        frame = query_executor.execute(query, [start_date, end_date, *requested_codes]).fetch_df()
    else:
        query = (
            'SELECT ts_code, CAST(datetime AS DATE) AS dt '
            'FROM minute_bar '
            'WHERE CAST(datetime AS DATE) BETWEEN $start_date AND $end_date '
            'GROUP BY ts_code, dt'
        )
        frame = market_store.query(query, {'start_date': start_date, 'end_date': end_date})
        if not frame.empty and 'ts_code' in frame.columns:
            frame = frame[frame['ts_code'].isin(requested_codes)]
    if frame.empty:
        return {}
    present_by_code: dict[str, set[date]] = {}
    date_col = 'dt' if 'dt' in frame.columns else 'day_count' if 'day_count' in frame.columns else None
    if date_col is None:
        return {}
    for ts_code, loaded_date in frame[['ts_code', date_col]].itertuples(index=False, name=None):
        if not isinstance(ts_code, str) or not ts_code:
            continue
        normalized = _coerce_yyyymmdd_date(loaded_date)
        if normalized is None:
            continue
        present_by_code.setdefault(ts_code, set()).add(normalized)
    return present_by_code


def _group_contiguous_trade_day_ranges(
    ordered_reference_trade_days: list[date],
    target_trade_days: list[date],
) -> list[tuple[date, date]]:
    if not target_trade_days:
        return []
    unique_target_days = sorted(set(target_trade_days))
    reference_positions = {
        trade_day: index for index, trade_day in enumerate(sorted(set(ordered_reference_trade_days)))
    }
    ranges: list[tuple[date, date]] = []
    range_start = unique_target_days[0]
    range_end = unique_target_days[0]
    previous_position = reference_positions[range_end]
    for trade_day in unique_target_days[1:]:
        current_position = reference_positions[trade_day]
        if current_position == previous_position + 1:
            range_end = trade_day
        else:
            ranges.append((range_start, range_end))
            range_start = trade_day
            range_end = trade_day
        previous_position = current_position
    ranges.append((range_start, range_end))
    return ranges


def _collect_gap_backfill_details(updater: MinuteBarUpdater, run_kwargs: dict[str, Any]) -> dict[str, Any]:
    start_date = _require_date(run_kwargs['start_date'], 'start_date')
    end_date = _require_date(run_kwargs['end_date'], 'end_date')
    requested_codes = _normalize_requested_codes(updater, run_kwargs)
    trade_days = _extract_open_trade_days(updater, start_date, end_date)
    if not trade_days:
        return {
            'requested_codes': requested_codes,
            'pending_codes': [],
            'skipped_codes': requested_codes,
            'target_trade_days': 0,
            'gap_ranges': 0,
            'missing_trade_days': 0,
            'jobs': [],
        }

    stock_basic = updater.source.fetch_stock_basic()
    listing_bounds = _listing_bounds_by_code(stock_basic)
    if hasattr(updater, 'market_store'):
        present_by_code = _load_present_trade_days(updater.market_store, start_date, end_date, requested_codes)
    else:
        present_by_code = {ts_code: set() for ts_code in requested_codes}
    pending_codes: list[str] = []
    skipped_codes: list[str] = []
    jobs: list[dict[str, Any]] = []
    missing_trade_days = 0

    for ts_code in requested_codes:
        eligible_trade_days = _eligible_trade_days_for_code(ts_code, trade_days, listing_bounds)
        present_trade_days = present_by_code.get(ts_code, set())
        missing_days = [trade_day for trade_day in eligible_trade_days if trade_day not in present_trade_days]
        if not missing_days:
            skipped_codes.append(ts_code)
            continue
        pending_codes.append(ts_code)
        missing_trade_days += len(missing_days)
        contiguous_ranges = _group_contiguous_trade_day_ranges(eligible_trade_days, missing_days)
        for gap_start, gap_end in contiguous_ranges:
            gap_kwargs = dict(run_kwargs)
            gap_kwargs.pop('ts_codes', None)
            gap_kwargs['ts_code'] = ts_code
            gap_kwargs['start_date'] = gap_start
            gap_kwargs['end_date'] = gap_end
            jobs.append(gap_kwargs)

    return {
        'requested_codes': requested_codes,
        'pending_codes': pending_codes,
        'skipped_codes': skipped_codes,
        'target_trade_days': len(trade_days),
        'gap_ranges': len(jobs),
        'missing_trade_days': missing_trade_days,
        'jobs': jobs,
    }


def _build_gap_backfill_jobs(updater: MinuteBarUpdater, run_kwargs: dict[str, Any]) -> list[dict[str, Any]]:
    return _collect_gap_backfill_details(updater, run_kwargs)['jobs']


def _serialize_job(job: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in job.items():
        payload[key] = value.isoformat() if isinstance(value, date) else value
    return payload


def _estimate_job_cost(job: dict[str, Any]) -> int:
    start_date = _require_date(job['start_date'], 'start_date')
    end_date = _require_date(job['end_date'], 'end_date')
    return (end_date - start_date).days + 1


def _add_job_metadata(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_jobs: list[dict[str, Any]] = []
    for index, job in enumerate(jobs, start=1):
        normalized = dict(job)
        start_date = _require_date(normalized['start_date'], 'start_date')
        end_date = _require_date(normalized['end_date'], 'end_date')
        ts_code = str(normalized.get('ts_code', ''))
        freq = str(normalized.get('freq', '1min'))
        normalized['job_index'] = index
        normalized['job_id'] = f'{ts_code}:{start_date.isoformat()}:{end_date.isoformat()}:{freq}'
        normalized['estimated_cost'] = _estimate_job_cost(normalized)
        normalized_jobs.append(normalized)
    return normalized_jobs


def _plan_gap_backfill_jobs(
    updater: MinuteBarUpdater,
    run_kwargs: dict[str, Any],
    *,
    shard_count: int = 1,
    max_gap_jobs: int | None = None,
) -> dict[str, Any]:
    details = _collect_gap_backfill_details(updater, run_kwargs)
    jobs = _add_job_metadata(list(details['jobs']))
    if max_gap_jobs is not None:
        jobs = jobs[:max(0, max_gap_jobs)]
    jobs_by_code: dict[str, list[dict[str, Any]]] = {}
    for job in jobs:
        jobs_by_code.setdefault(str(job['ts_code']), []).append(job)
    shards = _shard_gap_jobs(jobs, shard_count)
    return {
        **details,
        'jobs': jobs,
        'jobs_by_code': jobs_by_code,
        'job_count_by_code': {code: len(code_jobs) for code, code_jobs in jobs_by_code.items()},
        'job_count': len(jobs),
        'shard_count': len(shards),
        'shards': shards,
    }


def _shard_gap_jobs(jobs: list[dict[str, Any]], shard_count: int) -> list[dict[str, Any]]:
    normalized_shard_count = max(1, shard_count)
    if not jobs:
        return [
            {
                'shard_id': shard_index,
                'jobs': [],
                'job_count': 0,
                'estimated_cost': 0,
            }
            for shard_index in range(1, normalized_shard_count + 1)
        ]
    shard_buckets = [
        {
            'shard_id': shard_index,
            'jobs': [],
            'job_count': 0,
            'estimated_cost': 0,
        }
        for shard_index in range(1, normalized_shard_count + 1)
    ]
    ordered_jobs = sorted(
        jobs,
        key=lambda item: (
            -int(item.get('estimated_cost', 0)),
            str(item.get('ts_code', '')),
            _require_date(item['start_date'], 'start_date'),
            _require_date(item['end_date'], 'end_date'),
        ),
    )
    for job in ordered_jobs:
        shard = min(shard_buckets, key=lambda item: (int(item['estimated_cost']), int(item['job_count']), int(item['shard_id'])))
        shard['jobs'].append(job)
        shard['job_count'] = int(shard['job_count']) + 1
        shard['estimated_cost'] = int(shard['estimated_cost']) + int(job.get('estimated_cost', 0))
    return shard_buckets


def _write_manifest(path: str | None, payload: dict[str, object]) -> None:
    _MANIFEST_WRITE_LOCK.write_json(path, payload)


def _manifest_payload_from_plan(plan: dict[str, Any]) -> dict[str, object]:
    return {
        'requested_codes': list(plan.get('requested_codes', [])),
        'pending_codes': list(plan.get('pending_codes', [])),
        'skipped_codes': list(plan.get('skipped_codes', [])),
        'target_trade_days': int(plan.get('target_trade_days', 0)),
        'gap_ranges': int(plan.get('gap_ranges', 0)),
        'missing_trade_days': int(plan.get('missing_trade_days', 0)),
        'job_count': int(plan.get('job_count', 0)),
        'job_count_by_code': dict(plan.get('job_count_by_code', {})),
        'jobs': [_serialize_job(job) for job in plan.get('jobs', [])],
        'shard_count': int(plan.get('shard_count', 0)),
        'shards': [
            {
                'shard_id': int(shard['shard_id']),
                'job_count': int(shard['job_count']),
                'estimated_cost': int(shard['estimated_cost']),
                'jobs': [_serialize_job(job) for job in shard['jobs']],
            }
            for shard in plan.get('shards', [])
        ],
    }


def _loaded_trade_day_counts(updater: MinuteBarUpdater, start_date: date, end_date: date) -> dict[str, int]:
    start_bound = datetime.combine(start_date, datetime.min.time())
    end_exclusive = datetime.combine(end_date, datetime.min.time()) + timedelta(days=1)
    query = (
        'SELECT ts_code, COUNT(DISTINCT CAST(datetime AS DATE)) AS day_count '
        'FROM minute_bar '
        'WHERE datetime >= $start_bound '
        '  AND datetime < $end_exclusive '
        'GROUP BY ts_code'
    )
    frame = updater.market_store.query(query, {'start_bound': start_bound, 'end_exclusive': end_exclusive})
    if frame.empty:
        return {}
    return {str(ts_code): int(day_count) for ts_code, day_count in frame[['ts_code', 'day_count']].itertuples(index=False, name=None) if isinstance(ts_code, str) and ts_code}


def _filter_pending_codes(updater: MinuteBarUpdater, run_kwargs: dict[str, Any]) -> tuple[list[str], list[str], int]:
    start_date = _require_date(run_kwargs['start_date'], 'start_date')
    end_date = _require_date(run_kwargs['end_date'], 'end_date')
    requested_codes = _normalize_requested_codes(updater, run_kwargs)
    target_trade_days = _extract_trade_days(updater, start_date, end_date)
    if target_trade_days <= 0:
        return requested_codes, [], 0
    loaded_counts = _loaded_trade_day_counts(updater, start_date, end_date)
    pending, skipped = [], []
    for ts_code in requested_codes:
        if loaded_counts.get(ts_code, 0) >= target_trade_days:
            skipped.append(ts_code)
        else:
            pending.append(ts_code)
    return pending, skipped, target_trade_days


def _run_gap_job(
    job: dict[str, Any],
    progress_file: str | None,
    workers: int,
    updater_factory: Any = MinuteBarUpdater,
    updater: MinuteBarUpdater | None = None,
) -> dict[str, Any]:
    owned_updater = updater is None
    active_updater = updater if updater is not None else updater_factory()
    try:
        run_kwargs = {
            key: value
            for key, value in job.items()
            if key in {'ts_code', 'ts_codes', 'start_date', 'end_date', 'freq'}
        }
        with _override_minute_bar_workers(workers):
            counts = active_updater.run(**run_kwargs)
        _write_progress_record(progress_file, {
            'job': 'minute_bar',
            'event': 'gap_job_completed',
            'job_id': job.get('job_id'),
            'job_index': job.get('job_index'),
            'ts_code': job.get('ts_code'),
            'counts': counts,
        })
        return {
            'job': job,
            'counts': counts,
            'returncode': 0,
            'error': None,
        }
    except Exception as exc:
        _write_progress_record(progress_file, {
            'job': 'minute_bar',
            'event': 'gap_job_failed',
            'job_id': job.get('job_id'),
            'job_index': job.get('job_index'),
            'ts_code': job.get('ts_code'),
            'error': repr(exc),
        })
        return {
            'job': job,
            'counts': {},
            'returncode': 1,
            'error': repr(exc),
        }
    finally:
        if owned_updater:
            active_updater.close()


def _run_shard_jobs(
    shard: dict[str, Any],
    *,
    progress_file: str | None,
    workers: int,
    updater_factory: Any = MinuteBarUpdater,
) -> dict[str, Any]:
    shard_id = int(shard['shard_id'])
    updater = updater_factory()
    try:
        updater.market_store.init_schema()
        results: list[dict[str, Any]] = []
        counts: dict[str, int] = {}
        succeeded = 0
        failed = 0
        for job in shard['jobs']:
            _write_progress_record(progress_file, {
                'job': 'minute_bar',
                'event': 'gap_job_started',
                'shard_id': shard_id,
                'job_id': job.get('job_id'),
                'job_index': job.get('job_index'),
                'ts_code': job.get('ts_code'),
                'start_date': job.get('start_date'),
                'end_date': job.get('end_date'),
                'estimated_cost': job.get('estimated_cost'),
            })
            result = _run_gap_job(job, progress_file, workers, updater_factory=updater_factory, updater=updater)
            results.append(result)
            if int(result.get('returncode', 1)) == 0:
                succeeded += 1
            else:
                failed += 1
            for key, value in result.get('counts', {}).items():
                counts[key] = counts.get(key, 0) + int(value)
        return {
            'shard_summary': {
                'shard_id': shard_id,
                'job_count': int(shard['job_count']),
                'estimated_cost': int(shard['estimated_cost']),
                'succeeded': succeeded,
                'failed': failed,
                'counts': counts,
            },
            'results': results,
        }
    finally:
        updater.close()


def _merge_shard_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    failed_jobs: list[dict[str, Any]] = []
    completed_jobs: list[dict[str, Any]] = []
    shard_summaries: list[dict[str, Any]] = []
    for result in results:
        shard_summary = result.get('shard_summary')
        if isinstance(shard_summary, dict):
            shard_summaries.append(shard_summary)
        for item in result.get('results', []):
            completed_jobs.append(item)
            if int(item.get('returncode', 1)) != 0:
                failed_jobs.append(item)
            for key, value in item.get('counts', {}).items():
                counts[key] = counts.get(key, 0) + int(value)
    return {
        'counts': counts,
        'failed_jobs': failed_jobs,
        'completed_jobs': completed_jobs,
        'shard_summaries': shard_summaries,
        'succeeded_jobs': len(completed_jobs) - len(failed_jobs),
        'failed_job_count': len(failed_jobs),
    }


def _write_shard_artifact(base_dir: Path, shard: dict[str, Any], results: list[dict[str, Any]]) -> Path:
    base_dir.mkdir(parents=True, exist_ok=True)
    shard_path = base_dir / f'shard_{int(shard["shard_id"]):04d}.json'
    payload = {
        'shard_id': int(shard['shard_id']),
        'job_count': int(shard['job_count']),
        'estimated_cost': int(shard['estimated_cost']),
        'jobs': [_serialize_job(job) for job in shard['jobs']],
        'results': [
            {
                'job': _serialize_job(item['job']),
                'counts': item.get('counts', {}),
                'returncode': int(item.get('returncode', 1)),
                'error': item.get('error'),
            }
            for item in results
        ],
    }
    shard_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding='utf-8')
    return shard_path


def _load_shard_artifacts(base_dir: Path) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    if not base_dir.exists():
        return artifacts
    for path in sorted(base_dir.glob('shard_*.json')):
        artifacts.append(json.loads(path.read_text(encoding='utf-8')))
    return artifacts


def _execute_gap_jobs(
    shards: list[dict[str, Any]],
    *,
    progress_file: str | None,
    manifest_file: str | None,
    queue_workers: int,
    workers: int,
    shard_output_dir: str | None = None,
) -> dict[str, Any]:
    normalized_queue_workers = max(1, int(queue_workers))
    output_dir = Path(shard_output_dir) if shard_output_dir else None
    for shard in shards:
        _write_progress_record(progress_file, {
            'job': 'minute_bar',
            'event': 'shard_started',
            'shard_id': int(shard['shard_id']),
            'job_count': int(shard['job_count']),
            'estimated_cost': int(shard['estimated_cost']),
        })
    future_to_shard: dict[Future[dict[str, Any]], dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=normalized_queue_workers) as executor:
        for shard in shards:
            future = executor.submit(
                _run_shard_jobs,
                shard,
                progress_file=progress_file,
                workers=workers,
            )
            future_to_shard[future] = shard
        shard_results: list[dict[str, Any]] = []
        while future_to_shard:
            done, _ = wait(tuple(future_to_shard), timeout=JOB_WAIT_TIMEOUT_SECONDS, return_when=FIRST_COMPLETED)
            if not done:
                continue
            for future in done:
                shard = future_to_shard.pop(future)
                shard_result = future.result()
                shard_summary = shard_result['shard_summary']
                _write_progress_record(progress_file, {
                    'job': 'minute_bar',
                    'event': 'shard_completed',
                    'shard_id': shard_summary['shard_id'],
                    'job_count': shard_summary['job_count'],
                    'succeeded': shard_summary['succeeded'],
                    'failed': shard_summary['failed'],
                    'counts': shard_summary['counts'],
                })
                if output_dir is not None:
                    _write_shard_artifact(output_dir, shard, list(shard_result['results']))
                shard_results.append(shard_result)
    merged = _merge_shard_results(shard_results)
    if output_dir is not None:
        (output_dir / 'merged.json').write_text(json.dumps(merged, ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding='utf-8')
    _write_progress_record(progress_file, {
        'job': 'minute_bar',
        'event': 'merge_completed',
        'counts': merged['counts'],
        'succeeded_jobs': merged['succeeded_jobs'],
        'failed_job_count': merged['failed_job_count'],
    })
    if manifest_file:
        _write_manifest(manifest_file, {
            'status': 'completed',
            'counts': merged['counts'],
            'failed_job_count': merged['failed_job_count'],
            'succeeded_jobs': merged['succeeded_jobs'],
            'failed_jobs': [
                {
                    'job': _serialize_job(item['job']),
                    'error': item.get('error'),
                }
                for item in merged['failed_jobs']
            ],
            'shard_summaries': merged['shard_summaries'],
        })
    return merged

def _run_job(run_kwargs: dict[str, Any], progress_file: str | None) -> dict[str, int]:
    updater = MinuteBarUpdater()
    try:
        updater.market_store.init_schema()
        plan = _plan_gap_backfill_jobs(updater, run_kwargs)
        requested_codes = plan['requested_codes']
        pending_codes = plan['pending_codes']
        skipped_codes = plan['skipped_codes']
        target_trade_days = plan['target_trade_days']
        jobs = plan['jobs']
        logger.info(
            f"minute_bar resume scan: requested={len(requested_codes)} pending={len(pending_codes)} "
            f"skipped={len(skipped_codes)} trade_days={target_trade_days} "
            f"gap_ranges={plan['gap_ranges']} missing_trade_days={plan['missing_trade_days']}"
        )
        _write_progress_record(progress_file, {
            'job': 'minute_bar', 'event': 'filtered', 'target_trade_days': target_trade_days,
            'requested_count': len(requested_codes), 'pending_count': len(pending_codes),
            'skipped_count': len(skipped_codes), 'skipped_ts_codes': skipped_codes,
            'gap_range_count': plan['gap_ranges'], 'missing_trade_day_count': plan['missing_trade_days'],
        })
        if not jobs:
            logger.info('minute_bar resume scan found no pending symbols; nothing to do.')
            return {}
        counts: dict[str, int] = {}
        for job in jobs:
            job_kwargs = {key: value for key, value in job.items() if key in {'ts_code', 'ts_codes', 'start_date', 'end_date', 'freq'}}
            if 'ts_codes' in job_kwargs and len(job_kwargs['ts_codes']) == 1:
                job_kwargs['ts_code'] = job_kwargs.pop('ts_codes')[0]
            job_counts = updater.run(**job_kwargs)
            for key, value in job_counts.items():
                counts[key] = counts.get(key, 0) + int(value)
        return counts
    finally:
        updater.close()


def _chunk_codes(codes: list[str], chunk_size: int) -> list[list[str]]:
    return [codes[i:i + chunk_size] for i in range(0, len(codes), chunk_size)]


@contextmanager
def _override_minute_bar_workers(workers: int | None):
    if workers is None or workers <= 0:
        yield
        return
    original_stock_workers = settings.minute_bar_stock_workers
    original_fetch_workers = settings.minute_bar_fetch_workers
    settings.minute_bar_stock_workers = workers
    settings.minute_bar_fetch_workers = workers
    try:
        yield
    finally:
        settings.minute_bar_stock_workers = original_stock_workers
        settings.minute_bar_fetch_workers = original_fetch_workers


def _run_one_code_batch(
    ts_codes: list[str],
    start_date: date,
    end_date: date,
    freq: str,
    progress_file: str | None,
    workers: int,
) -> dict[str, object]:
    run_kwargs: dict[str, object] = {
        'ts_codes': ts_codes,
        'start_date': start_date,
        'end_date': end_date,
        'freq': freq,
    }
    _write_progress_record(progress_file, {
        'job': 'minute_bar',
        'event': 'batch_item_started',
        'ts_codes': ts_codes,
        'workers': workers,
    })
    try:
        with _override_minute_bar_workers(workers):
            counts = _run_job(run_kwargs, progress_file)
    except Exception as exc:
        _write_progress_record(progress_file, {
            'job': 'minute_bar',
            'event': 'batch_item_failed',
            'ts_codes': ts_codes,
            'workers': workers,
            'error': repr(exc),
        })
        return {'ts_codes': ts_codes, 'returncode': 1, 'counts': {}, 'error': repr(exc)}
    _write_progress_record(progress_file, {
        'job': 'minute_bar',
        'event': 'batch_item_completed',
        'ts_codes': ts_codes,
        'workers': workers,
        'counts': counts,
    })
    return {'ts_codes': ts_codes, 'returncode': 0, 'counts': counts}


def run_code_batches(ts_codes: list[str], start_date: date, end_date: date, freq: str, *, workers: int = 20, chunk_size: int = 1, progress_file: str | None = None) -> list[dict[str, object]]:
    batches = _chunk_codes(ts_codes, chunk_size)
    return [
        _run_one_code_batch(batch, start_date, end_date, freq, progress_file, workers)
        for batch in batches
    ]


def _load_missing_only_codes(start_date: date, end_date: date) -> list[str]:
    source = get_data_source(settings.primary_data_source)
    stock_basic = source.fetch_stock_basic()
    if 'list_date' not in stock_basic.columns or 'ts_code' not in stock_basic.columns:
        return [code for code in stock_basic.get('ts_code', []).tolist() if isinstance(code, str) and code]

    updater = MinuteBarUpdater()
    try:
        cal = source.fetch_trade_calendar(start_date, end_date)
        trade_days = [
            d.date() if hasattr(d, 'date') else d
            for d in cal.loc[cal['is_open'] == 1, 'cal_date'].tolist()
        ]
        if not trade_days:
            return []
        mb_days = updater.market_store.query(
            'select ts_code, cast(datetime as date) as dt from minute_bar '
            'where cast(datetime as date) between $start_date and $end_date '
            'group by ts_code, dt',
            {'start_date': start_date, 'end_date': end_date},
        )
        if not mb_days.empty and 'dt' in mb_days.columns:
            mb_days = mb_days.copy()
            mb_days['dt'] = [d.date() if hasattr(d, 'date') else d for d in mb_days['dt'].tolist()]
        if mb_days.empty:
            return [str(x) for x in stock_basic['ts_code'].dropna().tolist() if isinstance(x, str)]
        present_by_code = mb_days.groupby('ts_code')['dt'].apply(set).to_dict()
        codes: list[str] = []
        for row in stock_basic[['ts_code', 'list_date']].dropna(subset=['ts_code']).itertuples(index=False):
            ts_code = str(row.ts_code)
            list_date = _coerce_yyyymmdd_date(row.list_date)
            if list_date is None or list_date > end_date:
                continue
            eligible = [d for d in trade_days if d >= list_date]
            present = present_by_code.get(ts_code, set())
            if len(present.intersection(eligible)) < len(eligible):
                codes.append(ts_code)
        return codes
    finally:
        updater.close()


def main() -> dict[str, Any]:
    args = parse_args()
    run_kwargs = build_run_kwargs(args)
    batch_run = getattr(args, 'batch_run', False)
    missing_only = getattr(args, 'missing_only', False)
    plan_only = getattr(args, 'plan_only', False)
    workers = getattr(args, 'workers', settings.resolved_minute_bar_stock_workers)
    queue_workers = getattr(args, 'queue_workers', 1)
    shard_count = getattr(args, 'shards', 1)
    manifest_file = getattr(args, 'manifest_file', None)
    max_gap_jobs = getattr(args, 'max_gap_jobs', None)
    progress_file = getattr(args, 'progress_file', None)
    shard_output_dir = getattr(args, 'shard_output_dir', None)

    updater = MinuteBarUpdater()
    try:
        if missing_only:
            codes = _load_missing_only_codes(_require_date(run_kwargs['start_date'], 'start_date'), _require_date(run_kwargs['end_date'], 'end_date'))
            run_kwargs = dict(run_kwargs)
            run_kwargs.pop('ts_code', None)
            run_kwargs['ts_codes'] = codes
        elif batch_run or plan_only:
            run_kwargs = dict(run_kwargs)
            run_kwargs['ts_codes'] = _normalize_requested_codes(updater, run_kwargs)
            run_kwargs.pop('ts_code', None)

        if batch_run or plan_only:
            logger.info(
                'Starting planned full load: '
                f'minute_bar workers={workers} queue_workers={queue_workers} shards={shard_count} '
                f'missing_only={missing_only} plan_only={plan_only}'
            )
            plan = _plan_gap_backfill_jobs(
                updater,
                run_kwargs,
                shard_count=shard_count,
                max_gap_jobs=max_gap_jobs,
            )
            manifest_payload = _manifest_payload_from_plan(plan)
            if manifest_file:
                _write_manifest(manifest_file, {'status': 'planned', **manifest_payload})
            _write_progress_record(progress_file, {
                'job': 'minute_bar',
                'event': 'planned',
                'run_kwargs': run_kwargs,
                'workers': workers,
                'queue_workers': queue_workers,
                'missing_only': missing_only,
                'plan_only': plan_only,
                'requested_count': len(plan['requested_codes']),
                'pending_count': len(plan['pending_codes']),
                'skipped_count': len(plan['skipped_codes']),
                'gap_range_count': plan['gap_ranges'],
                'missing_trade_day_count': plan['missing_trade_days'],
                'job_count': plan['job_count'],
                'shard_count': plan['shard_count'],
            })
            if plan_only:
                print({'planned_jobs': plan['job_count'], 'shards': plan['shard_count']})
                return {'planned_jobs': plan['job_count'], 'shards': plan['shard_count'], 'manifest_file': manifest_file}
            merged = _execute_gap_jobs(
                plan['shards'],
                progress_file=progress_file,
                manifest_file=manifest_file,
                queue_workers=queue_workers,
                workers=workers,
                shard_output_dir=shard_output_dir,
            )
            summary = {
                'planned_jobs': plan['job_count'],
                'shards': plan['shard_count'],
                'ok': merged['succeeded_jobs'],
                'failed': merged['failed_job_count'],
                'counts': merged['counts'],
            }
            _write_progress_record(progress_file, {'job': 'minute_bar', 'event': 'batch_completed', 'summary': summary, 'counts': merged['counts']})
            print(summary)
            return summary
        logger.info('Starting full load: minute_bar.')
        _write_progress_record(progress_file, {'job': 'minute_bar', 'event': 'started', 'run_kwargs': run_kwargs})
        try:
            counts = _run_job(run_kwargs, progress_file)
        except Exception as exc:
            _write_progress_record(progress_file, {'job': 'minute_bar', 'event': 'failed', 'run_kwargs': run_kwargs, 'error': repr(exc)})
            raise
        logger.info(f'Rows loaded: {counts}')
        logger.info('Full load complete: minute_bar.')
        _write_progress_record(progress_file, {'job': 'minute_bar', 'event': 'completed', 'run_kwargs': run_kwargs, 'counts': counts})
        return counts
    finally:
        updater.close()


def run_job(**kwargs: object) -> dict[str, int]:
    normalized_kwargs = dict(kwargs)
    if 'start_date' not in normalized_kwargs or 'end_date' not in normalized_kwargs:
        return run_updater_job('minute_bar', MinuteBarUpdater, normalized_kwargs, logger)
    return _run_job(normalized_kwargs, None)


if __name__ == '__main__':
    main()
