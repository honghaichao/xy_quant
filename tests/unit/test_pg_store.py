"""Unit tests for PostgreSQL metadata storage."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any, cast

import pandas as pd
import pytest

from config.settings import settings as app_settings
from data.storage import pg_store
from data.storage.pg_store import POSTGRES_META_TABLES, PostgresMetaStore
from utils.exception import StorageError


class FakeCursor:
    """Minimal psycopg-style cursor for unit tests."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, dict[str, Any] | tuple[str, ...] | None]] = []
        self.rowcount = 0
        self.description: list[SimpleNamespace] | None = None
        self._rows: list[tuple[Any, ...]] = []

    def _record_statement(self, sql: str, params: dict[str, Any] | tuple[str, ...] | None = None) -> None:
        self.executed.append((sql, params))
        normalized_sql = " ".join(sql.split())
        if normalized_sql.startswith("SELECT table_name FROM information_schema.tables"):
            self.description = [SimpleNamespace(name="table_name")]
            self._rows = [(table_name,) for table_name in sorted(POSTGRES_META_TABLES)]
            self.rowcount = len(self._rows)
            return
        if normalized_sql.startswith("SELECT column_name FROM information_schema.columns"):
            table_name = params[0] if isinstance(params, tuple) else None
            columns_by_table = {
                "stock_basic": [
                    "ts_code", "symbol", "name", "area", "industry", "fullname", "cnspell",
                    "market", "exchange", "list_status", "list_date", "delist_date", "is_hs",
                    "act_name", "act_ent_type",
                ],
                "concept_money_flow": ["trade_date", "concept_code", "行业-涨跌幅", "序号"],
                "data_update_log": [
                    "log_key", "table_name", "source", "update_type", "start_date", "end_date",
                    "rows_affected", "status", "error_msg", "context", "started_at", "finished_at",
                ],
                "data_quality_report": [
                    "report_key", "report_date", "table_name", "check_type", "check_result", "details", "created_at",
                ],
            }
            self.description = [SimpleNamespace(name="column_name")]
            rows = columns_by_table.get(table_name, []) if table_name is not None else []
            self._rows = [(column,) for column in rows]
            self.rowcount = len(self._rows)
            return
        if normalized_sql.startswith("SELECT ts_code, name FROM stock_basic"):
            self.description = [SimpleNamespace(name="ts_code"), SimpleNamespace(name="name")]
            self._rows = [("000001.SZ", "Ping An Bank")]
            self.rowcount = 1
            return
        if normalized_sql.startswith("SELECT"):
            self.description = []
            self._rows = []
            self.rowcount = 0
            return
        self.description = None
        if normalized_sql.startswith("INSERT INTO") or normalized_sql.startswith("UPDATE"):
            self.rowcount = 1
        else:
            self.rowcount = 0

    def execute(self, sql: str, params: dict[str, Any] | tuple[str, ...] | None = None) -> None:
        self._record_statement(sql, params)

    def executemany(
        self,
        sql: str,
        params_seq: list[dict[str, Any] | tuple[str, ...]],
        *,
        returning: bool = False,
    ) -> None:
        del returning
        for params in params_seq:
            self._record_statement(sql, params)
        self.rowcount = len(params_seq)

    def fetchall(self) -> list[tuple[Any, ...]]:
        """Return buffered result rows."""
        return list(self._rows)

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class FakeConnection:
    """Minimal psycopg-style connection for unit tests."""

    def __init__(self) -> None:
        self.cursor_obj = FakeCursor()
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self) -> FakeCursor:
        """Return a reusable fake cursor."""
        return self.cursor_obj

    def commit(self) -> None:
        """Record commit calls."""
        self.commits += 1

    def rollback(self) -> None:
        """Record rollback calls."""
        self.rollbacks += 1

    def close(self) -> None:
        """Mark connection closed."""
        self.closed = True


@pytest.fixture
def fake_connection() -> FakeConnection:
    """Provide a fake PostgreSQL connection."""
    return FakeConnection()


