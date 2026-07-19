"""Unit tests for P0.9 update scripts."""

from __future__ import annotations

import importlib
import sys
from argparse import Namespace
from datetime import date
from pathlib import Path

import scripts.backfill_day as backfill_day

import pandas as pd
import pytest

SCRIPT_CASES = [
    (
        "scripts.update_basic",
        "BasicUpdater",
        {},
        {"stock_basic": 3},
        "Starting incremental update: basic.",
        "Incremental update complete: basic.",
    ),
    (
        "scripts.update_calendar",
        "CalendarUpdater",
        {"start_date": date(2024, 2, 1), "end_date": date(2024, 2, 29)},
        {"trade_calendar": 8},
        "Starting incremental update: calendar.",
        "Incremental update complete: calendar.",
    ),
    (
        "scripts.update_daily",
        "DailyUpdater",
        {
            "trade_date": date(2024, 2, 29),
            "ts_codes": ["000001.SZ", "600000.SH"],
            "index_codes": ["000300.SH"],
        },
        {"daily_bar": 2, "limit_list": 1},
        "Starting incremental update: daily.",
        "Incremental update complete: daily.",
    ),
    (
        "scripts.update_finance",
        "FinanceUpdater",
        {
            "ts_codes": ["000001.SZ"],
            "start_date": date(2023, 1, 1),
            "end_date": date(2023, 12, 31),
        },
        {"income": 4, "balancesheet": 4},
        "Starting incremental update: finance.",
        "Incremental update complete: finance.",
    ),
    (
        "scripts.update_member",
        "MemberUpdater",
        {
            "concept_codes": ["C01"],
            "industry_codes": ["I01"],
            "index_codes": ["000300.SH"],
            "trade_date": date(2024, 2, 29),
        },
        {"index_weight:000300.SH": 3},
        "Starting incremental update: member.",
        "Incremental update complete: member.",
    ),
    (
        "scripts.update_suspend",
        "SuspendUpdater",
        {"trade_date": date(2024, 2, 29), "ts_code": "000001.SZ"},
        {"stock_suspend": 5},
        "Starting incremental update: suspend.",
        "Incremental update complete: suspend.",
    ),
]


class DummyLogger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, message: str) -> None:
        self.messages.append(message)


@pytest.mark.parametrize(
    ("module_name", "updater_attr", "args_dict", "counts", "start_message", "end_message"),
    SCRIPT_CASES,
)
def test_update_script_invokes_target_updater(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    updater_attr: str,
    args_dict: dict[str, object],
    counts: dict[str, int],
    start_message: str,
    end_message: str,
) -> None:
    module = importlib.import_module(module_name)
    logger = DummyLogger()
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    class FakeUpdater:
        def run(self, *args: object, **kwargs: object) -> dict[str, int]:
            calls.append((args, kwargs))
            return counts

        def close(self) -> None:
            calls.append((("close",), {}))

    monkeypatch.setattr(module, updater_attr, FakeUpdater)
    monkeypatch.setattr(module, "parse_args", lambda argv=None: Namespace(**args_dict))
    monkeypatch.setattr(module, "logger", logger)

    result = module.main()

    assert result == counts
    assert calls[0] == ((), args_dict)
    assert calls[-1] == (("close",), {})
    assert logger.messages == [
        start_message,
        f"Rows loaded: {counts}",
        end_message,
    ]


def test_update_all_runs_incremental_jobs_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("scripts.update_all")
    logger = DummyLogger()
    executed: list[tuple[str, dict[str, object]]] = []

    monkeypatch.setattr(
        module,
        "parse_args",
        lambda argv=None: Namespace(
            trade_date=date(2024, 2, 29),
            start_date=date(2024, 2, 1),
            end_date=date(2024, 2, 29),
            ts_codes=["000001.SZ", "600000.SH"],
            index_codes=["000300.SH"],
            concept_codes=["C01"],
            industry_codes=["I01"],
        ),
    )
    monkeypatch.setattr(module, "logger", logger)

    def fake_run_job(job_name: str, **kwargs: object) -> dict[str, int]:
        executed.append((job_name, dict(kwargs)))
        return {job_name: 1}

    monkeypatch.setattr(module, "run_subjob", fake_run_job)

    result = module.main()

    assert result == {
        "calendar": {"calendar": 1},
        "basic": {"basic": 1},
        "daily": {"daily": 1},
        "member": {"member": 1},
        "finance": {"finance": 1},
        "hk_hold": {"hk_hold": 1},
        "suspend": {"suspend": 1},
    }
    assert executed == [
        ("calendar", {"start_date": date(2024, 2, 1), "end_date": date(2024, 2, 29)}),
        ("basic", {}),
        (
            "daily",
            {
                "trade_date": date(2024, 2, 29),
                "ts_codes": ["000001.SZ", "600000.SH"],
                "index_codes": ["000300.SH"],
            },
        ),
        (
            "member",
            {
                "concept_codes": ["C01"],
                "industry_codes": ["I01"],
                "index_codes": ["000300.SH"],
                "trade_date": date(2024, 2, 29),
            },
        ),
        (
            "finance",
            {
                "ts_codes": ["000001.SZ", "600000.SH"],
                "start_date": date(2024, 2, 1),
                "end_date": date(2024, 2, 29),
            },
        ),
        ("hk_hold", {"trade_date": date(2024, 2, 29)}),
        ("suspend", {"trade_date": date(2024, 2, 29)}),
    ]
    assert logger.messages == [
        "Starting orchestrated incremental update.",
        "Incremental update orchestrator complete.",
    ]


