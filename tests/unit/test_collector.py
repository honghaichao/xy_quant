"""Unit tests for P1 review collector."""

from __future__ import annotations

from datetime import date

import pandas as pd

from review.collector import ReviewCollector


class _DummyStore:
    def __init__(self, frames: list[pd.DataFrame]) -> None:
        self._frames = frames

    def query(self, sql: str, params=None) -> pd.DataFrame:
        return self._frames.pop(0)


def test_collect_breadth_treats_nan_aggregates_as_zero() -> None:
    collector = ReviewCollector(_DummyStore([pd.DataFrame([{"up": float("nan"), "down": float("nan"), "flat": float("nan")}])]), _DummyStore([]))

    breadth = collector._collect_breadth(date(2026, 5, 19))

    assert breadth == {"up": 0, "down": 0, "flat": 0, "net": 0}


from datetime import date

import pandas as pd

from review.collector import ReviewDataCollector


class FakeStore:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.frames = frames
        self.queries: list[tuple[str, dict[str, object] | None]] = []

    def query(self, sql: str, params: dict[str, object] | None = None) -> pd.DataFrame:
        self.queries.append((sql, params))
        if "FROM index_daily" in sql:
            return self.frames["index_daily"]
        if "FROM daily_bar" in sql:
            return self.frames["daily_bar"]
        if "COUNT(*) AS value FROM limit_list" in sql:
            if '"limit" = \'U\' AND open_times > 0' in sql:
                return pd.DataFrame([{"value": 1}])
            if '"limit" = \'U\'' in sql:
                return pd.DataFrame([{"value": 2}])
            if '"limit" = \'D\'' in sql:
                return pd.DataFrame([{"value": 1}])
        if 'FROM limit_list' in sql:
            return self.frames["limit_list"]
        if "FROM industry_money_flow" in sql:
            return self.frames["industry_money_flow"]
        if "SELECT MAX(trade_date) AS prev_trade_date" in sql:
            return pd.DataFrame([{"prev_trade_date": date(2024, 1, 1)}])
        if "FROM concept_money_flow" in sql:
            return self.frames["concept_money_flow"]
        if "FROM stock_money_flow" in sql:
            return self.frames["stock_money_flow"]
        if "FROM hk_hold" in sql:
            return self.frames["hk_hold"]
        return pd.DataFrame()


def make_collector() -> tuple[ReviewDataCollector, FakeStore, FakeStore]:
    frames = {
        "index_daily": pd.DataFrame([{ "ts_code": "000001.SH", "close": 3000.0, "pct_chg": 1.2 }]),
        "daily_bar": pd.DataFrame([{ "up": 2, "down": 1, "flat": 3 }]),
        "limit_list": pd.DataFrame([
            {"trade_date": date(2024, 1, 2), "ts_code": "000001.SZ", "name": "A", "amount": 10.0, "limit_times": 3, "limit": "U", "open_times": 1},
            {"trade_date": date(2024, 1, 2), "ts_code": "000002.SZ", "name": "B", "amount": 8.0, "limit_times": 2, "limit": "U", "open_times": 0},
            {"trade_date": date(2024, 1, 2), "ts_code": "000003.SZ", "name": "C", "amount": 1.0, "limit_times": 1, "limit": "D", "open_times": 0},
        ]),
        "industry_money_flow": pd.DataFrame([
            {"trade_date": date(2024, 1, 2), "industry_code": "801010", "industry_name": "银行", "main_inflow": 10.0, "pct_chg": 2.0},
        ]),
        "concept_money_flow": pd.DataFrame([
            {"trade_date": date(2024, 1, 1), "concept_code": "C1", "concept_name": "AI", "main_inflow": 20.0, "pct_chg": 4.0, "limit_count": 3, "net_amount": 20.0},
            {"trade_date": date(2024, 1, 2), "concept_code": "C1", "concept_name": "AI", "main_inflow": 15.0, "pct_chg": 3.0, "limit_count": 2, "net_amount": 15.0},
        ]),
        "stock_money_flow": pd.DataFrame([
            {"trade_date": date(2024, 1, 2), "ts_code": "000001.SZ", "name": "PingAn", "main_inflow": 11.0, "pct_chg": 2.1},
        ]),
        "hk_hold": pd.DataFrame([
            {"trade_date": date(2024, 1, 2), "ts_code": "000001.SZ", "name": "PingAn", "vol": 100.0, "ratio": 1.2, "exchange": "SZ"},
        ]),
    }
    market = FakeStore(frames)
    meta = FakeStore(frames)
    return ReviewDataCollector(market, meta), market, meta


def test_collect_returns_full_snapshot():
    collector, _, _ = make_collector()
    result = collector.collect(date(2024, 1, 2))

    assert result.trade_date == date(2024, 1, 2)
    assert result.index_perf["000001.SH"]["close"] == 3000.0
    assert result.breadth["net"] == 1
    assert result.limit_stats["limit_up"] == 2
    assert len(result.limit_up_details) == 3
    assert result.consecutive_limits[0]["limit_times"] == 3
    assert result.top_industries_in[0]["name"] == "银行"
    assert result.top_concepts_in[0]["name"] == "AI"
    assert result.top_stocks_in[0]["name"] == "PingAn"
    assert result.north_flow["north_net_amount"] == 100.0


def test_postgres_query_store_replaces_all_named_placeholders() -> None:
    from review.main import PostgresQueryStore

    class FakeCursor:
        def __init__(self) -> None:
            self.executed: tuple[str, list[object] | None] | None = None
            self.description = []

        def execute(self, statement, values=None):
            self.executed = (statement, values)

        def fetchall(self):
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConn:
        def __init__(self, cursor: FakeCursor) -> None:
            self._cursor = cursor

        def cursor(self):
            return self._cursor

        def close(self):
            return None

    store = PostgresQueryStore.__new__(PostgresQueryStore)
    cursor = FakeCursor()
    store._conn = FakeConn(cursor)

    store.query(
        "SELECT * FROM concept_money_flow WHERE trade_date = :trade_date ORDER BY main_inflow DESC LIMIT :limit",
        {"trade_date": "2026-05-19", "limit": 3},
    )

    assert cursor.executed == (
        "SELECT * FROM concept_money_flow WHERE trade_date = %s ORDER BY main_inflow DESC LIMIT %s",
        ["2026-05-19", 3],
    )


def test_collect_index_perf_queries_index_daily():
    collector, market, _ = make_collector()
    collector._collect_index_perf(date(2024, 1, 2))

    sql, params = market.queries[-1]
    assert "FROM index_daily" in sql
    assert params == {"trade_date": date(2024, 1, 2)}


def test_collect_breadth_computes_net():
    collector, _, _ = make_collector()
    assert collector._collect_breadth(date(2024, 1, 2)) == {"up": 2, "down": 1, "flat": 3, "net": 1}


def test_collect_limit_stats_uses_limit_list():
    collector, market, _ = make_collector()
    stats = collector._collect_limit_stats(date(2024, 1, 2))

    assert stats["limit_up"] == 2
    assert stats["broken"] == 1
    assert round(stats["broken_rate"], 3) == 0.5
    assert any('"limit" = \'U\'' in sql for sql, _ in market.queries)


def test_collect_prev_hot_review_links_yesterday_hot_concepts():
    collector, _, _ = make_collector()
    result = collector._collect_prev_hot_review(date(2024, 1, 2))

    assert result[0]["concept_code"] == "C1"
    assert result[0]["verdict"] in {"延续", "掉队"}
