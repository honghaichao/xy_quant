from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

pytest.importorskip('duckdb')
pd = pytest.importorskip('pandas')
duckdb = pytest.importorskip('duckdb')

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import full_load_minute_bar as module


class _FakeSource:
    def __init__(self, trade_days: list[date], stock_basic: object) -> None:
        self._trade_days = trade_days
        self._stock_basic = stock_basic

    def fetch_trade_calendar(self, start_date: date, end_date: date):
        _ = start_date, end_date
        return pd.DataFrame({'cal_date': self._trade_days, 'is_open': [1] * len(self._trade_days)})

    def fetch_stock_basic(self):
        return self._stock_basic


class _FakeStore:
    def init_schema(self) -> None:
        return None


class _TrackingStore(_FakeStore):
    def __init__(self) -> None:
        self.queries: list[tuple[str, dict[str, object]]] = []
        self._rows = pd.DataFrame([
            {'ts_code': '000001.SZ', 'dt': pd.Timestamp(date(2020, 1, 2))},
            {'ts_code': '000001.SZ', 'dt': pd.Timestamp(date(2020, 1, 7))},
        ])

    def query(self, sql: str, params: dict[str, object]):
        self.queries.append((sql, params))
        return self._rows.copy()


def test_build_gap_backfill_jobs_groups_adjacent_missing_trade_days(tmp_path, monkeypatch):
    db_path = tmp_path / 'market.duckdb'
    con = duckdb.connect(str(db_path))
    con.execute('CREATE TABLE minute_bar (ts_code VARCHAR, datetime TIMESTAMP, freq VARCHAR)')
    con.execute(
        """
        INSERT INTO minute_bar VALUES
            ('000001.SZ', TIMESTAMP '2020-01-02 09:31:00', '1min'),
            ('000001.SZ', TIMESTAMP '2020-01-07 09:31:00', '1min')
        """
    )
    con.close()

    monkeypatch.setattr(module.settings, 'duckdb_path', str(db_path))

    updater = SimpleNamespace(
        source=_FakeSource(
            trade_days=[
                date(2020, 1, 2),
                date(2020, 1, 3),
                date(2020, 1, 6),
                date(2020, 1, 7),
                date(2020, 1, 8),
            ],
            stock_basic=pd.DataFrame({'ts_code': ['000001.SZ'], 'list_date': ['20190101']}),
        ),
        market_store=_TrackingStore(),
    )

    jobs = module._build_gap_backfill_jobs(
        updater,
        {'ts_code': '000001.SZ', 'start_date': date(2020, 1, 2), 'end_date': date(2020, 1, 8), 'freq': '1min'},
    )

    assert jobs == [
        {'ts_code': '000001.SZ', 'start_date': date(2020, 1, 3), 'end_date': date(2020, 1, 6), 'freq': '1min'},
        {'ts_code': '000001.SZ', 'start_date': date(2020, 1, 8), 'end_date': date(2020, 1, 8), 'freq': '1min'},
    ]


def test_run_job_backfills_each_precise_gap_range(tmp_path, monkeypatch):
    db_path = tmp_path / 'market.duckdb'
    con = duckdb.connect(str(db_path))
    con.execute('CREATE TABLE minute_bar (ts_code VARCHAR, datetime TIMESTAMP, freq VARCHAR)')
    con.execute(
        """
        INSERT INTO minute_bar VALUES
            ('000001.SZ', TIMESTAMP '2020-01-02 09:31:00', '1min'),
            ('000001.SZ', TIMESTAMP '2020-01-07 09:31:00', '1min')
        """
    )
    con.close()

    monkeypatch.setattr(module.settings, 'duckdb_path', str(db_path))

    source = _FakeSource(
        trade_days=[
            date(2020, 1, 2),
            date(2020, 1, 3),
            date(2020, 1, 6),
            date(2020, 1, 7),
            date(2020, 1, 8),
        ],
        stock_basic=pd.DataFrame({'ts_code': ['000001.SZ'], 'list_date': ['20190101']}),
    )
    run_calls: list[dict[str, object]] = []

    tracking_store = _TrackingStore()

    class _FakeUpdater:
        def __init__(self) -> None:
            self.source = source
            self.market_store = tracking_store

        def run(self, **kwargs):
            run_calls.append(dict(kwargs))
            return {'minute_bar': 10 if len(run_calls) == 1 else 20}

        def close(self) -> None:
            return None

    monkeypatch.setattr(module, 'MinuteBarUpdater', _FakeUpdater)

    counts = module._run_job(
        {'ts_code': '000001.SZ', 'start_date': date(2020, 1, 2), 'end_date': date(2020, 1, 8), 'freq': '1min'},
        None,
    )

    assert run_calls == [
        {'ts_code': '000001.SZ', 'start_date': date(2020, 1, 3), 'end_date': date(2020, 1, 6), 'freq': '1min'},
        {'ts_code': '000001.SZ', 'start_date': date(2020, 1, 8), 'end_date': date(2020, 1, 8), 'freq': '1min'},
    ]
    assert counts == {'minute_bar': 30}
    assert tracking_store.queries == [
        ('SELECT ts_code, CAST(datetime AS DATE) AS dt FROM minute_bar WHERE CAST(datetime AS DATE) BETWEEN $start_date AND $end_date GROUP BY ts_code, dt', {'start_date': date(2020, 1, 2), 'end_date': date(2020, 1, 8)})
    ]