@pytest.fixture
def store(fake_connection: FakeConnection) -> PostgresMetaStore:
    """Create metadata store with a fake connection for isolation."""
    return PostgresMetaStore(connection=fake_connection)


def test_init_schema_creates_all_meta_tables(store: PostgresMetaStore) -> None:
    """init_schema emits the complete PostgreSQL schema."""
    store.init_schema()

    fake_store = cast(FakeConnection, store.connection)
    executed_sql = "\n".join(sql for sql, _ in fake_store.cursor_obj.executed)

    for table_name in POSTGRES_META_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table_name}" in executed_sql
    assert "cnspell" in executed_sql
    assert "act_name" in executed_sql
    assert "act_ent_type" in executed_sql
    assert "ALTER TABLE dividend ADD COLUMN IF NOT EXISTS div_listdate DATE" in executed_sql
    assert "ALTER TABLE dividend ADD COLUMN IF NOT EXISTS imp_ann_date DATE" in executed_sql
    assert "ALTER TABLE hk_hold ALTER COLUMN name TYPE VARCHAR(200)" in executed_sql
    assert "div_listdate" in executed_sql
    assert "imp_ann_date" in executed_sql
    assert fake_store.commits == 1


def test_upsert_query_execute_and_close_use_parameterized_sql(
    store: PostgresMetaStore,
    fake_connection: FakeConnection,
) -> None:
    """Store performs parameterized inserts, queries, and updates."""
    frame = pd.DataFrame(
        [
            {
                "ts_code": "000001.SZ",
                "symbol": "000001",
                "name": "Ping An Bank",
                "area": "Shenzhen",
                "industry": "Bank",
                "fullname": "Ping An Bank Co., Ltd.",
                "cnspell": "payh",
                "market": "Main",
                "exchange": "SZSE",
                "list_status": "L",
                "list_date": date(1991, 4, 3),
                "delist_date": None,
                "is_hs": "N",
                "act_name": "No controller",
                "act_ent_type": "Other",
            }
        ]
    )

    assert store.upsert("stock_basic", frame) == 1

    insert_sql, insert_params = fake_connection.cursor_obj.executed[-1]
    assert 'INSERT INTO "stock_basic" ("ts_code", "symbol", "name", "area", "industry", "fullname", "cnspell", "market", "exchange", "list_status", "list_date", "delist_date", "is_hs", "act_name", "act_ent_type")' in insert_sql
    assert 'ON CONFLICT ("ts_code") DO UPDATE SET' in insert_sql
    assert isinstance(insert_params, dict)
    assert insert_params["p0"] == "000001.SZ"
    assert insert_params["p2"] == "Ping An Bank"

    query_result = store.query(
        "SELECT ts_code, name FROM stock_basic WHERE ts_code = %(ts_code)s",
        {"ts_code": "000001.SZ"},
    )
    assert query_result.to_dict(orient="records") == [
        {"ts_code": "000001.SZ", "name": "Ping An Bank"}
    ]

    assert store.execute(
        "UPDATE stock_basic SET industry = %(industry)s WHERE ts_code = %(ts_code)s",
        {"industry": "Banking", "ts_code": "000001.SZ"},
    ) == 1
    assert fake_connection.commits == 2

    store.close()
    assert fake_connection.closed is True


def test_upsert_quotes_non_ascii_and_symbol_identifiers(
    store: PostgresMetaStore,
    fake_connection: FakeConnection,
) -> None:
    """Quoted identifiers and safe placeholder names should support non-ASCII columns."""
    frame = pd.DataFrame(
        [
            {
                "trade_date": date(2024, 1, 5),
                "concept_code": "C01",
                "行业-涨跌幅": 1.23,
                "序号": 1,
            }
        ]
    )

    assert store.upsert("concept_money_flow", frame) == 1

    insert_sql, insert_params = fake_connection.cursor_obj.executed[-1]
    assert 'INSERT INTO "concept_money_flow" ("trade_date", "concept_code", "行业-涨跌幅", "序号")' in insert_sql
    assert 'ON CONFLICT ("trade_date", "concept_code") DO UPDATE SET "行业-涨跌幅" = EXCLUDED."行业-涨跌幅", "序号" = EXCLUDED."序号"' in insert_sql
    assert insert_params == {"p0": date(2024, 1, 5), "p1": "C01", "p2": 1.23, "p3": 1}


