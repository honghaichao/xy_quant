"""Extra coverage tests for script helpers and entrypoints."""

from __future__ import annotations

import argparse
import importlib
import runpy
import sys
from datetime import date
from typing import Any

import pytest

from scripts import full_load_helpers, update_helpers


class DummyLogger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, message: str) -> None:
        self.messages.append(message)


class RaisingUpdater:
    def __init__(self, recorder: list[str]) -> None:
        self.recorder = recorder

    def run(self, **kwargs: object) -> dict[str, int]:
        del kwargs
        self.recorder.append("run")
        raise RuntimeError("boom")

    def close(self) -> None:
        self.recorder.append("close")


@pytest.mark.parametrize("helpers", [full_load_helpers, update_helpers])
def test_script_helpers_parse_and_logger(helpers: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    parser = argparse.ArgumentParser()
    helpers.add_date_range_arguments(parser, required=False) if helpers is update_helpers else helpers.add_date_range_arguments(parser)
    helpers.add_trade_date_argument(parser, required=False)
    helpers.add_ts_codes_argument(parser, required=False)
    helpers.add_index_codes_argument(parser)
    helpers.add_concept_codes_argument(parser)
    helpers.add_industry_codes_argument(parser)

    args = parser.parse_args(
        [
            "--start-date",
            "2024-01-01",
            "--end-date",
            "2024-01-31",
            "--trade-date",
            "2024-01-15",
            "--ts-codes",
            "000001.SZ, 600000.SH",
            "--index-codes",
            "000300.SH",
            "--concept-codes",
            "C01",
            "--industry-codes",
            "I01",
        ]
    )

    assert helpers.parse_date("2024-01-01") == date(2024, 1, 1)
    assert helpers.parse_csv_list(None) == []
    assert helpers.parse_csv_list(" a, ,b ") == ["a", "b"]
    assert args.start_date == date(2024, 1, 1)
    assert args.end_date == date(2024, 1, 31)
    assert args.trade_date == date(2024, 1, 15)
    assert args.ts_codes == ["000001.SZ", "600000.SH"]
    assert args.index_codes == ["000300.SH"]
    assert args.concept_codes == ["C01"]
    assert args.industry_codes == ["I01"]

    monkeypatch.setattr(helpers, "get_logger", lambda name: {"logger_name": name})
    prefix = "full_load_" if helpers is full_load_helpers else "update_"
    assert helpers.build_logger("daily") == {"logger_name": prefix + "daily"}


@pytest.mark.parametrize(
    ("helpers", "start_message", "end_message"),
    [
        (full_load_helpers, "Starting full load: daily.", "Full load complete: daily."),
        (update_helpers, "Starting incremental update: daily.", "Incremental update complete: daily."),
    ],
)
def test_run_updater_job_closes_on_exception(
    helpers: Any,
    start_message: str,
    end_message: str,
) -> None:
    logger = DummyLogger()
    recorder: list[str] = []

    class Factory:
        def __call__(self) -> RaisingUpdater:
            return RaisingUpdater(recorder)

    with pytest.raises(RuntimeError, match="boom"):
        helpers.run_updater_job("daily", Factory(), {}, logger)

    assert recorder == ["run", "close"]
    assert logger.messages == [start_message]
    assert end_message not in logger.messages


FULL_LOAD_PARSE_CASES = [
    ("scripts.full_load_adj_factor", ["--ts-codes", "000001.SZ", "--start-date", "2024-01-01", "--end-date", "2024-01-31"], {"ts_codes": ["000001.SZ"], "start_date": date(2024, 1, 1), "end_date": date(2024, 1, 31)}),
    ("scripts.full_load_daily_basic", ["--ts-codes", "000001.SZ", "--start-date", "2024-01-01", "--end-date", "2024-01-31"], {"ts_codes": ["000001.SZ"], "start_date": date(2024, 1, 1), "end_date": date(2024, 1, 31)}),
    ("scripts.full_load_member", ["--concept-codes", "C01", "--industry-codes", "I01", "--index-codes", "000300.SH"], {"concept_codes": ["C01"], "industry_codes": ["I01"], "index_codes": ["000300.SH"], "trade_date": None}),
    ("scripts.full_load_holdertrade", ["--ann-date", "2024-01-31", "--ts-code", "000001.SZ"], {"ann_date": date(2024, 1, 31), "ts_code": "000001.SZ"}),
    ("scripts.full_load_minute_bar", ["--ts-code", "000001.SZ", "--start-date", "2024-01-01", "--end-date", "2024-01-31", "--freq", "5min"], {"ts_code": "000001.SZ", "start_date": date(2024, 1, 1), "end_date": date(2024, 1, 31), "freq": "5min"}),
    ("scripts.full_load_hk_hold", ["--trade-date", "2024-01-31"], {"trade_date": date(2024, 1, 31), "ts_code": None}),
    ("scripts.full_load_index_daily", ["--index-codes", "000300.SH", "--start-date", "2024-01-01", "--end-date", "2024-01-31"], {"index_codes": ["000300.SH"], "start_date": date(2024, 1, 1), "end_date": date(2024, 1, 31)}),
    ("scripts.full_load_limit_list", ["--trade-date", "2024-01-31", "--kind", "D"], {"trade_date": date(2024, 1, 31), "kind": "D"}),
    ("scripts.full_load_margin", ["--trade-date", "2024-01-31"], {"trade_date": date(2024, 1, 31)}),
    ("scripts.full_load_money_flow", ["--trade-date", "2024-01-31"], {"trade_date": date(2024, 1, 31)}),
    ("scripts.full_load_suspend", ["--trade-date", "2024-01-31", "--ts-code", "000001.SZ"], {"trade_date": date(2024, 1, 31), "ts_code": "000001.SZ"}),
    ("scripts.full_load_top_list", ["--trade-date", "2024-01-31"], {"trade_date": date(2024, 1, 31)}),
]


UPDATE_PARSE_CASES = [
    ("scripts.update_adj_factor", ["--ts-codes", "000001.SZ", "--start-date", "2024-02-01", "--end-date", "2024-02-29"], {"ts_codes": ["000001.SZ"], "start_date": date(2024, 2, 1), "end_date": date(2024, 2, 29)}),
    ("scripts.update_daily", ["--trade-date", "2024-02-29", "--ts-codes", "000001.SZ", "--index-codes", "000300.SH"], {"trade_date": date(2024, 2, 29), "ts_codes": ["000001.SZ"], "index_codes": ["000300.SH"]}),
    ("scripts.update_daily_basic", ["--ts-codes", "000001.SZ", "--trade-date", "2024-02-29", "--start-date", "2024-02-01", "--end-date", "2024-02-29"], {"ts_codes": ["000001.SZ"], "trade_date": date(2024, 2, 29), "start_date": date(2024, 2, 1), "end_date": date(2024, 2, 29)}),
    ("scripts.update_holdertrade", ["--ann-date", "2024-02-29", "--ts-code", "000001.SZ"], {"ann_date": date(2024, 2, 29), "ts_code": "000001.SZ"}),
    ("scripts.update_hk_hold", ["--trade-date", "2024-02-29"], {"trade_date": date(2024, 2, 29)}),
    ("scripts.update_index_daily", ["--index-codes", "000300.SH", "--start-date", "2024-02-01", "--end-date", "2024-02-29"], {"index_codes": ["000300.SH"], "start_date": date(2024, 2, 1), "end_date": date(2024, 2, 29)}),
    ("scripts.update_limit_list", ["--trade-date", "2024-02-29", "--kind", "D"], {"trade_date": date(2024, 2, 29), "kind": "D"}),
    ("scripts.update_margin", ["--trade-date", "2024-02-29"], {"trade_date": date(2024, 2, 29)}),
    ("scripts.update_member", ["--concept-codes", "C01", "--industry-codes", "I01", "--index-codes", "000300.SH"], {"concept_codes": ["C01"], "industry_codes": ["I01"], "index_codes": ["000300.SH"], "trade_date": None}),
    ("scripts.update_minute_bar", ["--ts-code", "000001.SZ", "--start-date", "2024-02-01", "--end-date", "2024-02-29", "--freq", "5min"], {"ts_code": "000001.SZ", "start_date": date(2024, 2, 1), "end_date": date(2024, 2, 29), "freq": "5min"}),
    ("scripts.update_money_flow", ["--trade-date", "2024-02-29"], {"trade_date": date(2024, 2, 29)}),
    ("scripts.update_top_list", ["--trade-date", "2024-02-29"], {"trade_date": date(2024, 2, 29)}),
]


@pytest.mark.parametrize(("module_name", "argv", "expected"), FULL_LOAD_PARSE_CASES + UPDATE_PARSE_CASES)
def test_script_parse_args_and_build_run_kwargs(
    module_name: str,
    argv: list[str],
    expected: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module(module_name)
    monkeypatch.setattr(sys, "argv", [module_name.rsplit(".", 1)[-1] + ".py", *argv])

    args = module.parse_args()
    run_kwargs = module.build_run_kwargs(args)

    assert run_kwargs == expected


RUN_JOB_CASES = [
    ("scripts.full_load_adj_factor", "AdjFactorUpdater", {"ts_codes": ["000001.SZ"]}),
    ("scripts.full_load_daily_basic", "DailyBasicUpdater", {"ts_codes": ["000001.SZ"]}),
    ("scripts.full_load_holdertrade", "HoldertradeUpdater", {"ann_date": date(2024, 1, 31)}),
    ("scripts.full_load_hk_hold", "HkHoldUpdater", {"trade_date": date(2024, 1, 31)}),
    ("scripts.full_load_index_daily", "IndexDailyUpdater", {"index_codes": ["000300.SH"]}),
    ("scripts.full_load_limit_list", "LimitListUpdater", {"trade_date": date(2024, 1, 31), "kind": "U"}),
    ("scripts.full_load_margin", "MarginUpdater", {"trade_date": date(2024, 1, 31)}),
    ("scripts.full_load_member", "MemberUpdater", {"trade_date": None}),
    ("scripts.full_load_money_flow", "MoneyFlowUpdater", {"trade_date": date(2024, 1, 31)}),
    ("scripts.full_load_suspend", "SuspendUpdater", {"trade_date": date(2024, 1, 31)}),
    ("scripts.full_load_top_list", "TopListUpdater", {"trade_date": date(2024, 1, 31)}),
    ("scripts.update_adj_factor", "AdjFactorUpdater", {"ts_codes": ["000001.SZ"]}),
    ("scripts.update_daily", "DailyUpdater", {"trade_date": date(2024, 2, 29)}),
    ("scripts.update_daily_basic", "DailyBasicUpdater", {"trade_date": date(2024, 2, 29)}),
    ("scripts.update_holdertrade", "HoldertradeUpdater", {"ann_date": date(2024, 2, 29)}),
    ("scripts.update_hk_hold", "HkHoldUpdater", {"trade_date": date(2024, 2, 29)}),
    ("scripts.update_index_daily", "IndexDailyUpdater", {"index_codes": ["000300.SH"]}),
    ("scripts.update_limit_list", "LimitListUpdater", {"trade_date": date(2024, 2, 29), "kind": "U"}),
    ("scripts.update_margin", "MarginUpdater", {"trade_date": date(2024, 2, 29)}),
    ("scripts.update_member", "MemberUpdater", {"trade_date": None}),
    ("scripts.update_minute_bar", "MinuteBarUpdater", {"ts_code": "000001.SZ", "freq": "1min"}),
    ("scripts.update_money_flow", "MoneyFlowUpdater", {"trade_date": date(2024, 2, 29)}),
    ("scripts.update_top_list", "TopListUpdater", {"trade_date": date(2024, 2, 29)}),
]


@pytest.mark.parametrize(("module_name", "updater_attr", "kwargs"), RUN_JOB_CASES)
def test_script_run_job_entrypoints(
    module_name: str,
    updater_attr: str,
    kwargs: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module(module_name)
    logger = DummyLogger()
    called: list[tuple[str, Any, dict[str, object], DummyLogger]] = []
    expected_job_name = module_name.rsplit(".", 1)[-1].removeprefix("full_load_").removeprefix("update_")

    def fake_run_updater_job(job_name: str, updater_cls: Any, run_kwargs: dict[str, object], run_logger: DummyLogger) -> dict[str, int]:
        called.append((job_name, updater_cls, run_kwargs, run_logger))
        return {job_name: 1}

    monkeypatch.setattr(module, "logger", logger)
    monkeypatch.setattr(module, "run_updater_job", fake_run_updater_job)

    result = module.run_job(**kwargs)

    assert result == {expected_job_name: 1}
    assert called == [
        (
            expected_job_name,
            getattr(module, updater_attr),
            kwargs,
            logger,
        )
    ]


SCRIPT_MAIN_CASES = [
    ("scripts.full_load_adj_factor", ["--ts-codes", "000001.SZ", "--start-date", "2024-01-01", "--end-date", "2024-01-31"], "scripts.full_load_helpers", "adj_factor"),
    ("scripts.full_load_daily_basic", ["--ts-codes", "000001.SZ", "--start-date", "2024-01-01", "--end-date", "2024-01-31"], "scripts.full_load_helpers", "daily_basic"),
    ("scripts.full_load_holdertrade", ["--ann-date", "2024-01-31", "--ts-code", "000001.SZ"], "scripts.full_load_helpers", "holdertrade"),
    ("scripts.full_load_hk_hold", ["--trade-date", "2024-01-31"], "scripts.full_load_helpers", "hk_hold"),
    ("scripts.full_load_index_daily", ["--index-codes", "000300.SH", "--start-date", "2024-01-01", "--end-date", "2024-01-31"], "scripts.full_load_helpers", "index_daily"),
    ("scripts.full_load_limit_list", ["--trade-date", "2024-01-31"], "scripts.full_load_helpers", "limit_list"),
    ("scripts.full_load_margin", ["--trade-date", "2024-01-31"], "scripts.full_load_helpers", "margin"),
    ("scripts.full_load_member", ["--index-codes", "000300.SH"], "scripts.full_load_helpers", "member"),
    ("scripts.full_load_money_flow", ["--trade-date", "2024-01-31"], "scripts.full_load_helpers", "money_flow"),
    ("scripts.full_load_suspend", ["--trade-date", "2024-01-31"], "scripts.full_load_helpers", "suspend"),
    ("scripts.full_load_top_list", ["--trade-date", "2024-01-31"], "scripts.full_load_helpers", "top_list"),
    ("scripts.update_adj_factor", ["--ts-codes", "000001.SZ", "--start-date", "2024-02-01", "--end-date", "2024-02-29"], "scripts.update_helpers", "adj_factor"),
    ("scripts.update_daily", ["--trade-date", "2024-02-29", "--ts-codes", "000001.SZ"], "scripts.update_helpers", "daily"),
    ("scripts.update_daily_basic", ["--ts-codes", "000001.SZ", "--start-date", "2024-02-01", "--end-date", "2024-02-29"], "scripts.update_helpers", "daily_basic"),
    ("scripts.update_hk_hold", ["--trade-date", "2024-02-29"], "scripts.update_helpers", "hk_hold"),
    ("scripts.update_holdertrade", ["--ann-date", "2024-02-29", "--ts-code", "000001.SZ"], "scripts.update_helpers", "holdertrade"),
    ("scripts.update_index_daily", ["--index-codes", "000300.SH", "--start-date", "2024-02-01", "--end-date", "2024-02-29"], "scripts.update_helpers", "index_daily"),
    ("scripts.update_limit_list", ["--trade-date", "2024-02-29"], "scripts.update_helpers", "limit_list"),
    ("scripts.update_margin", ["--trade-date", "2024-02-29"], "scripts.update_helpers", "margin"),
    ("scripts.update_member", ["--index-codes", "000300.SH"], "scripts.update_helpers", "member"),
    ("scripts.update_minute_bar", ["--ts-code", "000001.SZ", "--start-date", "2024-02-01", "--end-date", "2024-02-29"], "scripts.update_helpers", "minute_bar"),
    ("scripts.update_money_flow", ["--trade-date", "2024-02-29"], "scripts.update_helpers", "money_flow"),
    ("scripts.update_top_list", ["--trade-date", "2024-02-29"], "scripts.update_helpers", "top_list"),
]


def test_full_load___main___entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    orchestrator = importlib.import_module("scripts.full_load_all")
    calls: list[str] = []

    def fake_main() -> dict[str, int]:
        calls.append("full_load_all")
        return {"ok": 1}

    monkeypatch.setattr(orchestrator, "main", fake_main)
    monkeypatch.setattr(sys, "argv", ["full_load.py"])
    sys.modules.pop("scripts.full_load", None)
    runpy.run_module("scripts.full_load", run_name="__main__")
    assert calls == ["full_load_all"]


@pytest.mark.parametrize(("module_name", "argv", "helper_module_name", "job_name"), SCRIPT_MAIN_CASES)
def test_script___main___entrypoints(
    module_name: str,
    argv: list[str],
    helper_module_name: str,
    job_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper_module = importlib.import_module(helper_module_name)
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_run_updater_job(name: str, updater_cls: Any, run_kwargs: dict[str, object], logger: Any) -> dict[str, int]:
        del updater_cls, logger
        calls.append((name, run_kwargs))
        return {name: 1}

    monkeypatch.setattr(helper_module, "run_updater_job", fake_run_updater_job)
    monkeypatch.setattr(sys, "argv", [module_name.rsplit(".", 1)[-1] + ".py", *argv])
    sys.modules.pop(module_name, None)
    runpy.run_module(module_name, run_name="__main__")

    assert len(calls) == 1
    assert calls[0][0] == job_name


def test_full_load_and_update_all_run_job_and_parse_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    full_module = importlib.import_module("scripts.full_load_all")
    update_module = importlib.import_module("scripts.update_all")

    monkeypatch.setattr(
        full_module,
        "run_subjob",
        lambda job_name, **kwargs: {job_name: len(kwargs)},
    )
    monkeypatch.setattr(full_module, "init_db_main", lambda argv=None: None)
    monkeypatch.setattr(full_module, "logger", DummyLogger())
    monkeypatch.setattr(update_module, "run_subjob", lambda job_name, **kwargs: {job_name: len(kwargs)})
    monkeypatch.setattr(update_module, "logger", DummyLogger())

    full_result = full_module.run_job(
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
        trade_date=date(2024, 1, 31),
        ts_codes=["000001.SZ"],
        minute_ts_code="000001.SZ",
        index_codes=["000300.SH"],
        concept_codes=["C01"],
        industry_codes=["I01"],
        holdertrade_ts_code="000001.SZ",
        holdertrade_ann_date=date(2024, 1, 31),
    )
    update_result = update_module.run_job(
        trade_date=date(2024, 2, 29),
        start_date=date(2024, 2, 1),
        end_date=date(2024, 2, 29),
        ts_codes=["000001.SZ"],
        index_codes=["000300.SH"],
        concept_codes=["C01"],
        industry_codes=["I01"],
    )

    assert full_result["holdertrade"] == {"holdertrade": 2}
    assert update_result["daily"] == {"daily": 3}
    assert update_result["hk_hold"] == {"hk_hold": 1}

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
            "000001.SZ",
            "--minute-ts-code",
            "000001.SZ",
        ],
    )
    parsed = full_module.parse_args()
    assert parsed.minute_ts_code == "000001.SZ"
