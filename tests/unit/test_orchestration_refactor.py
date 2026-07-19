"""Regression tests for source strategy, orchestrator, and foundation init refactors."""

from __future__ import annotations

import importlib
from argparse import Namespace
from datetime import date

import pytest

from data.source.strategy import SourceSelectionPolicy


class DummyLogger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, message: str) -> None:
        self.messages.append(message)


class FakeSource:
    def __init__(self, name: str, capabilities: set[str]) -> None:
        self.name = name
        self._capabilities = capabilities

    def supports(self, capability: str) -> bool:
        return capability in self._capabilities


class FakeStore:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def init_schema(self) -> None:
        self.calls.append("init_schema")

    def close(self) -> None:
        self.calls.append("close")


class DummyStrategyUpdater:
    source_capability = "minute_bar"

    def __init__(self, strategy: SourceSelectionPolicy) -> None:
        self.source = strategy.resolve(self.source_capability)


def test_source_selection_policy_respects_capability_preference_before_settings() -> None:
    sources = {
        "tushare": FakeSource("tushare", {"minute_bar", "daily_bar"}),
        "akshare": FakeSource("akshare", {"daily_bar"}),
    }
    policy = SourceSelectionPolicy(
        factory=sources.__getitem__,
        preferred_sources_by_capability={"minute_bar": ("tushare", "akshare")},
        primary_source="akshare",
        fallback_source="tushare",
    )

    updater = DummyStrategyUpdater(policy)

    assert updater.source.name == "tushare"


def test_source_selection_policy_falls_back_when_preferred_source_lacks_capability() -> None:
    sources = {
        "tushare": FakeSource("tushare", {"daily_bar"}),
        "akshare": FakeSource("akshare", {"minute_bar", "daily_bar"}),
    }
    policy = SourceSelectionPolicy(
        factory=sources.__getitem__,
        preferred_sources_by_capability={"minute_bar": ("tushare", "akshare")},
        primary_source="tushare",
        fallback_source="akshare",
    )

    assert policy.resolve("minute_bar").name == "akshare"


