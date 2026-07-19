"""Unit tests for data updater orchestration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import Future
from datetime import date
from threading import Event, Lock, Thread
from time import sleep
from typing import Any, Literal

import pandas as pd
import pytest

from data.updater.adj_factor_updater import AdjFactorUpdater
from data.updater.base import BaseUpdater
from data.updater.basic_updater import BasicUpdater
from data.updater.calendar_updater import CalendarUpdater
from data.updater.daily_bar_updater import DailyBarUpdater
from data.updater.daily_basic_updater import DailyBasicUpdater
from data.updater.daily_updater import DailyUpdater
from data.updater.finance_updater import FinanceUpdater
from data.updater.hk_hold_updater import HkHoldUpdater
from data.updater.holdertrade_updater import HoldertradeUpdater
from data.updater.index_daily_updater import IndexDailyUpdater
from data.updater.init_loader import InitLoader
from data.updater.limit_list_updater import LimitListUpdater
from data.updater.margin_updater import MarginUpdater
from data.updater.member_updater import MemberUpdater
from data.updater.minute_bar_updater import MinuteBarUpdater
from data.updater.money_flow_updater import MoneyFlowUpdater
from data.updater.scheduler import UpdateScheduler
from data.updater.suspend_updater import SuspendUpdater
from data.updater.top_list_updater import TopListUpdater
from interfaces.data_source import IDataSource
from interfaces.market_store import IMarketStore
from interfaces.meta_store import IMetaStore


class RecordingStore(IMarketStore, IMetaStore):
    """Spy store that records schema and upsert calls."""

    def __init__(self) -> None:
        self.init_calls = 0
        self.upserts: list[tuple[str, pd.DataFrame]] = []
        self.closed = False

    def init_schema(self) -> None:
        self.init_calls += 1

    def upsert(self, table: str, df: pd.DataFrame) -> int:
        self.upserts.append((table, df.copy()))
        return len(df.index)

    def query(self, sql: str, params: Mapping[str, Any] | None = None) -> pd.DataFrame:
        del sql, params
        return pd.DataFrame()

    def execute(self, sql: str, params: Mapping[str, Any] | None = None) -> int:
        del sql, params
        return 0

    def get_last_date(self, table: str, ts_code: str | None = None) -> date | None:
        del table, ts_code
        return None

    def count(self, table: str, where: str | None = None) -> int:
        del table, where
        return 0

    def close(self) -> None:
        self.closed = True


class RecordingSource(IDataSource):
    """Spy source that returns pre-baked frames per endpoint."""

    name = "recording"

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.frames = {
            "stock_basic": pd.DataFrame([{"ts_code": "000001.SZ", "name": "平安银行"}]),
            "trade_calendar": pd.DataFrame([{"exchange": "SSE", "cal_date": date(2024, 1, 2), "is_open": 1}]),
            "daily_bar": pd.DataFrame(
                [{
                    "ts_code": "000001.SZ",
                    "trade_date": date(2024, 1, 2),
                    "open": 10.0,
                    "high": 10.8,
                    "low": 9.9,
                    "close": 10.5,
                    "change": 0.5,
                    "pct_chg": 5.0,
                    "vol": 1000.0,
                    "amount": 10500.0,
                }]
            ),
            "minute_bar": pd.DataFrame(
                [{
                    "ts_code": "000001.SZ",
                    "datetime": pd.Timestamp("2024-01-02 09:31:00"),
                    "freq": "1min",
                    "open": 10.0,
                    "high": 10.2,
                    "low": 9.9,
                    "close": 10.1,
                    "vol": 100.0,
                    "amount": 1000.0,
                }]
            ),
            "daily_basic": pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": date(2024, 1, 2)}]),
            "adj_factor": pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": date(2024, 1, 2), "adj_factor": 1.0}]),
            "index_daily": pd.DataFrame([{"ts_code": "000300.SH", "trade_date": date(2024, 1, 2)}]),
            "limit_pool": pd.DataFrame([{"trade_date": date(2024, 1, 2), "ts_code": "000001.SZ", "limit": "U"}]),
            "stock_suspend": pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": date(2024, 1, 2), "suspend_type": "S"}]),
            "top_list": pd.DataFrame([{"trade_date": date(2024, 1, 2), "ts_code": "000001.SZ"}]),
            "margin_detail": pd.DataFrame([{"trade_date": date(2024, 1, 2), "ts_code": "000001.SZ"}]),
            "hk_hold": pd.DataFrame([{"trade_date": date(2024, 1, 2), "ts_code": "000001.SZ"}]),
            "concept_money_flow": pd.DataFrame([{"trade_date": date(2024, 1, 2), "concept_code": "CON001"}]),
            "industry_money_flow": pd.DataFrame([{"trade_date": date(2024, 1, 2), "industry_code": "IND001"}]),
            "stock_money_flow": pd.DataFrame([{"trade_date": date(2024, 1, 2), "ts_code": "000001.SZ"}]),
            "income": pd.DataFrame([{"ts_code": "000001.SZ", "end_date": date(2023, 12, 31), "report_type": "1"}]),
            "balancesheet": pd.DataFrame([{"ts_code": "000001.SZ", "end_date": date(2023, 12, 31), "report_type": "1"}]),
            "cashflow": pd.DataFrame([{"ts_code": "000001.SZ", "end_date": date(2023, 12, 31), "report_type": "1"}]),
            "fina_indicator": pd.DataFrame([{"ts_code": "000001.SZ", "end_date": date(2023, 12, 31)}]),
            "dividend": pd.DataFrame([{"ts_code": "000001.SZ", "end_date": date(2023, 12, 31)}]),
            "stk_holdertrade": pd.DataFrame([{"ts_code": "000001.SZ", "ann_date": date(2024, 1, 2)}]),
            "concept_list": pd.DataFrame([{"concept_code": "CON001", "concept_name": "AI"}]),
            "concept_member": pd.DataFrame([{"concept_code": "CON001", "ts_code": "000001.SZ"}]),
            "industry_list": pd.DataFrame([{"industry_code": "IND001", "industry_name": "银行"}]),
            "industry_member": pd.DataFrame([{"industry_code": "IND001", "ts_code": "000001.SZ"}]),
            "index_weight": pd.DataFrame([{"index_code": "000300.SH", "trade_date": date(2024, 1, 2), "ts_code": "000001.SZ"}]),
        }

    def _record(self, name: str, *args: Any, **kwargs: Any) -> pd.DataFrame:
        self.calls.append((name, args, kwargs))
        return self.frames[name].copy()

    def fetch_stock_basic(self) -> pd.DataFrame:
        return self._record("stock_basic")

    def fetch_trade_calendar(self, start_date: date, end_date: date) -> pd.DataFrame:
        return self._record("trade_calendar", start_date, end_date)

    def fetch_daily_bar(
        self,
        ts_code: str | list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        return self._record("daily_bar", ts_code, start_date, end_date)

    def fetch_minute_bar(self, ts_code: str, start_date: date, end_date: date, freq: str = "1min") -> pd.DataFrame:
        return self._record("minute_bar", ts_code, start_date, end_date, freq)

    def fetch_daily_basic(
        self,
        ts_code: str | list[str] | None = None,
        trade_date: date | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        return self._record("daily_basic", ts_code, trade_date, start_date, end_date)

    def fetch_adj_factor(
        self,
        ts_code: str | list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        return self._record("adj_factor", ts_code, start_date, end_date)

    def fetch_index_daily(
        self, ts_code: str, start_date: date | None = None, end_date: date | None = None
    ) -> pd.DataFrame:
        return self._record("index_daily", ts_code, start_date, end_date)

    def fetch_limit_pool(self, trade_date: date, kind: str = "U") -> pd.DataFrame:
        return self._record("limit_pool", trade_date, kind)

    def fetch_stock_suspend(self, trade_date: date | None = None, ts_code: str | None = None) -> pd.DataFrame:
        return self._record("stock_suspend", trade_date, ts_code)

    def fetch_top_list(self, trade_date: date) -> pd.DataFrame:
        return self._record("top_list", trade_date)

    def fetch_margin_detail(self, trade_date: date) -> pd.DataFrame:
        return self._record("margin_detail", trade_date)

    def fetch_hk_hold(self, trade_date: date | None = None, ts_code: str | None = None) -> pd.DataFrame:
        return self._record("hk_hold", trade_date, ts_code)

    def fetch_concept_money_flow(self, trade_date: date) -> pd.DataFrame:
        return self._record("concept_money_flow", trade_date)

    def fetch_industry_money_flow(self, trade_date: date) -> pd.DataFrame:
        return self._record("industry_money_flow", trade_date)

    def fetch_stock_money_flow(self, trade_date: date) -> pd.DataFrame:
        return self._record("stock_money_flow", trade_date)

    def fetch_income(self, ts_code: str, start_date: date | None = None, end_date: date | None = None) -> pd.DataFrame:
        return self._record("income", ts_code, start_date, end_date)

    def fetch_balancesheet(
        self, ts_code: str, start_date: date | None = None, end_date: date | None = None
    ) -> pd.DataFrame:
        return self._record("balancesheet", ts_code, start_date, end_date)

    def fetch_cashflow(self, ts_code: str, start_date: date | None = None, end_date: date | None = None) -> pd.DataFrame:
        return self._record("cashflow", ts_code, start_date, end_date)

    def fetch_fina_indicator(
        self, ts_code: str, start_date: date | None = None, end_date: date | None = None
    ) -> pd.DataFrame:
        return self._record("fina_indicator", ts_code, start_date, end_date)

    def fetch_dividend(self, ts_code: str) -> pd.DataFrame:
        return self._record("dividend", ts_code)

    def fetch_stk_holdertrade(self, ts_code: str | None = None, ann_date: date | None = None) -> pd.DataFrame:
        return self._record("stk_holdertrade", ts_code, ann_date)

    def fetch_concept_list(self) -> pd.DataFrame:
        return self._record("concept_list")

    def fetch_concept_member(self, concept_code: str) -> pd.DataFrame:
        return self._record("concept_member", concept_code)

    def fetch_industry_list(self) -> pd.DataFrame:
        return self._record("industry_list")

    def fetch_industry_member(self, industry_code: str) -> pd.DataFrame:
        return self._record("industry_member", industry_code)

    def fetch_index_weight(self, index_code: str, trade_date: date | None = None) -> pd.DataFrame:
        return self._record("index_weight", index_code, trade_date)


class DummyUpdater:
    """Test double for scheduler delegation checks."""

    def __init__(self, result: dict[str, int]) -> None:
        self.result = result
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.closed = False

    def run(self, *args: Any, **kwargs: Any) -> dict[str, int]:
        self.calls.append(("run", args, kwargs))
        return self.result

    def close(self) -> None:
        self.closed = True


class ConcreteUpdater(BaseUpdater):
    """Concrete updater used to verify the base class contract."""

    def run(self) -> dict[str, int]:
        return {"ok": 1}


def test_base_updater_is_abstract_and_closes_stores() -> None:
    """BaseUpdater should be abstract while still managing shared resources."""
    base_updater_cls: type[Any] = BaseUpdater
    with pytest.raises(TypeError):
        base_updater_cls()

    market_store = RecordingStore()
    meta_store = RecordingStore()
    updater = ConcreteUpdater(source=RecordingSource(), market_store=market_store, meta_store=meta_store)

    assert updater.run() == {"ok": 1}
    updater.close()
    assert market_store.closed is True
    assert meta_store.closed is True


def test_init_loader_initializes_schemas_and_routes_tables() -> None:
    """Bootstrap loading writes reference tables to the expected stores."""
    source = RecordingSource()
    market_store = RecordingStore()
    meta_store = RecordingStore()
    loader = InitLoader(source=source, market_store=market_store, meta_store=meta_store)

    counts = loader.run(
        ts_codes=["000001.SZ"],
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 2),
        index_codes=["000300.SH"],
        trade_date=date(2024, 1, 2),
    )

    assert market_store.init_calls == 1
    assert meta_store.init_calls == 1
    assert [table for table, _ in meta_store.upserts] == ["stock_basic", "trade_calendar"]
    assert [table for table, _ in market_store.upserts] == [
        "daily_bar",
        "daily_basic",
        "adj_factor",
        "index_daily",
        "limit_list",
    ]
    assert counts["daily_bar"] == 1
    assert counts["index_daily:000300.SH"] == 1
    assert counts["limit_list"] == 1


def test_single_table_market_updaters_route_to_market_store() -> None:
    """Market updaters should write each standardized table to DuckDB."""
    source = RecordingSource()
    market_store = RecordingStore()
    meta_store = RecordingStore()

    daily_bar = DailyBarUpdater(source=source, market_store=market_store, meta_store=meta_store)
    adj_factor = AdjFactorUpdater(source=source, market_store=market_store, meta_store=meta_store)
    daily_basic = DailyBasicUpdater(source=source, market_store=market_store, meta_store=meta_store)
    index_daily = IndexDailyUpdater(source=source, market_store=market_store, meta_store=meta_store)
    minute_bar = MinuteBarUpdater(source=source, market_store=market_store, meta_store=meta_store)
    limit_list = LimitListUpdater(source=source, market_store=market_store, meta_store=meta_store)

    assert daily_bar.run(["000001.SZ"], date(2024, 1, 2), date(2024, 1, 2)) == {"daily_bar": 1}
    assert adj_factor.run(["000001.SZ"], date(2024, 1, 2), date(2024, 1, 2)) == {"adj_factor": 1}
    assert daily_basic.run(["000001.SZ"], trade_date=date(2024, 1, 2)) == {"daily_basic": 1}
    assert index_daily.run(["000300.SH"], date(2024, 1, 2), date(2024, 1, 2)) == {"index_daily:000300.SH": 1}
    assert minute_bar.run("000001.SZ", date(2024, 1, 2), date(2024, 1, 2), freq="1min") == {"minute_bar": 1}
    assert limit_list.run(date(2024, 1, 2), kind="U") == {"limit_list": 1}

    assert [table for table, _ in market_store.upserts] == [
        "daily_bar",
        "adj_factor",
        "daily_basic",
        "index_daily",
        "minute_bar",
        "limit_list",
    ]
    assert meta_store.upserts == []


def test_minute_bar_updater_defaults_to_all_market_symbols_when_ts_code_is_omitted() -> None:
    """Minute-bar updater should expand to all stock_basic symbols and walk newest chunks first."""
    source = RecordingSource()
    source.frames["stock_basic"] = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "name": "平安银行"},
            {"ts_code": "600000.SH", "name": "浦发银行"},
        ]
    )
    market_store = RecordingStore()
    updater = MinuteBarUpdater(source=source, market_store=market_store, meta_store=RecordingStore())

    counts = updater.run(start_date=date(2024, 1, 1), end_date=date(2024, 2, 5), freq="5min")

    assert counts == {"minute_bar": 4}
    assert source.calls[1][1:] == ("000001.SZ", date(2024, 1, 31), date(2024, 2, 5), "5min")
    assert source.calls[2][1:] == ("600000.SH", date(2024, 1, 31), date(2024, 2, 5), "5min")
    assert source.calls[3][1:] == ("000001.SZ", date(2024, 1, 1), date(2024, 1, 30), "5min")
    assert source.calls[4][1:] == ("600000.SH", date(2024, 1, 1), date(2024, 1, 30), "5min")


def test_minute_bar_updater_logs_reverse_date_progress_for_all_market_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Full-market minute-bar mode should persist newest chunks first for each stock."""

    class ReverseDailySource(RecordingSource):
        def __init__(self) -> None:
            super().__init__()
            self.frames["stock_basic"] = pd.DataFrame(
                [
                    {"ts_code": "000001.SZ", "name": "平安银行"},
                    {"ts_code": "600000.SH", "name": "浦发银行"},
                ]
            )

        def fetch_minute_bar(self, ts_code: str, start_date: date, end_date: date, freq: str = "1min") -> pd.DataFrame:
            self.calls.append(("minute_bar", (ts_code, start_date, end_date, freq), {}))
            return pd.DataFrame(
                [
                    {
                        "ts_code": ts_code,
                        "datetime": pd.Timestamp(f"{start_date.isoformat()} 09:35:00"),
                        "freq": freq,
                        "open": 10.0,
                        "high": 10.2,
                        "low": 9.9,
                        "close": 10.1,
                        "vol": 100.0,
                        "amount": 1000.0,
                    }
                ]
            )

    class RecordingLogger:
        def __init__(self) -> None:
            self.messages: list[str] = []

        def info(self, message: str, *args: Any) -> None:
            self.messages.append(message.format(*args) if args else message)

    logger = RecordingLogger()
    monkeypatch.setattr("data.updater.minute_bar_updater.logger", logger)

    source = ReverseDailySource()
    market_store = RecordingStore()
    updater = MinuteBarUpdater(source=source, market_store=market_store, meta_store=RecordingStore())

    counts = updater.run(start_date=date(2024, 1, 1), end_date=date(2024, 2, 5), freq="5min")

    assert counts == {"minute_bar": 4}
    assert set(logger.messages) == {
        "minute_bar progress ts_code=000001.SZ chunk=1/2 range=2024-01-31..2024-02-05 chunk_rows=1 total_rows=1",
        "minute_bar progress ts_code=600000.SH chunk=1/2 range=2024-01-31..2024-02-05 chunk_rows=1 total_rows=2",
        "minute_bar progress ts_code=000001.SZ chunk=2/2 range=2024-01-01..2024-01-30 chunk_rows=1 total_rows=3",
        "minute_bar progress ts_code=600000.SH chunk=2/2 range=2024-01-01..2024-01-30 chunk_rows=1 total_rows=4",
    }


