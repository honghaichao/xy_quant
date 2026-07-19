"""数据更新调度入口。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from .daily_updater import DailyUpdater
from .finance_updater import FinanceUpdater
from .init_loader import InitLoader


class _RunnableUpdater(Protocol):
    def close(self) -> None: ...


class _InitLoaderLike(_RunnableUpdater, Protocol):
    def run(
        self,
        ts_codes: Sequence[str],
        start_date: date,
        end_date: date,
        index_codes: Sequence[str] | None = None,
        trade_date: date | None = None,
    ) -> dict[str, int]: ...


class _DailyUpdaterLike(_RunnableUpdater, Protocol):
    def run(
        self,
        trade_date: date,
        ts_codes: Sequence[str],
        index_codes: Sequence[str] | None = None,
    ) -> dict[str, int]: ...


class _FinanceUpdaterLike(_RunnableUpdater, Protocol):
    def run(
        self,
        ts_codes: Sequence[str],
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, int]: ...


class UpdateScheduler:
    """Coordinate full-load, daily, and finance refresh jobs."""

    def __init__(
        self,
        init_loader: _InitLoaderLike | None = None,
        daily_updater: _DailyUpdaterLike | None = None,
        finance_updater: _FinanceUpdaterLike | None = None,
    ) -> None:
        self.init_loader = init_loader or InitLoader()
        self.daily_updater = daily_updater or DailyUpdater()
        self.finance_updater = finance_updater or FinanceUpdater()

    def run_full_load(
        self,
        ts_codes: Sequence[str],
        start_date: date,
        end_date: date,
        index_codes: Sequence[str] | None = None,
        trade_date: date | None = None,
    ) -> dict[str, int]:
        """Execute the bootstrap loader."""
        return self.init_loader.run(ts_codes, start_date, end_date, index_codes, trade_date)

    def run_daily(
        self,
        trade_date: date,
        ts_codes: Sequence[str],
        index_codes: Sequence[str] | None = None,
    ) -> dict[str, int]:
        """Execute the daily refresh workflow."""
        return self.daily_updater.run(trade_date, ts_codes, index_codes)

    def run_finance(
        self,
        ts_codes: Sequence[str],
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, int]:
        """Execute the financial refresh workflow."""
        return self.finance_updater.run(ts_codes, start_date, end_date)

    def close(self) -> None:
        """Close resources owned by the child updaters."""
        for updater in (self.init_loader, self.daily_updater, self.finance_updater):
            updater.close()
