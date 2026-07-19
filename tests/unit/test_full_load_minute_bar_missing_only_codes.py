from __future__ import annotations

from datetime import date
from pathlib import Path
import sys

import pandas as pd
import pytest

pytest.importorskip('duckdb')

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import full_load_minute_bar as module


class _FakeSource:
    def __init__(self) -> None:
        self.calendar_calls: list[tuple[date, date]] = []

    def fetch_stock_basic(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "list_date": "20200101"},
                {"ts_code": "000002.SZ", "list_date": "20200101"},
            ]
        )

    def fetch_trade_calendar(self, start_date: date, end_date: date) -> pd.DataFrame:
        self.calendar_calls.append((start_date, end_date))
        return pd.DataFrame(
            [
                {"cal_date": pd.Timestamp(date(2020, 1, 2)), "is_open": 1},
                {"cal_date": pd.Timestamp(date(2020, 1, 3)), "is_open": 1},
            ]
        )


class _FakeMarketStore:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.queries: list[tuple[str, dict[str, object] | None]] = []

    def init_schema(self) -> None:
        return None

    def upsert(self, table: str, df: pd.DataFrame) -> int:
        raise AssertionError('upsert should not be called')

    def query(self, sql: str, params: dict[str, object] | None = None) -> pd.DataFrame:
        self.queries.append((sql, params))
        return self.frame.copy()

    def execute(self, sql: str, params: dict[str, object] | None = None) -> int:
        raise AssertionError('execute should not be called')

    def get_last_date(self, table: str, ts_code: str | None = None) -> date | None:
        return None

    def count(self, table: str, where: str | None = None) -> int:
        return 0

    def close(self) -> None:
        return None


class _FakeUpdater:
    def __init__(self, store: _FakeMarketStore) -> None:
        self.market_store = store

    def close(self) -> None:
        return None


def test_load_missing_only_codes_uses_updater_market_store_query(monkeypatch):
    source = _FakeSource()
    store = _FakeMarketStore(
        pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "dt": pd.Timestamp(date(2020, 1, 2))},
                {"ts_code": "000001.SZ", "dt": pd.Timestamp(date(2020, 1, 3))},
                {"ts_code": "000002.SZ", "dt": pd.Timestamp(date(2020, 1, 2))},
            ]
        )
    )
    updater = _FakeUpdater(store)

    monkeypatch.setattr(module, 'get_data_source', lambda *_args, **_kwargs: source)
    monkeypatch.setattr(module, 'MinuteBarUpdater', lambda: updater)

    codes = module._load_missing_only_codes(date(2020, 1, 2), date(2020, 1, 3))

    assert codes == ['000002.SZ']
    assert source.calendar_calls == [(date(2020, 1, 2), date(2020, 1, 3))]
    assert len(store.queries) == 1
    sql, params = store.queries[0]
    assert 'from minute_bar' in sql.lower()
    assert params == {'start_date': date(2020, 1, 2), 'end_date': date(2020, 1, 3)}
