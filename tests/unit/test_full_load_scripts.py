"""Unit tests for P0.8 full-load scripts."""

from __future__ import annotations

import importlib
import sys
from argparse import Namespace
from datetime import date

import pytest

SCRIPT_CASES = [
    (
        "scripts.full_load_basic",
        "BasicUpdater",
        {},
        {"stock_basic": 10},
        "Starting full load: basic.",
        "Full load complete: basic.",
    ),
    (
        "scripts.full_load_calendar",
        "CalendarUpdater",
        {"start_date": date(2024, 1, 1), "end_date": date(2024, 1, 31)},
        {"trade_calendar": 20},
        "Starting full load: calendar.",
        "Full load complete: calendar.",
    ),
    (
        "scripts.full_load_daily_bar",
        "DailyBarUpdater",
        {
            "ts_codes": ["000001.SZ", "600000.SH"],
            "start_date": date(2024, 1, 1),
            "end_date": date(2024, 1, 31),
        },
        {"daily_bar": 50},
        "Starting full load: daily_bar.",
        "Full load complete: daily_bar.",
    ),
    (
        "scripts.full_load_finance",
        "FinanceUpdater",
        {
            "ts_codes": ["000001.SZ"],
            "start_date": date(2023, 1, 1),
            "end_date": date(2023, 12, 31),
        },
        {"income": 4, "balancesheet": 4, "cashflow": 4, "fina_indicator": 4, "dividend": 1},
        "Starting full load: finance.",
        "Full load complete: finance.",
    ),
    (
        "scripts.full_load_member",
        "MemberUpdater",
        {
            "concept_codes": ["C01"],
            "industry_codes": ["I01"],
            "index_codes": ["000300.SH"],
            "trade_date": date(2024, 1, 31),
        },
        {"concept_list": 1, "concept_member:C01": 2, "industry_list": 1, "industry_member:I01": 2, "index_weight:000300.SH": 3},
        "Starting full load: member.",
        "Full load complete: member.",
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
def test_full_load_script_invokes_target_updater(
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


def test_full_load_all_initializes_db_and_runs_all_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("scripts.full_load_all")
    logger = DummyLogger()
    executed: list[tuple[str, dict[str, object]]] = []

    monkeypatch.setattr(
        module,
        "parse_args",
        lambda argv=None: Namespace(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            trade_date=date(2024, 1, 31),
            ts_codes=["000001.SZ", "600000.SH"],
            minute_ts_code=None,
            index_codes=["000300.SH"],
            concept_codes=["C01"],
            industry_codes=["I01"],
            minute_freq="5min",
            holdertrade_ts_code=None,
            holdertrade_ann_date=None,
        ),
    )
    monkeypatch.setattr(module, "logger", logger)
    monkeypatch.setattr(module, "init_db_main", lambda argv=None: executed.append(("init_db", {"argv": argv})))

    def fake_run_job(job_name: str, **kwargs: object) -> dict[str, int]:
        executed.append((job_name, dict(kwargs)))
        return {job_name: 1}

    monkeypatch.setattr(
        module,
        "run_subjob",
        fake_run_job,
    )

    result = module.main()

    assert result["basic"] == {"basic": 1}
    assert result["finance"] == {"finance": 1}
    assert executed == [
        ("init_db", {"argv": []}),
        ("basic", {}),
        ("calendar", {"start_date": date(2024, 1, 1), "end_date": date(2024, 1, 31)}),
        (
            "daily_bar",
            {
                "ts_codes": ["000001.SZ", "600000.SH"],
                "start_date": date(2024, 1, 1),
                "end_date": date(2024, 1, 31),
            },
        ),
        (
            "minute_bar",
            {
                "ts_codes": ["000001.SZ", "600000.SH"],
                "start_date": date(2024, 1, 1),
                "end_date": date(2024, 1, 31),
                "freq": "5min",
            },
        ),
        (
            "adj_factor",
            {
                "ts_codes": ["000001.SZ", "600000.SH"],
                "start_date": date(2024, 1, 1),
                "end_date": date(2024, 1, 31),
            },
        ),
        (
            "daily_basic",
            {
                "ts_codes": ["000001.SZ", "600000.SH"],
                "start_date": date(2024, 1, 1),
                "end_date": date(2024, 1, 31),
            },
        ),
        (
            "index_daily",
            {
                "index_codes": ["000300.SH"],
                "start_date": date(2024, 1, 1),
                "end_date": date(2024, 1, 31),
            },
        ),
        ("limit_list", {"trade_date": date(2024, 1, 31)}),
        ("money_flow", {"trade_date": date(2024, 1, 31)}),
        ("top_list", {"trade_date": date(2024, 1, 31)}),
        ("margin", {"trade_date": date(2024, 1, 31)}),
        ("hk_hold", {"trade_date": date(2024, 1, 31)}),
        ("suspend", {"trade_date": date(2024, 1, 31)}),
        (
            "member",
            {
                "concept_codes": ["C01"],
                "industry_codes": ["I01"],
                "index_codes": ["000300.SH"],
                "trade_date": date(2024, 1, 31),
            },
        ),
        ("holdertrade", {"ann_date": date(2024, 1, 31)}),
        (
            "finance",
            {
                "ts_codes": ["000001.SZ", "600000.SH"],
                "start_date": date(2024, 1, 1),
                "end_date": date(2024, 1, 31),
            },
        ),
    ]
    assert logger.messages == [
        "Initializing storage before full load.",
        "Starting orchestrated full load.",
        "Full load orchestrator complete.",
    ]


def test_full_load_all_parse_args_allows_omitting_minute_ts_code(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("scripts.full_load_all")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "full_load_all.py",
            "--start-date",
            "2024-01-01",
            "--end-date",
            "2024-01-31",
            "--trade-date",
            "2024-01-31",
            "--ts-codes",
            "000001.SZ,600000.SH",
            "--minute-freq",
            "1min",
        ],
    )

    args = module.parse_args()

    assert args.ts_codes == ["000001.SZ", "600000.SH"]
    assert args.minute_ts_code is None
    assert args.minute_freq == "1min"


def test_full_load_minute_bar_build_run_kwargs_supports_all_market_namespace() -> None:
    module = importlib.import_module("scripts.full_load_minute_bar")

    kwargs = module.build_run_kwargs(
        Namespace(
            ts_code=None,
            ts_codes=["000001.SZ", "600000.SH"],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            freq="5min",
        )
    )

    assert kwargs == {
        "ts_codes": ["000001.SZ", "600000.SH"],
        "start_date": date(2024, 1, 1),
        "end_date": date(2024, 1, 31),
        "freq": "5min",
    }


def test_full_load_minute_bar_parse_args_defaults_to_1min(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("scripts.full_load_minute_bar")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "full_load_minute_bar.py",
            "--ts-code",
            "000001.SZ",
            "--start-date",
            "2024-01-01",
            "--end-date",
            "2024-01-31",
        ],
    )

    args = module.parse_args()

    assert args.freq == "1min"
