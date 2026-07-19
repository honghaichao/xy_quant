"""Unit tests for DuckDB market storage."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from data.storage.duckdb_store import DUCKDB_MARKET_TABLES, DuckDBMarketStore
from utils.exception import StorageError


@pytest.fixture
def store(tmp_path: Path) -> DuckDBMarketStore:
    """Create a market store backed by a temporary DuckDB database."""
    db_path = tmp_path / "market.duckdb"
    market_store = DuckDBMarketStore(db_path=str(db_path))
    market_store.init_schema()
    return market_store


@pytest.fixture(autouse=True)
def close_store(request: pytest.FixtureRequest) -> Iterator[None]:
    """Close store fixtures created by the test when present."""
    yield
    store_fixture = request.node.funcargs.get("store")
    if isinstance(store_fixture, DuckDBMarketStore):
        store_fixture.close()


def test_init_schema_creates_all_market_tables(store: DuckDBMarketStore) -> None:
    """init_schema creates all market tables from the plan."""
    tables = store.query(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'main'
        ORDER BY table_name
        """
    )

    assert tables["table_name"].tolist() == sorted(DUCKDB_MARKET_TABLES)


def test_upsert_query_and_count_round_trip(store: DuckDBMarketStore) -> None:
    """Store can upsert, overwrite by primary key, query, and count rows."""
    first = pd.DataFrame(
        [
            {
                "ts_code": "000001.SZ",
                "trade_date": date(2024, 1, 2),
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": 10.2,
                "pre_close": 9.9,
                "change": 0.3,
                "pct_chg": 3.03,
                "vol": 1000.0,
                "amount": 5000.0,
            }
        ]
    )
    second = first.assign(close=[10.8], amount=[5200.0])

    assert store.upsert("daily_bar", first) == 1
    assert store.upsert("daily_bar", second) == 1
    assert store.count("daily_bar") == 1

    result = store.query(
        "SELECT ts_code, trade_date, close, amount FROM daily_bar WHERE ts_code = $ts_code",
        {"ts_code": "000001.SZ"},
    )

    assert result.to_dict(orient="records") == [
        {
            "ts_code": "000001.SZ",
            "trade_date": pd.Timestamp("2024-01-02"),
            "close": 10.8,
            "amount": 5200.0,
        }
    ]


def test_minute_bar_uses_month_partitions_and_view(store: DuckDBMarketStore) -> None:
    """minute_bar writes into month partitions while preserving the compatibility view."""
    frame = pd.DataFrame(
        [
            {
                "ts_code": "000001.SZ",
                "datetime": pd.Timestamp("2024-01-02 09:31:00"),
                "freq": "1min",
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.05,
                "vol": 100.0,
                "amount": 105.0,
            },
            {
                "ts_code": "000001.SZ",
                "datetime": pd.Timestamp("2024-02-01 09:31:00"),
                "freq": "1min",
                "open": 2.0,
                "high": 2.1,
                "low": 1.9,
                "close": 2.05,
                "vol": 200.0,
                "amount": 410.0,
            },
        ]
    )

    assert store.upsert("minute_bar", frame) == 2

    tables = store.query(
        """
        SELECT table_name, table_type
        FROM information_schema.tables
        WHERE table_schema = 'main'
        ORDER BY table_name
        """
    )
    table_names = set(tables["table_name"])
    assert "minute_bar_2024_01" in table_names
    assert "minute_bar_2024_02" in table_names
    assert "minute_bar" in table_names
    assert set(tables.loc[tables["table_name"] == "minute_bar", "table_type"]) == {"VIEW"}
    assert store.count("minute_bar") == 2


def test_execute_and_get_last_date_support_optional_symbol_filter(store: DuckDBMarketStore) -> None:
    """Arbitrary statements and latest-date lookup work as documented."""
    rows = pd.DataFrame(
        [
            {
                "ts_code": "000001.SZ",
                "trade_date": date(2024, 1, 2),
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.0,
                "pre_close": 0.8,
                "change": 0.2,
                "pct_chg": 25.0,
                "vol": 10.0,
                "amount": 11.0,
            },
            {
                "ts_code": "000001.SZ",
                "trade_date": date(2024, 1, 3),
                "open": 1.0,
                "high": 1.2,
                "low": 0.8,
                "close": 1.1,
                "pre_close": 1.0,
                "change": 0.1,
                "pct_chg": 10.0,
                "vol": 12.0,
                "amount": 13.0,
            },
            {
                "ts_code": "000002.SZ",
                "trade_date": date(2024, 1, 1),
                "open": 2.0,
                "high": 2.1,
                "low": 1.9,
                "close": 2.0,
                "pre_close": 2.0,
                "change": 0.0,
                "pct_chg": 0.0,
                "vol": 20.0,
                "amount": 21.0,
            },
        ]
    )

    store.upsert("daily_bar", rows)
    affected = store.execute(
        "UPDATE daily_bar SET amount = $amount WHERE ts_code = $ts_code AND trade_date = $trade_date",
        {"amount": 14.0, "ts_code": "000001.SZ", "trade_date": date(2024, 1, 3)},
    )

    assert affected == 1
    assert store.get_last_date("daily_bar") == date(2024, 1, 3)
    assert store.get_last_date("daily_bar", ts_code="000001.SZ") == date(2024, 1, 3)
    assert store.get_last_date("daily_bar", ts_code="999999.SZ") is None
    assert store.count("daily_bar", "ts_code = '000001.SZ'") == 2


def test_invalid_table_name_is_rejected(store: DuckDBMarketStore) -> None:
    """Known table validation rejects unsupported market table names."""
    with pytest.raises(StorageError, match="Unsupported market table"):
        store.upsert("unknown_table", pd.DataFrame())
