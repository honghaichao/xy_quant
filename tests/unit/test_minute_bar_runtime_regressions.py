from __future__ import annotations

from datetime import date
from pathlib import Path
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import full_load_minute_bar as minute_bar_module
import data.source.tushare_source as tushare_source_module
from utils.exception import ConfigError


class _FakeUpdater:
    def __init__(self) -> None:
        self.market_store = SimpleNamespace(init_schema=lambda: None)
        self.closed = False
        self.run_calls: list[dict[str, object]] = []

    def run(self, **kwargs):
        self.run_calls.append(dict(kwargs))
        return {'minute_bar': 241}

    def close(self) -> None:
        self.closed = True


def test_execute_gap_jobs_uses_requested_outer_worker_count(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_queue_workers: list[int] = []
    captured_shards: list[dict[str, object]] = []

    def fake_run_shard_jobs(
        shard: dict[str, object],
        *,
        progress_file: str | None,
        workers: int,
        updater_factory=None,
    ) -> dict[str, object]:
        _ = progress_file, workers, updater_factory
        captured_shards.append(shard)
        return {
            'shard_summary': {
                'shard_id': int(shard['shard_id']),
                'job_count': int(shard['job_count']),
                'estimated_cost': int(shard['estimated_cost']),
                'succeeded': len(shard['jobs']),
                'failed': 0,
                'counts': {'minute_bar': len(shard['jobs'])},
            },
            'results': [
                {'job': job, 'counts': {'minute_bar': 1}, 'returncode': 0, 'error': None}
                for job in shard['jobs']
            ],
        }

    class FakeExecutor:
        def __init__(self, max_workers: int) -> None:
            captured_queue_workers.append(max_workers)
            self.max_workers = max_workers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def submit(self, fn, *args, **kwargs):
            class FakeFuture:
                def result(self_nonlocal):
                    return fn(*args, **kwargs)

            return FakeFuture()

    def fake_wait(futures, timeout, return_when):
        return set(futures), set()

    monkeypatch.setattr(minute_bar_module, '_run_shard_jobs', fake_run_shard_jobs)
    monkeypatch.setattr(minute_bar_module, 'ThreadPoolExecutor', FakeExecutor)
    monkeypatch.setattr(minute_bar_module, 'wait', fake_wait)

    result = minute_bar_module._execute_gap_jobs(
        [
            {
                'shard_id': 1,
                'job_count': 2,
                'estimated_cost': 2,
                'jobs': [
                    {'job_id': 'a', 'job_index': 1, 'ts_code': '000001.SZ', 'start_date': date(2024, 1, 2), 'end_date': date(2024, 1, 2), 'freq': '1min', 'estimated_cost': 1},
                    {'job_id': 'b', 'job_index': 2, 'ts_code': '000002.SZ', 'start_date': date(2024, 1, 2), 'end_date': date(2024, 1, 2), 'freq': '1min', 'estimated_cost': 1},
                ],
            }
        ],
        progress_file=None,
        manifest_file=None,
        queue_workers=8,
        workers=10,
    )

    assert captured_queue_workers == [8]
    assert [int(shard['shard_id']) for shard in captured_shards] == [1]
    assert result['failed_job_count'] == 0
    assert result['succeeded_jobs'] == 2


def test_execute_gap_jobs_clamps_non_positive_outer_worker_count_to_one(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_queue_workers: list[int] = []

    class FakeExecutor:
        def __init__(self, max_workers: int) -> None:
            captured_queue_workers.append(max_workers)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def submit(self, fn, *args, **kwargs):
            class FakeFuture:
                def result(self_nonlocal):
                    return {'shard_summary': {'shard_id': 1, 'job_count': 0, 'estimated_cost': 0, 'succeeded': 0, 'failed': 0, 'counts': {}}, 'results': []}

            return FakeFuture()

    def fake_wait(futures, timeout, return_when):
        return set(futures), set()

    monkeypatch.setattr(minute_bar_module, 'ThreadPoolExecutor', FakeExecutor)
    monkeypatch.setattr(minute_bar_module, 'wait', fake_wait)

    result = minute_bar_module._execute_gap_jobs(
        [{'shard_id': 1, 'job_count': 0, 'estimated_cost': 0, 'jobs': []}],
        progress_file=None,
        manifest_file=None,
        queue_workers=0,
        workers=10,
    )

    assert captured_queue_workers == [1]
    assert result['failed_job_count'] == 0
    assert result['succeeded_jobs'] == 0


def test_run_gap_job_reuses_shared_updater_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    updater = _FakeUpdater()
    monkeypatch.setattr(minute_bar_module, 'MinuteBarUpdater', lambda: (_ for _ in ()).throw(AssertionError('should not instantiate directly')))

    result = minute_bar_module._run_gap_job(
        {
            'job_id': 'x',
            'job_index': 1,
            'ts_code': '000001.SZ',
            'start_date': date(2024, 1, 2),
            'end_date': date(2024, 1, 2),
            'freq': '1min',
        },
        progress_file=None,
        workers=4,
        updater_factory=lambda: updater,
    )

    assert result['returncode'] == 0
    assert result['counts']['minute_bar'] == 241
    assert updater.closed is True


def test_run_gap_job_does_not_close_injected_updater() -> None:
    updater = _FakeUpdater()

    result = minute_bar_module._run_gap_job(
        {
            'job_id': 'shared',
            'job_index': 1,
            'ts_code': '000001.SZ',
            'start_date': date(2024, 1, 2),
            'end_date': date(2024, 1, 2),
            'freq': '1min',
        },
        progress_file=None,
        workers=4,
        updater=updater,
    )

    assert result['returncode'] == 0
    assert updater.closed is False


def test_run_shard_jobs_reuses_single_updater_across_jobs() -> None:
    updater = _FakeUpdater()

    result = minute_bar_module._run_shard_jobs(
        {
            'shard_id': 1,
            'job_count': 2,
            'estimated_cost': 2,
            'jobs': [
                {'job_id': 'a', 'job_index': 1, 'ts_code': '000001.SZ', 'start_date': date(2024, 1, 2), 'end_date': date(2024, 1, 2), 'freq': '1min', 'estimated_cost': 1},
                {'job_id': 'b', 'job_index': 2, 'ts_code': '000002.SZ', 'start_date': date(2024, 1, 3), 'end_date': date(2024, 1, 3), 'freq': '1min', 'estimated_cost': 1},
            ],
        },
        progress_file=None,
        workers=4,
        updater_factory=lambda: updater,
    )

    assert updater.run_calls == [
        {'ts_code': '000001.SZ', 'start_date': date(2024, 1, 2), 'end_date': date(2024, 1, 2), 'freq': '1min'},
        {'ts_code': '000002.SZ', 'start_date': date(2024, 1, 3), 'end_date': date(2024, 1, 3), 'freq': '1min'},
    ]
    assert updater.closed is True
    assert result['shard_summary']['succeeded'] == 2
    assert result['shard_summary']['failed'] == 0


def test_create_default_client_uses_explicit_token_and_skips_pro_api_when_token_file_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tushare_source_module.settings, 'tushare_token', 'test-token')

    token_calls: list[str] = []
    pro_api_calls: list[object] = []

    class FakeTsModule:
        def set_token(self, token: str) -> None:
            token_calls.append(token)

        def pro_api(self, token=None):
            pro_api_calls.append(token)
            return SimpleNamespace(stock_basic=lambda **kwargs: pd.DataFrame())

        def pro_bar(self, **kwargs):
            return pd.DataFrame()

    monkeypatch.setattr(tushare_source_module, 'ts', FakeTsModule())

    client = tushare_source_module._create_default_client()

    assert token_calls == ['test-token']
    assert pro_api_calls == ['test-token']
    assert hasattr(client, 'stock_basic')


def test_create_default_client_requires_configured_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tushare_source_module.settings, 'tushare_token', '')

    with pytest.raises(ConfigError, match='Tushare token is required'):
        tushare_source_module._create_default_client()