def test_data_update_log_uses_idempotent_log_key_conflict_target(
    store: PostgresMetaStore,
    fake_connection: FakeConnection,
) -> None:
    """Audit log writes should upsert on stable log_key rather than append by surrogate id."""
    frame = pd.DataFrame(
        [
            {
                "log_key": "minute_bar|tushare|full|2024-01-01|2024-01-31",
                "table_name": "minute_bar",
                "source": "tushare",
                "update_type": "full",
                "start_date": date(2024, 1, 1),
                "end_date": date(2024, 1, 31),
                "rows_affected": 123,
                "status": "success",
                "error_msg": None,
                "context": {"freq": "1min"},
                "started_at": pd.Timestamp("2024-02-01 09:00:00"),
                "finished_at": pd.Timestamp("2024-02-01 09:10:00"),
            }
        ]
    )

    assert store.upsert("data_update_log", frame) == 1

    insert_sql, insert_params = fake_connection.cursor_obj.executed[-1]
    assert 'INSERT INTO "data_update_log" ("log_key", "table_name", "source", "update_type", "start_date", "end_date", "rows_affected", "status", "error_msg", "context", "started_at", "finished_at")' in insert_sql
    assert 'ON CONFLICT ("log_key") DO UPDATE SET' in insert_sql
    assert isinstance(insert_params, dict)
    assert insert_params["p0"] == "minute_bar|tushare|full|2024-01-01|2024-01-31"


def test_data_quality_report_uses_idempotent_report_key_conflict_target(
    store: PostgresMetaStore,
    fake_connection: FakeConnection,
) -> None:
    """Quality report writes should upsert on stable report_key rather than append by surrogate id."""
    frame = pd.DataFrame(
        [
            {
                "report_key": "minute_bar|2024-01-31|row_count|success",
                "report_date": date(2024, 1, 31),
                "table_name": "minute_bar",
                "check_type": "row_count",
                "check_result": "success",
                "details": {"rows": 123},
                "created_at": pd.Timestamp("2024-02-01 10:00:00"),
            }
        ]
    )

    assert store.upsert("data_quality_report", frame) == 1

    insert_sql, insert_params = fake_connection.cursor_obj.executed[-1]
    assert 'INSERT INTO "data_quality_report" ("report_key", "report_date", "table_name", "check_type", "check_result", "details", "created_at")' in insert_sql
    assert 'ON CONFLICT ("report_key") DO UPDATE SET' in insert_sql
    assert isinstance(insert_params, dict)
    assert insert_params["p0"] == "minute_bar|2024-01-31|row_count|success"


def test_invalid_table_name_is_rejected(store: PostgresMetaStore) -> None:
    """Known table validation rejects unsupported metadata tables."""
    with pytest.raises(StorageError, match="Unsupported meta table"):
        store.upsert("unsupported", pd.DataFrame())


def test_build_pg_dsn_uses_configured_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """Runtime PostgreSQL DSN should use the configured password, not a placeholder."""
    monkeypatch.setattr(app_settings, "pg_user", "quant_user")
    monkeypatch.setattr(app_settings, "pg_password", "secret-pass")
    monkeypatch.setattr(app_settings, "pg_host", "db.local")
    monkeypatch.setattr(app_settings, "pg_port", 5433)
    monkeypatch.setattr(app_settings, "pg_database", "xy_quant")

    assert pg_store._build_pg_dsn() == "postgresql://quant_user:secret-pass@db.local:5433/xy_quant"
