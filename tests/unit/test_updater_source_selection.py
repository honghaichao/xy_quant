"""Regression tests for updater default data-source routing."""

from __future__ import annotations

from data.source.strategy import SourceSelectionPolicy
from data.updater.adj_factor_updater import AdjFactorUpdater
from data.updater.basic_updater import BasicUpdater
from data.updater.calendar_updater import CalendarUpdater
from data.updater.daily_bar_updater import DailyBarUpdater
from data.updater.daily_basic_updater import DailyBasicUpdater
from data.updater.hk_hold_updater import HkHoldUpdater
from data.updater.index_daily_updater import IndexDailyUpdater
from data.updater.limit_list_updater import LimitListUpdater
from data.updater.minute_bar_updater import MinuteBarUpdater
from data.updater.money_flow_updater import MoneyFlowUpdater
from data.updater.suspend_updater import SuspendUpdater


def test_minute_bar_updater_defaults_to_tushare() -> None:
    updater = MinuteBarUpdater()
    assert updater.source.name == "tushare"


def test_limit_list_updater_defaults_to_tushare() -> None:
    updater = LimitListUpdater()
    assert updater.source.name == "tushare"


def test_money_flow_updater_defaults_to_tushare() -> None:
    updater = MoneyFlowUpdater()
    assert updater.source.name == "tushare"


def test_hk_hold_updater_defaults_to_tushare() -> None:
    updater = HkHoldUpdater()
    assert updater.source.name == "tushare"


def test_daily_bar_updater_defaults_to_tushare() -> None:
    updater = DailyBarUpdater()
    assert updater.source.name == "tushare"


def test_adj_factor_updater_defaults_to_tushare() -> None:
    updater = AdjFactorUpdater()
    assert updater.source.name == "tushare"


def test_daily_basic_updater_defaults_to_tushare() -> None:
    updater = DailyBasicUpdater()
    assert updater.source.name == "tushare"


def test_calendar_updater_defaults_to_tushare() -> None:
    updater = CalendarUpdater()
    assert updater.source.name == "tushare"


def test_basic_updater_defaults_to_tushare() -> None:
    updater = BasicUpdater()
    assert updater.source.name == "tushare"


def test_suspend_updater_defaults_to_tushare() -> None:
    updater = SuspendUpdater()
    assert updater.source.name == "tushare"


def test_index_daily_updater_stays_on_tushare() -> None:
    updater = IndexDailyUpdater()
    assert updater.source.name == "tushare"


def test_base_updater_can_use_explicit_source_selection_policy() -> None:
    class FakeSource:
        name = "akshare"

        def supports(self, capability: str) -> bool:
            return capability == "minute_bar"

    policy = SourceSelectionPolicy(
        factory=lambda name: FakeSource(),
        preferred_sources_by_capability={"minute_bar": ("akshare",)},
        primary_source="tushare",
        fallback_source="akshare",
    )

    updater = MinuteBarUpdater(source_strategy=policy)

    assert updater.source.name == "akshare"