def test_backfill_day_normalize_args_defaults_index_codes() -> None:
    args = Namespace(
        trade_date=date(2026, 5, 19),
        ts_codes=[],
        index_codes=None,
        concept_codes=[],
        industry_codes=[],
        progress_file=Path('logs/backfill_day_progress.jsonl'),
        stop_on_error=False,
    )

    normalized = backfill_day._normalize_args(args)

    assert normalized.index_codes == ['000001.SH', '399001.SZ', '399006.SZ', '000300.SH', '000905.SH']


def test_backfill_day_normalize_args_preserves_explicit_index_codes() -> None:
    args = Namespace(
        trade_date=date(2026, 5, 19),
        ts_codes=[],
        index_codes=['000852.SH'],
        concept_codes=[],
        industry_codes=[],
        progress_file=Path('logs/backfill_day_progress.jsonl'),
        stop_on_error=False,
    )

    normalized = backfill_day._normalize_args(args)

    assert normalized.index_codes == ['000852.SH']


def test_tushare_limit_pool_primary_empty_returns_empty_without_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from data.source.tushare_source import TushareSource

    source = TushareSource(client=object())
    fallback_calls: list[tuple[date, str]] = []

    def fake_call(api_name: str, **kwargs: object) -> pd.DataFrame:
        assert api_name == 'limit_list_d'
        return pd.DataFrame()

    def fake_fallback(trade_date: date, *, kind: str) -> pd.DataFrame:
        fallback_calls.append((trade_date, kind))
        return pd.DataFrame({'trade_date': ['20260519'], 'ts_code': ['000001.SZ']})

    monkeypatch.setattr(source, '_call', fake_call)
    monkeypatch.setattr(source, '_fetch_limit_pool_from_stk_limit', fake_fallback)

    result = source.fetch_limit_pool(date(2026, 5, 19), kind='U')

    assert fallback_calls == [(date(2026, 5, 19), 'U')]
    assert result.to_dict(orient='records') == [{'trade_date': '20260519', 'ts_code': '000001.SZ'}]


def test_full_load_minute_bar_skips_already_loaded_symbols(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("scripts.full_load_minute_bar")
    logger = DummyLogger()
    run_calls: list[dict[str, object]] = []
    progress_events: list[dict[str, object]] = []

    class FakeSource:
        def fetch_stock_basic(self) -> pd.DataFrame:
            return pd.DataFrame(
                {
                    "ts_code": ["000001.SZ", "000002.SZ", "000003.SZ"],
                    "list_date": ["20100101", "20100101", "20240301"],
                    "delist_date": [None, "20240228", None],
                }
            )

        def fetch_trade_calendar(self, start_date: date, end_date: date) -> pd.DataFrame:
            return pd.DataFrame({"is_open": [1, 1], "cal_date": ["20240228", "20240229"]})

    class FakeMarketStore:
        def init_schema(self) -> None:
            progress_events.append({"event": "init_schema"})

        def query(self, sql: str, params: dict[str, object] | None = None) -> pd.DataFrame:
            assert "GROUP BY ts_code" in sql
            assert params is not None
            return pd.DataFrame({"ts_code": ["000001.SZ", "000002.SZ"], "dt": [2, 0]})

    class FakeUpdater:
        def __init__(self) -> None:
            self.source = FakeSource()
            self.market_store = FakeMarketStore()

        def run(self, **kwargs: object) -> dict[str, int]:
            run_calls.append(dict(kwargs))
            return {"minute_bar": 123}

        def close(self) -> None:
            progress_events.append({"event": "close"})

    monkeypatch.setattr(module, "MinuteBarUpdater", FakeUpdater)
    monkeypatch.setattr(module, "logger", logger)
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda argv=None: Namespace(
            ts_code=None,
            ts_codes=[],
            start_date=date(2024, 2, 28),
            end_date=date(2024, 2, 29),
            freq="1min",
            progress_file=None,
        ),
    )

    result = module.main()

    assert result == {"minute_bar": 246}
    assert run_calls == [
        {
            "start_date": date(2024, 2, 28),
            "end_date": date(2024, 2, 29),
            "freq": "1min",
            "ts_code": "000001.SZ",
        },
        {
            "start_date": date(2024, 2, 28),
            "end_date": date(2024, 2, 28),
            "freq": "1min",
            "ts_code": "000002.SZ",
        },
    ]
    assert progress_events == [{"event": "init_schema"}, {"event": "close"}]
    assert logger.messages == [
        "Starting full load: minute_bar.",
        "minute_bar resume scan: requested=2 pending=2 skipped=0 trade_days=2 gap_ranges=2 missing_trade_days=3",
        "Rows loaded: {'minute_bar': 246}",
        "Full load complete: minute_bar.",
    ]


