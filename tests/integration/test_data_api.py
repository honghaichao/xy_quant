"""Integration-style tests for the unified data API."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import pytest

from data import api


class FakeMarketStore:
    """In-memory market store stub returning preloaded frames."""

    def __init__(self, tables: dict[str, pd.DataFrame]) -> None:
        self.tables = tables
        self.queries: list[tuple[str, dict[str, Any] | None]] = []

    def query(self, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
        self.queries.append((sql, params))
        for table_name, frame in self.tables.items():
            if f"FROM {table_name}" in sql:
                return frame.copy()
        return pd.DataFrame()


class FakeMetaStore:
    """In-memory metadata store stub returning preloaded frames."""

    def __init__(self, tables: dict[str, pd.DataFrame]) -> None:
        self.tables = tables
        self.queries: list[tuple[str, dict[str, Any] | None]] = []

    def query(self, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
        self.queries.append((sql, params))
        for table_name, frame in self.tables.items():
            if f"FROM {table_name}" in sql:
                return frame.copy()
        return pd.DataFrame()


@pytest.fixture
def api_env(monkeypatch: pytest.MonkeyPatch) -> tuple[FakeMarketStore, FakeMetaStore]:
    """Patch the API module to use fake stores."""
    market_store = FakeMarketStore(
        {
            "daily_bar": pd.DataFrame(
                [
                    {
                        "ts_code": "000001.SZ",
                        "trade_date": pd.Timestamp("2024-01-02"),
                        "open": 10.0,
                        "high": 10.5,
                        "low": 9.8,
                        "close": 10.2,
                        "pre_close": 9.9,
                        "change": 0.3,
                        "pct_chg": 3.03,
                        "vol": 1000.0,
                        "amount": 5000.0,
                    },
                    {
                        "ts_code": "000001.SZ",
                        "trade_date": pd.Timestamp("2024-01-03"),
                        "open": 10.2,
                        "high": 10.7,
                        "low": 10.0,
                        "close": 10.4,
                        "pre_close": 10.2,
                        "change": 0.2,
                        "pct_chg": 1.96,
                        "vol": 1200.0,
                        "amount": 5200.0,
                    },
                    {
                        "ts_code": "000002.SZ",
                        "trade_date": pd.Timestamp("2024-01-03"),
                        "open": 20.0,
                        "high": 20.3,
                        "low": 19.9,
                        "close": 20.1,
                        "pre_close": 19.8,
                        "change": 0.3,
                        "pct_chg": 1.52,
                        "vol": 2200.0,
                        "amount": 10200.0,
                    },
                ]
            ),
            "minute_bar": pd.DataFrame(
                [
                    {
                        "ts_code": "000001.SZ",
                        "datetime": pd.Timestamp("2024-01-02 09:31:00"),
                        "freq": "1min",
                        "open": 10.0,
                        "high": 10.1,
                        "low": 9.9,
                        "close": 10.05,
                        "vol": 100.0,
                        "amount": 1000.0,
                    },
                    {
                        "ts_code": "000001.SZ",
                        "datetime": pd.Timestamp("2024-01-02 09:32:00"),
                        "freq": "1min",
                        "open": 10.05,
                        "high": 10.2,
                        "low": 10.0,
                        "close": 10.1,
                        "vol": 110.0,
                        "amount": 1100.0,
                    },
                ]
            ),
        }
    )
    meta_store = FakeMetaStore(
        {
            "trade_calendar": pd.DataFrame(
                [
                    {"exchange": "SSE", "cal_date": pd.Timestamp("2024-01-01"), "is_open": 0},
                    {"exchange": "SSE", "cal_date": pd.Timestamp("2024-01-02"), "is_open": 1},
                    {"exchange": "SSE", "cal_date": pd.Timestamp("2024-01-03"), "is_open": 1},
                ]
            ),
            "stock_basic": pd.DataFrame(
                [
                    {
                        "ts_code": "000001.SZ",
                        "symbol": "000001",
                        "name": "Ping An Bank",
                        "area": "Shenzhen",
                        "industry": "Bank",
                        "fullname": "Ping An Bank Co., Ltd.",
                        "market": "Main",
                        "exchange": "SZSE",
                        "list_status": "L",
                        "list_date": pd.Timestamp("1991-04-03"),
                        "delist_date": pd.NaT,
                        "is_hs": "N",
                    }
                ]
            ),
            "income": pd.DataFrame(
                [
                    {"ts_code": "000001.SZ", "end_date": pd.Timestamp("2023-12-31"), "n_income": 123.4},
                    {"ts_code": "000001.SZ", "end_date": pd.Timestamp("2022-12-31"), "n_income": 99.9},
                ]
            ),
            "concept_member": pd.DataFrame(
                [
                    {"concept_code": "CON001", "concept_name": "AI", "ts_code": "000001.SZ", "in_date": pd.Timestamp("2024-01-01"), "out_date": pd.NaT, "is_active": 1},
                    {"concept_code": "CON001", "concept_name": "AI", "ts_code": "000002.SZ", "in_date": pd.Timestamp("2024-01-01"), "out_date": pd.Timestamp("2024-01-02"), "is_active": 0},
                ]
            ),
            "industry_member": pd.DataFrame(
                [
                    {"industry_code": "IND001", "industry_name": "Bank", "ts_code": "000001.SZ", "in_date": pd.Timestamp("2024-01-01"), "out_date": pd.NaT},
                ]
            ),
            "index_weight": pd.DataFrame(
                [
                    {"index_code": "000300.SH", "ts_code": "000001.SZ", "trade_date": pd.Timestamp("2024-01-02"), "weight": 1.23},
                    {"index_code": "000300.SH", "ts_code": "000002.SZ", "trade_date": pd.Timestamp("2024-01-02"), "weight": 2.34},
                ]
            ),
        }
    )
    monkeypatch.setattr(api, "get_market_store", lambda name: market_store, raising=False)
    monkeypatch.setattr(api, "get_meta_store", lambda name: meta_store, raising=False)
    return market_store, meta_store


def test_get_price_filters_symbols_dates_and_fields(api_env: tuple[FakeMarketStore, FakeMetaStore]) -> None:
    """Daily price lookup should return the requested slice in JQ-style shape."""
    result = api.get_price(
        ["000001.SZ", "000002.SZ"],
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 3),
        fields=["ts_code", "trade_date", "close"],
    )

    assert result.to_dict(orient="records") == [
        {"ts_code": "000001.SZ", "trade_date": pd.Timestamp("2024-01-02"), "close": 10.2},
        {"ts_code": "000001.SZ", "trade_date": pd.Timestamp("2024-01-03"), "close": 10.4},
        {"ts_code": "000002.SZ", "trade_date": pd.Timestamp("2024-01-03"), "close": 20.1},
    ]


def test_get_price_supports_minute_frequency(api_env: tuple[FakeMarketStore, FakeMetaStore]) -> None:
    """Minute price lookup should read the minute table and keep datetime ordering."""
    result = api.get_price(
        "000001.SZ",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 2),
        frequency="1min",
        fields=["ts_code", "datetime", "close"],
    )

    assert result.to_dict(orient="records") == [
        {"ts_code": "000001.SZ", "datetime": pd.Timestamp("2024-01-02 09:31:00"), "close": 10.05},
        {"ts_code": "000001.SZ", "datetime": pd.Timestamp("2024-01-02 09:32:00"), "close": 10.1},
    ]


def test_get_fundamentals_and_security_info(api_env: tuple[FakeMarketStore, FakeMetaStore]) -> None:
    """Fundamentals and security metadata should come from the metadata store."""
    fundamentals = api.get_fundamentals(
        "income",
        "000001.SZ",
        start_date=date(2023, 1, 1),
        end_date=date(2023, 12, 31),
        fields=["ts_code", "end_date", "n_income"],
    )
    info = api.get_security_info("000001.SZ")

    assert fundamentals.to_dict(orient="records") == [
        {"ts_code": "000001.SZ", "end_date": pd.Timestamp("2023-12-31"), "n_income": 123.4}
    ]
    assert info["name"] == "Ping An Bank"
    assert info["ts_code"] == "000001.SZ"


def test_trade_days_and_constituent_helpers(api_env: tuple[FakeMarketStore, FakeMetaStore]) -> None:
    """Trade-day and constituent helper APIs should return normalized lists."""
    trade_days = api.get_trade_days(date(2024, 1, 1), date(2024, 1, 3))
    concept = api.get_concept_stocks("CON001", date(2024, 1, 2))
    industry = api.get_industry_stocks("IND001", date(2024, 1, 2))
    index = api.get_index_stocks("000300.SH", date(2024, 1, 2))

    assert trade_days == [date(2024, 1, 2), date(2024, 1, 3)]
    assert concept == ["000001.SZ"]
    assert industry == ["000001.SZ"]
    assert index == ["000001.SZ", "000002.SZ"]


def test_attribute_history_returns_tail_window(api_env: tuple[FakeMarketStore, FakeMetaStore]) -> None:
    """attribute_history should return the latest N rows for the security."""
    result = api.attribute_history(
        "000001.SZ",
        count=1,
        unit="1d",
        fields=["ts_code", "trade_date", "close"],
    )

    assert result.to_dict(orient="records") == [
        {"ts_code": "000001.SZ", "trade_date": pd.Timestamp("2024-01-03"), "close": 10.4}
    ]