def test_plan_gap_backfill_jobs_adds_job_metadata_and_shards(monkeypatch):
    updater = SimpleNamespace(
        source=_FakeSource(
            trade_days=[
                date(2020, 1, 2),
                date(2020, 1, 3),
                date(2020, 1, 6),
                date(2020, 1, 7),
                date(2020, 1, 8),
            ],
            stock_basic=pd.DataFrame({'ts_code': ['000001.SZ'], 'list_date': ['20190101']}),
        ),
        market_store=_TrackingStore(),
    )

    plan = module._plan_gap_backfill_jobs(
        updater,
        {'ts_code': '000001.SZ', 'start_date': date(2020, 1, 2), 'end_date': date(2020, 1, 8), 'freq': '1min'},
        shard_count=2,
    )

    assert plan['job_count'] == 2
    assert plan['job_count_by_code'] == {'000001.SZ': 2}
    assert [job['job_index'] for job in plan['jobs']] == [1, 2]
    assert [job['job_id'] for job in plan['jobs']] == [
        '000001.SZ:2020-01-03:2020-01-06:1min',
        '000001.SZ:2020-01-08:2020-01-08:1min',
    ]
    assert [job['estimated_cost'] for job in plan['jobs']] == [4, 1]
    assert len(plan['shards']) == 2
    assert [shard['shard_id'] for shard in plan['shards']] == [1, 2]
    assert [shard['job_count'] for shard in plan['shards']] == [1, 1]
    assert [shard['estimated_cost'] for shard in plan['shards']] == [4, 1]
    assert [shard['jobs'][0]['job_id'] for shard in plan['shards']] == [
        '000001.SZ:2020-01-03:2020-01-06:1min',
        '000001.SZ:2020-01-08:2020-01-08:1min',
    ]


def test_manifest_payload_serializes_dates(monkeypatch):
    updater = SimpleNamespace(
        source=_FakeSource(
            trade_days=[date(2020, 1, 2), date(2020, 1, 3)],
            stock_basic=pd.DataFrame({'ts_code': ['000001.SZ'], 'list_date': ['20190101']}),
        ),
        market_store=_TrackingStore(),
    )

    plan = module._plan_gap_backfill_jobs(
        updater,
        {'ts_code': '000001.SZ', 'start_date': date(2020, 1, 2), 'end_date': date(2020, 1, 3), 'freq': '1min'},
        shard_count=1,
    )
    payload = module._manifest_payload_from_plan(plan)

    assert payload['jobs'][0]['start_date'] == '2020-01-03'
    assert payload['jobs'][0]['end_date'] == '2020-01-03'
    assert payload['shards'][0]['jobs'][0]['job_id'] == '000001.SZ:2020-01-03:2020-01-03:1min'


def test_manifest_payload_empty_when_no_gap_jobs(monkeypatch):
    tracking_store = _TrackingStore()
    tracking_store._rows = pd.DataFrame([
        {'ts_code': '000001.SZ', 'dt': pd.Timestamp(date(2020, 1, 2))},
        {'ts_code': '000001.SZ', 'dt': pd.Timestamp(date(2020, 1, 3))},
    ])
    updater = SimpleNamespace(
        source=_FakeSource(
            trade_days=[date(2020, 1, 2), date(2020, 1, 3)],
            stock_basic=pd.DataFrame({'ts_code': ['000001.SZ'], 'list_date': ['20190101']}),
        ),
        market_store=tracking_store,
    )

    plan = module._plan_gap_backfill_jobs(
        updater,
        {'ts_code': '000001.SZ', 'start_date': date(2020, 1, 2), 'end_date': date(2020, 1, 3), 'freq': '1min'},
        shard_count=3,
    )
    payload = module._manifest_payload_from_plan(plan)

    assert payload['job_count'] == 0
    assert payload['pending_codes'] == []
    assert payload['skipped_codes'] == ['000001.SZ']
    assert len(payload['shards']) == 3
    assert all(shard['jobs'] == [] for shard in payload['shards'])


def test_main_plan_only_writes_manifest_and_skips_execution(tmp_path, monkeypatch):
    manifest_path = tmp_path / 'minute_bar_manifest.json'
    progress_path = tmp_path / 'minute_bar_progress.jsonl'
    run_calls: list[dict[str, object]] = []

    class _FakeUpdater:
        def __init__(self) -> None:
            self.source = _FakeSource(
                trade_days=[date(2020, 1, 2), date(2020, 1, 3)],
                stock_basic=pd.DataFrame({'ts_code': ['000001.SZ'], 'list_date': ['20190101']}),
            )
            self.market_store = _TrackingStore()

        def run(self, **kwargs):
            run_calls.append(dict(kwargs))
            return {'minute_bar': 1}

        def close(self) -> None:
            return None

    monkeypatch.setattr(module, 'MinuteBarUpdater', _FakeUpdater)
    monkeypatch.setattr(module, 'parse_args', lambda: SimpleNamespace(
        ts_code='000001.SZ',
        start='20200102',
        end='20200103',
        start_date=date(2020, 1, 2),
        end_date=date(2020, 1, 3),
        freq='1min',
        batch_run=False,
        missing_only=False,
        plan_only=True,
        workers=4,
        queue_workers=2,
        shards=2,
        manifest_file=str(manifest_path),
        max_gap_jobs=None,
        progress_file=str(progress_path),
        chunk_size=1,
        shard_output_dir=str(tmp_path / 'shards'),
    ))
    summary = module.main()

    assert summary == {'planned_jobs': 1, 'shards': 2, 'manifest_file': str(manifest_path)}
    assert run_calls == []
    manifest = __import__('json').loads(manifest_path.read_text(encoding='utf-8'))
    assert manifest['status'] == 'planned'
    assert manifest['job_count'] == 1
    assert manifest['jobs'][0]['job_id'] == '000001.SZ:2020-01-03:2020-01-03:1min'
    progress_text = progress_path.read_text(encoding='utf-8')
    assert '"event": "planned"' in progress_text
