"""Unit tests for lazy BaseUpdater store initialization."""

from __future__ import annotations

from typing import Any, cast

import pandas as pd
import pytest

from data.updater.base import BaseUpdater
from interfaces.data_source import IDataSource


class DummySource:
    def supports(self, capability: str) -> bool:
        return True


class DummyStore:
    def __init__(self) -> None:
        self.closed = False
        self.upserts: list[tuple[str, pd.DataFrame]] = []

    def close(self) -> None:
        self.closed = True

    def upsert(self, table: str, frame: pd.DataFrame) -> int:
        self.upserts.append((table, frame.copy()))
        return len(frame)


class DummyUpdater(BaseUpdater):
    source_capability = None

    def run(self, *args: Any, **kwargs: Any) -> dict[str, int]:
        return {}


def test_base_updater_initializes_stores_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    market = DummyStore()
    meta = DummyStore()

    def fake_get_market_store(name: str) -> DummyStore:
        calls.append(f"market:{name}")
        return market

    def fake_get_meta_store(name: str) -> DummyStore:
        calls.append(f"meta:{name}")
        return meta

    monkeypatch.setattr('data.updater.base.get_market_store', fake_get_market_store)
    monkeypatch.setattr('data.updater.base.get_meta_store', fake_get_meta_store)

    updater = DummyUpdater(source=cast(IDataSource, DummySource()))
    assert calls == []

    meta_rows = updater._upsert_meta('stock_basic', pd.DataFrame([{'ts_code': '000001.SZ'}]))
    assert meta_rows == 1
    assert calls == ['meta:postgres']

    market_rows = updater._upsert_market('daily_bar', pd.DataFrame([{'ts_code': '000001.SZ'}]))
    assert market_rows == 1
    assert calls == ['meta:postgres', 'market:duckdb']

    updater.close()
    assert market.closed is True
    assert meta.closed is True


def test_base_updater_close_skips_uninitialized_stores(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_store(_name: str) -> DummyStore:
        raise AssertionError('store factory should not be called during close')

    monkeypatch.setattr('data.updater.base.get_market_store', unexpected_store)
    monkeypatch.setattr('data.updater.base.get_meta_store', unexpected_store)

    updater = DummyUpdater(source=cast(IDataSource, DummySource()))
    updater.close()