def test_full_load_minute_bar_short_circuits_when_all_requested_symbols_are_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("scripts.full_load_minute_bar")
    logger = DummyLogger()
    progress_events: list[dict[str, object]] = []

    class FakeSource:
        def fetch_stock_basic(self) -> pd.DataFrame:
            return pd.DataFrame({"ts_code": ["000001.SZ"], "list_date": ["20100101"], "delist_date": [None]})

        def fetch_trade_calendar(self, start_date: date, end_date: date) -> pd.DataFrame:
            return pd.DataFrame({"is_open": [1, 1], "cal_date": ["20240228", "20240229"]})

    class FakeMarketStore:
        def init_schema(self) -> None:
            progress_events.append({"event": "init_schema"})

        def query(self, sql: str, params: dict[str, object] | None = None) -> pd.DataFrame:
            assert params is not None
            return pd.DataFrame({"ts_code": ["000001.SZ"], "day_count": [2]})

    class FakeUpdater:
        def __init__(self) -> None:
            self.source = FakeSource()
            self.market_store = FakeMarketStore()

        def run(self, **kwargs: object) -> dict[str, int]:
            raise AssertionError("run() should not be called when no symbols are pending")

        def close(self) -> None:
            progress_events.append({"event": "close"})

    monkeypatch.setattr(module, "MinuteBarUpdater", FakeUpdater)
    monkeypatch.setattr(module, "logger", logger)

    counts = module.run_job(
        ts_codes=["000001.SZ"],
        start_date=date(2024, 2, 28),
        end_date=date(2024, 2, 29),
        freq="1min",
    )

    assert counts == {}
    assert progress_events == [{"event": "init_schema"}, {"event": "close"}]
    assert logger.messages == [
        "minute_bar resume scan: requested=1 pending=1 skipped=0 trade_days=2 gap_ranges=1 missing_trade_days=2",
        "minute_bar resume scan found no pending symbols; nothing to do.",
    ]


def test_update_all_parse_args_accepts_plan_date_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("scripts.update_all")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "update_all.py",
            "--date",
            "2024-02-29",
            "--start",
            "2024-02-01",
            "--end",
            "2024-02-29",
            "--ts-codes",
            "000001.SZ,600000.SH",
        ],
    )

    args = module.parse_args()

    assert args.trade_date == date(2024, 2, 29)
    assert args.start_date == date(2024, 2, 1)
    assert args.end_date == date(2024, 2, 29)
    assert args.ts_codes == ["000001.SZ", "600000.SH"]


def test_update_daily_bar_parse_args_supports_precise_backfill_with_date_and_force(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("scripts.update_daily_bar")
    monkeypatch.setattr(
        sys,
        "argv",
        ["update_daily_bar.py", "--date", "2025-01-15", "--force"],
    )

    args = module.parse_args()
    run_kwargs = module.build_run_kwargs(args)

    assert args.trade_date == date(2025, 1, 15)
    assert args.start_date == date(2025, 1, 15)
    assert args.end_date == date(2025, 1, 15)
    assert args.force is True
    assert run_kwargs == {
        "ts_codes": None,
        "start_date": date(2025, 1, 15),
        "end_date": date(2025, 1, 15),
    }


def test_update_daily_bar_parse_args_supports_plan_start_end_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("scripts.update_daily_bar")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "update_daily_bar.py",
            "--start",
            "2025-01-01",
            "--end",
            "2025-01-31",
            "--ts-codes",
            "000001.SZ",
            "--force",
        ],
    )

    args = module.parse_args()
    run_kwargs = module.build_run_kwargs(args)

    assert args.trade_date is None
    assert args.start_date == date(2025, 1, 1)
    assert args.end_date == date(2025, 1, 31)
    assert args.ts_codes == ["000001.SZ"]
    assert args.force is True
    assert run_kwargs == {
        "ts_codes": ["000001.SZ"],
        "start_date": date(2025, 1, 1),
        "end_date": date(2025, 1, 31),
    }
