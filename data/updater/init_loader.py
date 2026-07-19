"""全量初始化加载器。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from .adj_factor_updater import AdjFactorUpdater
from .base import BaseUpdater
from .basic_updater import BasicUpdater
from .calendar_updater import CalendarUpdater
from .daily_bar_updater import DailyBarUpdater
from .daily_basic_updater import DailyBasicUpdater
from .index_daily_updater import IndexDailyUpdater
from .limit_list_updater import LimitListUpdater


class InitLoader(BaseUpdater):
    """Bootstrap historical and reference datasets."""

    def _spawn(self, updater_cls: type[BaseUpdater]) -> BaseUpdater:
        """Create a child updater sharing the same source and stores."""
        return updater_cls(source=self.source, market_store=self.market_store, meta_store=self.meta_store)

    def load_reference_data(self, start_date: date, end_date: date) -> dict[str, int]:
        """Load reference tables such as stock basics and the trading calendar."""
        self.market_store.init_schema()
        self.meta_store.init_schema()
        counts: dict[str, int] = {}
        self._safe_extend(counts, self._spawn(BasicUpdater).run())
        self._safe_extend(counts, self._spawn(CalendarUpdater).run(start_date, end_date))
        return counts

    def load_market_history(
        self,
        ts_codes: Sequence[str],
        start_date: date,
        end_date: date,
        index_codes: Sequence[str] | None = None,
        trade_date: date | None = None,
    ) -> dict[str, int]:
        """Load historical market tables for the requested securities."""
        counts: dict[str, int] = {}
        self._safe_extend(counts, self._spawn(DailyBarUpdater).run(ts_codes, start_date, end_date))
        self._safe_extend(
            counts,
            self._spawn(DailyBasicUpdater).run(ts_codes, start_date=start_date, end_date=end_date),
        )
        self._safe_extend(counts, self._spawn(AdjFactorUpdater).run(ts_codes, start_date, end_date))
        self._safe_extend(counts, self._spawn(IndexDailyUpdater).run(index_codes or [], start_date, end_date))
        if trade_date is not None:
            self._safe_extend(counts, self._spawn(LimitListUpdater).run(trade_date, kind='U'))
        return counts

    def run(
        self,
        ts_codes: Sequence[str],
        start_date: date,
        end_date: date,
        index_codes: Sequence[str] | None = None,
        trade_date: date | None = None,
    ) -> dict[str, int]:
        """Run a bootstrap load and return the inserted row counts."""
        counts = self.load_reference_data(start_date, end_date)
        self._safe_extend(counts, self.load_market_history(ts_codes, start_date, end_date, index_codes, trade_date))
        return counts