def test_minute_bar_updater_persists_each_chunk_and_logs_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    """Minute-bar updater should upsert each chunk immediately and emit progress logs."""

    class ChunkedMinuteSource(RecordingSource):
        def fetch_minute_bar(self, ts_code: str, start_date: date, end_date: date, freq: str = "1min") -> pd.DataFrame:
            self.calls.append(("minute_bar", (ts_code, start_date, end_date, freq), {}))
            return pd.DataFrame(
                [
                    {
                        "ts_code": ts_code,
                        "datetime": pd.Timestamp(f"{start_date.isoformat()} 09:35:00"),
                        "freq": freq,
                        "open": 10.0,
                        "high": 10.2,
                        "low": 9.9,
                        "close": 10.1,
                        "vol": 100.0,
                        "amount": 1000.0,
                    }
                ]
            )

    class RecordingLogger:
        def __init__(self) -> None:
            self.messages: list[str] = []

        def info(self, message: str, *args: Any) -> None:
            self.messages.append(message.format(*args) if args else message)

    logger = RecordingLogger()
    monkeypatch.setattr("data.updater.minute_bar_updater.logger", logger)

    source = ChunkedMinuteSource()
    market_store = RecordingStore()
    updater = MinuteBarUpdater(source=source, market_store=market_store, meta_store=RecordingStore())

    counts = updater.run(
        ts_code="000001.SZ",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 25),
        freq="5min",
    )

    assert counts == {"minute_bar": 1}
    assert [call[0] for call in source.calls] == ["minute_bar"]
    assert source.calls[0][1] == ("000001.SZ", date(2024, 1, 1), date(2024, 1, 25), "5min")
    assert [table for table, _ in market_store.upserts] == ["minute_bar"]
    assert logger.messages == [
        "minute_bar progress ts_code=000001.SZ chunk=1/1 range=2024-01-01..2024-01-25 chunk_rows=1 total_rows=1",
    ]


