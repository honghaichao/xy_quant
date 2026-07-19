"""Unit tests for report recap data collection."""

from __future__ import annotations

from datetime import date
import re

import pandas as pd

import scripts.report_recap_data as recap


class FakeDuckResult:
    def __init__(self, value: int) -> None:
        self.value = value

    def fetchone(self):
        return (self.value,)


class FakeDuckDBConn:
    def __init__(self) -> None:
        self.queries: list[tuple[str, list[object]]] = []

    def execute(self, sql: str, params: list[object] | None = None):
        self.queries.append((sql, params or []))
        if "count(*)" in sql and "select distinct" in sql:
            return FakeDuckResult(1)
        if "minute_bar" in sql:
            return FakeDuckResult(4)
        return FakeDuckResult(4)

    def close(self) -> None:
        pass


class FakePgCursor:
    def __init__(self, rows: dict[str, int]) -> None:
        self.rows = rows
        self.last_sql = ""
        self.last_params: tuple[object, object] | None = None

    def execute(self, sql: str, params: tuple[object, object]) -> None:
        self.last_sql = sql
        self.last_params = params

    def fetchone(self):
        match = re.search(r"from\s+([a-zA-Z_][a-zA-Z0-9_]*)", self.last_sql, flags=re.IGNORECASE)
        table = match.group(1) if match else ""
        return (self.rows[table],)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakePgConn:
    def __init__(self, rows: dict[str, int]) -> None:
        self.rows = rows
        self.cursor_obj = FakePgCursor(rows)

    def cursor(self):
        return self.cursor_obj

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeSource:
    def fetch_trade_calendar(self, start_date: date, end_date: date) -> pd.DataFrame:
        return pd.DataFrame({"cal_date": ["20240102", "20240103"], "is_open": [1, 1]})


def test_build_report_uses_trade_day_coverage(monkeypatch):
    monkeypatch.setattr(recap, "duckdb", type("Duck", (), {"connect": lambda *args, **kwargs: FakeDuckDBConn()}))
    monkeypatch.setattr(recap, "psycopg", type("Pg", (), {"connect": lambda *args, **kwargs: FakePgConn({
        "stock_suspend": 1,
        "top_list": 2,
        "margin_detail": 2,
        "hk_hold": 1,
        "stock_money_flow": 2,
        "concept_money_flow": 2,
        "industry_money_flow": 2,
    })}))
    monkeypatch.setattr(recap, "get_data_source", lambda name: FakeSource())
    monkeypatch.setattr(recap.settings, "primary_data_source", "tushare")
    monkeypatch.setattr(recap.settings, "duckdb_path", "/tmp/market.duckdb")
    monkeypatch.setattr(recap.settings, "pg_host", "localhost")
    monkeypatch.setattr(recap.settings, "pg_port", 5432)
    monkeypatch.setattr(recap.settings, "pg_user", "quant")
    monkeypatch.setattr(recap.settings, "pg_password", "secret")
    monkeypatch.setattr(recap.settings, "pg_database", "quant")

    report = recap.build_report(date(2024, 1, 2), date(2024, 1, 3))

    assert report["total_trade_days"] == 2
    assert report["market"][0]["covered_trade_days"] == 1
    assert report["market"][0]["coverage_pct"] == 50.0
    assert report["meta"][0]["covered_trade_days"] == 1
    assert report["meta"][0]["coverage_pct"] == 50.0
    assert len(report["meta"]) == 7