def test_full_load_all_uses_shared_job_specs(monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setattr(module, "run_defined_jobs", lambda *args, **kwargs: {
        "basic": {"basic": 1},
        "calendar": {"calendar": 1},
    })

    result = module.main()

    assert result == {"basic": {"basic": 1}, "calendar": {"calendar": 1}}
    assert executed == [("init_db", {"argv": []})]
    assert logger.messages == [
        "Initializing storage before full load.",
        "Starting orchestrated full load.",
        "Full load orchestrator complete.",
    ]


def test_init_foundations_initializes_schema_then_runs_foundation_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("scripts.init_foundations")
    logger = DummyLogger()
    executed: list[tuple[str, dict[str, object]]] = []

    monkeypatch.setattr(
        module,
        "parse_args",
        lambda argv=None: Namespace(start_date=date(2024, 1, 1), end_date=date(2024, 1, 31)),
    )
    monkeypatch.setattr(module, "logger", logger)
    monkeypatch.setattr(module, "init_db_main", lambda argv=None: executed.append(("init_db", {"argv": argv})))

    def fake_run_defined_jobs(*, args: Namespace, jobs: tuple[object, ...], script_prefix: str) -> dict[str, dict[str, int]]:
        executed.append((script_prefix, {"job_count": len(jobs), "start_date": args.start_date, "end_date": args.end_date}))
        return {"basic": {"stock_basic": 3}, "calendar": {"trade_calendar": 20}}

    monkeypatch.setattr(module, "run_defined_jobs", fake_run_defined_jobs)

    result = module.main()

    assert result == {"basic": {"stock_basic": 3}, "calendar": {"trade_calendar": 20}}
    assert executed == [
        ("init_db", {"argv": []}),
        ("full_load", {"job_count": 2, "start_date": date(2024, 1, 1), "end_date": date(2024, 1, 31)}),
    ]
    assert logger.messages == [
        "Initializing storage before foundation bootstrap.",
        "Starting foundation bootstrap.",
        "Foundation bootstrap complete.",
    ]


def test_update_all_accepts_date_alias_and_fills_default_ts_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("scripts.update_all")
    logger = DummyLogger()
    captured: dict[str, object] = {}

    class FakeFrame:
        columns = ["ts_code"]

        def __getitem__(self, key: str) -> object:
            assert key == "ts_code"

            class _Series:
                def dropna(self) -> object:
                    class _Dropped:
                        def tolist(self) -> list[str]:
                            return ["000001.SZ", "600000.SH"]

                    return _Dropped()

            return _Series()

    class FakeSource:
        def fetch_stock_basic(self) -> FakeFrame:
            return FakeFrame()

    monkeypatch.setattr(module, "logger", logger)
    monkeypatch.setattr(module, "get_data_source", lambda source_name: FakeSource())
    monkeypatch.setattr(
        module,
        "run_defined_jobs",
        lambda args: captured.update({"start": args.start_date, "end": args.end_date, "ts_codes": args.ts_codes})
        or {"ok": {"rows": 1}},
    )

    result = module.main(["--date", "2024-02-29"])

    assert result == {"ok": {"rows": 1}}
    assert captured == {
        "start": date(2024, 2, 29),
        "end": date(2024, 2, 29),
        "ts_codes": ["000001.SZ", "600000.SH"],
    }
    assert logger.messages == [
        "Starting orchestrated incremental update.",
        "Incremental update orchestrator complete.",
    ]


def test_update_all_run_job_normalizes_scheduler_string_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("scripts.update_all")
    logger = DummyLogger()
    captured: dict[str, object] = {}

    monkeypatch.setattr(module, "logger", logger)
    monkeypatch.setattr(
        module,
        "run_defined_jobs",
        lambda args: captured.update(
            {
                "trade_date": args.trade_date,
                "start_date": args.start_date,
                "end_date": args.end_date,
                "ts_codes": args.ts_codes,
                "index_codes": args.index_codes,
                "concept_codes": args.concept_codes,
                "industry_codes": args.industry_codes,
            }
        )
        or {"ok": {"rows": 1}},
    )

    result = module.run_job(
        trade_date="2024-02-29",
        start_date="2024-02-01",
        end_date="2024-02-29",
        ts_codes="000001.SZ,600000.SH",
        index_codes="000300.SH",
        concept_codes="C01,C02",
        industry_codes=("I01", "I02"),
    )

    assert result == {"ok": {"rows": 1}}
    assert captured == {
        "trade_date": date(2024, 2, 29),
        "start_date": date(2024, 2, 1),
        "end_date": date(2024, 2, 29),
        "ts_codes": ["000001.SZ", "600000.SH"],
        "index_codes": ["000300.SH"],
        "concept_codes": ["C01", "C02"],
        "industry_codes": ["I01", "I02"],
    }
    assert logger.messages == [
        "Starting orchestrated incremental update.",
        "Incremental update orchestrator complete.",
    ]


def test_full_load_all_run_job_normalizes_scheduler_string_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("scripts.full_load_all")
    logger = DummyLogger()
    executed: list[tuple[str, object]] = []

    monkeypatch.setattr(module, "logger", logger)
    monkeypatch.setattr(module, "init_db_main", lambda argv=None: executed.append(("init_db", argv)))
    def fake_run_defined_jobs(args: Namespace) -> dict[str, dict[str, int]]:
        executed.append(
            (
                "run_defined_jobs",
                {
                    "trade_date": args.trade_date,
                    "start_date": args.start_date,
                    "end_date": args.end_date,
                    "ts_codes": args.ts_codes,
                    "index_codes": args.index_codes,
                    "concept_codes": args.concept_codes,
                    "industry_codes": args.industry_codes,
                    "holdertrade_ann_date": args.holdertrade_ann_date,
                },
            )
        )
        return {"ok": {"rows": 1}}

    monkeypatch.setattr(module, "run_defined_jobs", fake_run_defined_jobs)

    result = module.run_job(
        trade_date="2024-02-29",
        start_date="2024-02-01",
        end_date="2024-02-29",
        ts_codes="000001.SZ,600000.SH",
        minute_ts_code="000001.SZ",
        index_codes="000300.SH",
        concept_codes=("C01",),
        industry_codes="I01,I02",
        minute_freq="1min",
        holdertrade_ann_date="2024-02-29",
    )

    assert result == {"ok": {"rows": 1}}
    assert executed == [
        ("init_db", []),
        (
            "run_defined_jobs",
            {
                "trade_date": date(2024, 2, 29),
                "start_date": date(2024, 2, 1),
                "end_date": date(2024, 2, 29),
                "ts_codes": ["000001.SZ", "600000.SH"],
                "index_codes": ["000300.SH"],
                "concept_codes": ["C01"],
                "industry_codes": ["I01", "I02"],
                "holdertrade_ann_date": date(2024, 2, 29),
            },
        ),
    ]
    assert logger.messages == [
        "Initializing storage before full load.",
        "Starting orchestrated full load.",
        "Full load orchestrator complete.",
    ]