def test_minute_bar_updater_fetches_chunks_concurrently_and_persists_completed_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Minute-bar loading should overlap remote fetches and persist whichever chunk finishes first."""
    source = RecordingSource()
    market_store = RecordingStore()
    updater = MinuteBarUpdater(source=source, market_store=market_store, meta_store=RecordingStore())
    queued_calls: list[tuple[str, date, date, str]] = []
    persisted_ranges: list[tuple[date, date]] = []
    release_fetches = Event()
    in_flight = 0
    max_in_flight = 0
    in_flight_lock = Lock()

    def fake_fetch_minute_bar(ts_code: str, start_date: date, end_date: date, freq: str = "1min") -> pd.DataFrame:
        nonlocal in_flight, max_in_flight
        queued_calls.append((ts_code, start_date, end_date, freq))
        with in_flight_lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            if in_flight >= 2:
                release_fetches.set()
        release_fetches.wait(timeout=2)
        with in_flight_lock:
            in_flight -= 1
        return pd.DataFrame(
            [
                {
                    "ts_code": ts_code,
                    "datetime": pd.Timestamp(f"{start_date.isoformat()} 09:31:00"),
                    "freq": freq,
                    "open": 1.0,
                    "high": 1.0,
                    "low": 1.0,
                    "close": 1.0,
                    "vol": 1.0,
                    "amount": 1.0,
                    "chunk_start": start_date,
                    "chunk_end": end_date,
                }
            ]
        )

    original_upsert = market_store.upsert

    def recording_upsert(table: str, df: pd.DataFrame) -> int:
        persisted_ranges.append((df.iloc[0]["chunk_start"], df.iloc[0]["chunk_end"]))
        return original_upsert(table, df)

    class InlineExecutor:
        def __init__(self, max_workers: int) -> None:
            self.max_workers = max_workers

        def __enter__(self) -> InlineExecutor:
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Literal[False]:
            return False

        def submit(self, fn: Any, /, *args: Any, **kwargs: Any) -> Future[pd.DataFrame]:
            future: Future[pd.DataFrame] = Future()

            def run() -> None:
                try:
                    future.set_result(fn(*args, **kwargs))
                except Exception as exc:  # pragma: no cover - forwarded to future
                    future.set_exception(exc)

            Thread(target=run, daemon=True).start()
            return future

    monkeypatch.setattr(source, "fetch_minute_bar", fake_fetch_minute_bar)
    monkeypatch.setattr(market_store, "upsert", recording_upsert)
    monkeypatch.setattr("data.updater.minute_bar_updater.ThreadPoolExecutor", InlineExecutor)
    monkeypatch.setattr("data.updater.minute_bar_updater.settings.minute_bar_stock_workers", 4, raising=False)

    result = updater.run(
        ts_code="000001.SZ",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 3, 31),
        freq="1min",
    )

    assert result == {"minute_bar": 4}
    assert len(queued_calls) == 3
    assert max_in_flight >= 2
    assert sorted(persisted_ranges) == [
        (date(2024, 1, 1), date(2024, 2, 2)),
        (date(2024, 2, 3), date(2024, 3, 6)),
        (date(2024, 3, 7), date(2024, 3, 31)),
    ]



def test_minute_bar_updater_consumes_completed_chunks_without_head_of_line_blocking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Minute-bar updater should persist completed chunks as they finish, not submission order."""
    source = RecordingSource()
    market_store = RecordingStore()
    updater = MinuteBarUpdater(source=source, market_store=market_store, meta_store=RecordingStore())
    persisted_ranges: list[tuple[date, date]] = []

    delay_by_start = {
        date(2024, 3, 7): 0.15,
        date(2024, 2, 3): 0.05,
        date(2024, 1, 1): 0.0,
    }

    def fake_fetch_minute_bar(ts_code: str, start_date: date, end_date: date, freq: str = "1min") -> pd.DataFrame:
        sleep(delay_by_start[start_date])
        return pd.DataFrame(
            [
                {
                    "ts_code": ts_code,
                    "datetime": pd.Timestamp(f"{start_date.isoformat()} 09:31:00"),
                    "freq": freq,
                    "open": 1.0,
                    "high": 1.0,
                    "low": 1.0,
                    "close": 1.0,
                    "vol": 1.0,
                    "amount": 1.0,
                    "chunk_start": start_date,
                    "chunk_end": end_date,
                }
            ]
        )

    original_upsert = market_store.upsert

    def recording_upsert(table: str, df: pd.DataFrame) -> int:
        persisted_ranges.append((df.iloc[0]["chunk_start"], df.iloc[0]["chunk_end"]))
        return original_upsert(table, df)

    class InlineExecutor:
        def __init__(self, max_workers: int) -> None:
            self.max_workers = max_workers

        def __enter__(self) -> InlineExecutor:
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Literal[False]:
            return False

        def submit(self, fn: Any, /, *args: Any, **kwargs: Any) -> Future[pd.DataFrame]:
            future: Future[pd.DataFrame] = Future()

            def run() -> None:
                try:
                    future.set_result(fn(*args, **kwargs))
                except Exception as exc:  # pragma: no cover - forwarded to future
                    future.set_exception(exc)

            Thread(target=run, daemon=True).start()
            return future

    monkeypatch.setattr(source, "fetch_minute_bar", fake_fetch_minute_bar)
    monkeypatch.setattr(market_store, "upsert", recording_upsert)
    monkeypatch.setattr("data.updater.minute_bar_updater.ThreadPoolExecutor", InlineExecutor)
    monkeypatch.setattr("data.updater.minute_bar_updater.settings.minute_bar_stock_workers", 4, raising=False)

    result = updater.run(
        ts_code="000001.SZ",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 3, 31),
        freq="1min",
    )

    assert result == {"minute_bar": 4}
    assert persisted_ranges == [
        (date(2024, 1, 1), date(2024, 2, 2)),
        (date(2024, 2, 3), date(2024, 3, 6)),
        (date(2024, 3, 7), date(2024, 3, 31)),
    ]



def test_minute_bar_updater_processes_multiple_symbols_concurrently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Minute-bar updater should keep multiple symbols in flight up to the configured worker limit."""
    source = RecordingSource()
    market_store = RecordingStore()
    updater = MinuteBarUpdater(source=source, market_store=market_store, meta_store=RecordingStore())
    in_flight_codes: set[str] = set()
    seen_codes: list[str] = []
    max_in_flight = 0
    lock = Lock()

    def fake_fetch_minute_bar(ts_code: str, start_date: date, end_date: date, freq: str = "1min") -> pd.DataFrame:
        nonlocal max_in_flight
        with lock:
            in_flight_codes.add(ts_code)
            seen_codes.append(ts_code)
            max_in_flight = max(max_in_flight, len(in_flight_codes))
        sleep(0.05)
        with lock:
            in_flight_codes.remove(ts_code)
        return pd.DataFrame(
            [
                {
                    "ts_code": ts_code,
                    "datetime": pd.Timestamp(f"{start_date.isoformat()} 09:31:00"),
                    "freq": freq,
                    "open": 1.0,
                    "high": 1.0,
                    "low": 1.0,
                    "close": 1.0,
                    "vol": 1.0,
                    "amount": 1.0,
                }
            ]
        )

    class InlineExecutor:
        def __init__(self, max_workers: int) -> None:
            self.max_workers = max_workers

        def __enter__(self) -> InlineExecutor:
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Literal[False]:
            return False

        def submit(self, fn: Any, /, *args: Any, **kwargs: Any) -> Future[pd.DataFrame]:
            future: Future[pd.DataFrame] = Future()

            def run() -> None:
                try:
                    future.set_result(fn(*args, **kwargs))
                except Exception as exc:  # pragma: no cover - forwarded to future
                    future.set_exception(exc)

            Thread(target=run, daemon=True).start()
            return future

    monkeypatch.setattr(source, "fetch_minute_bar", fake_fetch_minute_bar)
    monkeypatch.setattr("data.updater.minute_bar_updater.ThreadPoolExecutor", InlineExecutor)
    monkeypatch.setattr("data.updater.minute_bar_updater.settings.minute_bar_stock_workers", 2, raising=False)

    result = updater.run(
        start_date=date(2024, 3, 1),
        end_date=date(2024, 3, 31),
        freq="1min",
        ts_codes=["000001.SZ", "000002.SZ", "000003.SZ"],
    )

    assert result == {"minute_bar": 4}
    assert max_in_flight == 2
    assert seen_codes[:2] == ["000001.SZ", "000002.SZ"]
    assert set(seen_codes) == {"000001.SZ", "000002.SZ", "000003.SZ"}



def test_minute_bar_updater_logs_waiting_heartbeat_when_no_chunk_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Minute-bar updater should emit a heartbeat when all in-flight chunks are still waiting."""
    source = RecordingSource()
    market_store = RecordingStore()
    updater = MinuteBarUpdater(source=source, market_store=market_store, meta_store=RecordingStore())
    warnings: list[str] = []

    def fake_fetch_minute_bar(ts_code: str, start_date: date, end_date: date, freq: str = "1min") -> pd.DataFrame:
        sleep(0.02)
        return pd.DataFrame(
            [
                {
                    "ts_code": ts_code,
                    "datetime": pd.Timestamp(f"{start_date.isoformat()} 09:31:00"),
                    "freq": freq,
                    "open": 1.0,
                    "high": 1.0,
                    "low": 1.0,
                    "close": 1.0,
                    "vol": 1.0,
                    "amount": 1.0,
                }
            ]
        )

    original_wait = __import__('data.updater.minute_bar_updater', fromlist=['wait']).wait
    heartbeat_seen = False

    def fake_wait(fs: Any, timeout: float | None = None, return_when: Any = None) -> tuple[set[Future[Any]], set[Future[Any]]]:
        nonlocal heartbeat_seen
        if not heartbeat_seen:
            heartbeat_seen = True
            return set(), set(fs)
        return original_wait(fs, timeout=timeout, return_when=return_when)

    class DummyLogger:
        def info(self, message: str) -> None:
            pass

        def warning(self, message: str) -> None:
            warnings.append(message)

    monkeypatch.setattr(source, "fetch_minute_bar", fake_fetch_minute_bar)
    monkeypatch.setattr("data.updater.minute_bar_updater.wait", fake_wait)
    monkeypatch.setattr("data.updater.minute_bar_updater.logger", DummyLogger())
    monkeypatch.setattr("data.updater.minute_bar_updater.settings.minute_bar_stock_workers", 2, raising=False)
    monkeypatch.setattr("data.updater.minute_bar_updater.WAIT_HEARTBEAT_SECONDS", 1, raising=False)

    result = updater.run(
        start_date=date(2024, 3, 1),
        end_date=date(2024, 3, 31),
        freq="1min",
        ts_codes=["000001.SZ", "000002.SZ"],
    )

    assert result == {"minute_bar": 4}
    assert warnings
    assert "minute_bar waiting for remote chunk results" in warnings[0]
    assert "pending_futures=2" in warnings[0]
    assert "000001.SZ" in warnings[0]
    assert "000002.SZ" in warnings[0]



def test_minute_bar_updater_fails_fast_after_repeated_no_progress_waits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Minute-bar updater should raise with chunk details after sustained no-progress waits."""
    source = RecordingSource()
    market_store = RecordingStore()
    updater = MinuteBarUpdater(source=source, market_store=market_store, meta_store=RecordingStore())
    warnings: list[str] = []

    def fake_fetch_minute_bar(ts_code: str, start_date: date, end_date: date, freq: str = "1min") -> pd.DataFrame:
        sleep(0.05)
        return pd.DataFrame(
            [
                {
                    "ts_code": ts_code,
                    "datetime": pd.Timestamp(f"{start_date.isoformat()} 09:31:00"),
                    "freq": freq,
                    "open": 1.0,
                    "high": 1.0,
                    "low": 1.0,
                    "close": 1.0,
                    "vol": 1.0,
                    "amount": 1.0,
                }
            ]
        )

    wait_calls = 0

    def fake_wait(fs: Any, timeout: float | None = None, return_when: Any = None) -> tuple[set[Future[Any]], set[Future[Any]]]:
        nonlocal wait_calls
        wait_calls += 1
        return set(), set(fs)

    class DummyLogger:
        def info(self, message: str) -> None:
            pass

        def warning(self, message: str) -> None:
            warnings.append(message)

    monkeypatch.setattr(source, "fetch_minute_bar", fake_fetch_minute_bar)
    monkeypatch.setattr("data.updater.minute_bar_updater.wait", fake_wait)
    monkeypatch.setattr("data.updater.minute_bar_updater.logger", DummyLogger())
    monkeypatch.setattr("data.updater.minute_bar_updater.settings.minute_bar_stock_workers", 2, raising=False)
    monkeypatch.setattr("data.updater.minute_bar_updater.WAIT_HEARTBEAT_SECONDS", 1, raising=False)
    monkeypatch.setattr("data.updater.minute_bar_updater.MAX_NO_PROGRESS_HEARTBEATS", 2, raising=False)

    with pytest.raises(TimeoutError, match="minute_bar multi-code stalled") as exc_info:
        updater.run(
            start_date=date(2024, 3, 1),
            end_date=date(2024, 3, 31),
            freq="1min",
            ts_codes=["000001.SZ", "000002.SZ"],
        )

    assert wait_calls == 2
    assert len(warnings) == 2
    assert "pending_futures=2" in str(exc_info.value)
    assert "000001.SZ" in str(exc_info.value)
    assert "000002.SZ" in str(exc_info.value)



def test_meta_single_table_updaters_route_to_postgres() -> None:
    """Metadata updaters should persist the matching tables into Postgres."""
    source = RecordingSource()
    market_store = RecordingStore()
    meta_store = RecordingStore()

    assert BasicUpdater(source=source, market_store=market_store, meta_store=meta_store).run() == {"stock_basic": 1}
    assert CalendarUpdater(source=source, market_store=market_store, meta_store=meta_store).run(
        date(2024, 1, 1), date(2024, 1, 3)
    ) == {"trade_calendar": 1}
    assert TopListUpdater(source=source, market_store=market_store, meta_store=meta_store).run(date(2024, 1, 2)) == {
        "top_list": 1
    }
    assert MarginUpdater(source=source, market_store=market_store, meta_store=meta_store).run(date(2024, 1, 2)) == {
        "margin_detail": 1
    }
    assert HkHoldUpdater(source=source, market_store=market_store, meta_store=meta_store).run(
        trade_date=date(2024, 1, 2)
    ) == {"hk_hold": 1}
    assert SuspendUpdater(source=source, market_store=market_store, meta_store=meta_store).run(
        trade_date=date(2024, 1, 2)
    ) == {"stock_suspend": 1}
    assert HoldertradeUpdater(source=source, market_store=market_store, meta_store=meta_store).run(
        ts_code="000001.SZ", ann_date=date(2024, 1, 2)
    ) == {"stk_holdertrade": 1}

    assert market_store.upserts == []
    assert [table for table, _ in meta_store.upserts] == [
        "stock_basic",
        "trade_calendar",
        "top_list",
        "margin_detail",
        "hk_hold",
        "stock_suspend",
        "stk_holdertrade",
    ]


def test_money_flow_updater_persists_all_three_tables() -> None:
    """Money-flow updater should fetch and persist concept, industry, and stock flows."""
    source = RecordingSource()
    updater = MoneyFlowUpdater(source=source, market_store=RecordingStore(), meta_store=RecordingStore())

    counts = updater.run(date(2024, 1, 2))

    assert counts == {
        "concept_money_flow": 1,
        "industry_money_flow": 1,
        "stock_money_flow": 1,
    }
    assert [call[0] for call in source.calls[-3:]] == [
        "concept_money_flow",
        "industry_money_flow",
        "stock_money_flow",
    ]


def test_member_updater_persists_concept_industry_and_index_members() -> None:
    """Member updater should expand each requested membership list into separate tables."""
    source = RecordingSource()
    market_store = RecordingStore()
    meta_store = RecordingStore()
    updater = MemberUpdater(source=source, market_store=market_store, meta_store=meta_store)

    counts = updater.run(
        concept_codes=["CON001"],
        industry_codes=["IND001"],
        index_codes=["000300.SH"],
        trade_date=date(2024, 1, 2),
    )

    assert counts == {
        "concept_list": 1,
        "concept_member:CON001": 1,
        "industry_list": 1,
        "industry_member:IND001": 1,
        "index_weight:000300.SH": 1,
    }
    assert market_store.upserts == []
    assert [table for table, _ in meta_store.upserts] == [
        "concept_list",
        "concept_member",
        "industry_list",
        "industry_member",
        "index_weight",
    ]


def test_finance_updater_routes_financial_tables_for_each_symbol() -> None:
    """Financial refresh loads all quarterly tables into metadata storage."""
    source = RecordingSource()
    market_store = RecordingStore()
    meta_store = RecordingStore()
    updater = FinanceUpdater(source=source, market_store=market_store, meta_store=meta_store)

    counts = updater.run(
        ts_codes=["000001.SZ", "000002.SZ"],
        start_date=date(2023, 1, 1),
        end_date=date(2023, 12, 31),
    )

    assert market_store.upserts == []
    assert [table for table, _ in meta_store.upserts] == [
        "income",
        "balancesheet",
        "cashflow",
        "fina_indicator",
        "dividend",
        "income",
        "balancesheet",
        "cashflow",
        "fina_indicator",
        "dividend",
    ]
    assert counts == {
        "income": 2,
        "balancesheet": 2,
        "cashflow": 2,
        "fina_indicator": 2,
        "dividend": 2,
    }


def test_scheduler_delegates_and_closes_child_updaters() -> None:
    """Scheduler methods forward arguments to the child update services."""
    init_loader = DummyUpdater({"init": 1})
    daily_updater = DummyUpdater({"daily": 2})
    finance_updater = DummyUpdater({"finance": 3})
    scheduler = UpdateScheduler(
        init_loader=init_loader,
        daily_updater=daily_updater,
        finance_updater=finance_updater,
    )

    assert scheduler.run_full_load(["000001.SZ"], date(2024, 1, 1), date(2024, 1, 2)) == {"init": 1}
    assert scheduler.run_daily(date(2024, 1, 2), ["000001.SZ"]) == {"daily": 2}
    assert scheduler.run_finance(["000001.SZ"]) == {"finance": 3}

    scheduler.close()
    assert init_loader.closed is True
    assert daily_updater.closed is True
    assert finance_updater.closed is True


def test_daily_updater_run_executes_all_child_updaters(monkeypatch: pytest.MonkeyPatch) -> None:
    trade_date = date(2024, 2, 29)
    ts_codes = ["000001.SZ", "600000.SH"]
    index_codes = ["000300.SH"]
    updater = DailyUpdater(source=RecordingSource(), market_store=RecordingStore(), meta_store=RecordingStore())
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def install(name: str, result: dict[str, int]) -> None:
        class StubUpdater(BaseUpdater):
            def run(self, *args: object, **kwargs: object) -> dict[str, int]:
                calls.append((name, args, kwargs))
                return result

        monkeypatch.setattr(f"data.updater.daily_updater.{name}", StubUpdater)

    install("DailyBarUpdater", {"daily_bar": 2})
    install("DailyBasicUpdater", {"daily_basic": 2})
    install("AdjFactorUpdater", {"adj_factor": 2})
    install("IndexDailyUpdater", {"index_daily": 1})
    install("LimitListUpdater", {"limit_list": 3})
    install("SuspendUpdater", {"suspend": 1})
    install("TopListUpdater", {"top_list": 1})
    install("MarginUpdater", {"margin": 1})
    install("HkHoldUpdater", {"hk_hold": 1})
    install("MoneyFlowUpdater", {"money_flow": 1})

    result = updater.run(trade_date, ts_codes, index_codes)

    assert result == {
        "daily_bar": 2,
        "daily_basic": 2,
        "adj_factor": 2,
        "index_daily": 1,
        "limit_list": 3,
        "suspend": 1,
        "top_list": 1,
        "margin": 1,
        "hk_hold": 1,
        "money_flow": 1,
    }
    assert calls == [
        ("DailyBarUpdater", (ts_codes, trade_date, trade_date), {}),
        ("DailyBasicUpdater", (ts_codes,), {"trade_date": trade_date}),
        ("AdjFactorUpdater", (ts_codes, trade_date, trade_date), {}),
        ("IndexDailyUpdater", (index_codes, trade_date, trade_date), {}),
        ("LimitListUpdater", (trade_date,), {"kind": "U"}),
        ("SuspendUpdater", (), {"trade_date": trade_date}),
        ("TopListUpdater", (trade_date,), {}),
        ("MarginUpdater", (trade_date,), {}),
        ("HkHoldUpdater", (), {"trade_date": trade_date}),
        ("MoneyFlowUpdater", (trade_date,), {}),
    ]


def test_daily_updater_spawn_and_alias_share_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    source = RecordingSource()
    market_store = RecordingStore()
    meta_store = RecordingStore()
    updater = DailyUpdater(source=source, market_store=market_store, meta_store=meta_store)

    spawned = updater._spawn(DailyUpdater)

    assert spawned.source is source
    assert spawned.market_store is market_store
    assert spawned.meta_store is meta_store

    class PreferredCapabilitySource(RecordingSource):
        name = "preferred-capability"

        def supports(self, capability: str) -> bool:
            return capability in {"limit_pool", "hk_hold", "stock_money_flow"}

    requested_sources: list[str] = []

    def fake_get_data_source(name: str) -> IDataSource:
        requested_sources.append(name)
        if name == "tushare":
            return PreferredCapabilitySource()
        return RecordingSource()

    monkeypatch.setattr("data.updater.base.get_data_source", fake_get_data_source)

    assert isinstance(updater._spawn(LimitListUpdater).source, PreferredCapabilitySource)
    assert isinstance(updater._spawn(HkHoldUpdater).source, PreferredCapabilitySource)
    assert isinstance(updater._spawn(MoneyFlowUpdater).source, PreferredCapabilitySource)
    assert requested_sources[:3] == ["tushare", "tushare", "tushare"]

    class AliasProbeDailyUpdater(DailyUpdater):
        def run(
            self,
            trade_date: date,
            ts_codes: Sequence[str],
            index_codes: Sequence[str] | None = None,
        ) -> dict[str, int]:
            return {
                "trade_date_year": trade_date.year,
                "code_count": len(ts_codes),
                "index_count": len(index_codes or []),
            }

    alias_updater = AliasProbeDailyUpdater(source=source, market_store=market_store, meta_store=meta_store)
    assert alias_updater.update_daily_data(date(2024, 2, 29), ["000001.SZ"], ["000300.SH"]) == {
        "trade_date_year": 2024,
        "code_count": 1,
        "index_count": 1,
    }
