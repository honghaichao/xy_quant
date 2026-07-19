"""每日增量更新器。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from .adj_factor_updater import AdjFactorUpdater
from .base import BaseUpdater
from .daily_bar_updater import DailyBarUpdater
from .daily_basic_updater import DailyBasicUpdater
from .hk_hold_updater import HkHoldUpdater
from .index_daily_updater import IndexDailyUpdater
from .limit_list_updater import LimitListUpdater
from .margin_updater import MarginUpdater
from .money_flow_updater import MoneyFlowUpdater
from .suspend_updater import SuspendUpdater
from .top_list_updater import TopListUpdater


class DailyUpdater(BaseUpdater):
    """Run the daily market refresh pipeline."""

    @staticmethod
    def _chunk_codes(ts_codes: Sequence[str], chunk_size: int = 1000) -> list[list[str]]:
        codes = list(ts_codes)
        if not codes:
            return [[]]
        return [codes[index : index + chunk_size] for index in range(0, len(codes), chunk_size)]

    def _spawn(self, updater_cls: type[BaseUpdater]) -> BaseUpdater:
        """Create a child updater sharing stores while honoring capability-specific sources."""
        if updater_cls.source_capability is None:
            return updater_cls(source=self.source, market_store=self.market_store, meta_store=self.meta_store)
        return updater_cls(market_store=self.market_store, meta_store=self.meta_store)

    def run(
        self,
        trade_date: date,
        ts_codes: Sequence[str],
        index_codes: Sequence[str] | None = None,
    ) -> dict[str, int]:
        """Refresh all day-specific market and metadata tables."""
        counts: dict[str, int] = {}
        for code_chunk in self._chunk_codes(ts_codes):
            self._safe_extend(counts, self._spawn(DailyBarUpdater).run(code_chunk, trade_date, trade_date))
            self._safe_extend(counts, self._spawn(DailyBasicUpdater).run(code_chunk, trade_date=trade_date))
            self._safe_extend(counts, self._spawn(AdjFactorUpdater).run(code_chunk, trade_date, trade_date))
        self._safe_extend(counts, self._spawn(IndexDailyUpdater).run(index_codes or [], trade_date, trade_date))
        self._safe_extend(counts, self._spawn(LimitListUpdater).run(trade_date, kind='U'))
        self._safe_extend(counts, self._spawn(SuspendUpdater).run(trade_date=trade_date))
        self._safe_extend(counts, self._spawn(TopListUpdater).run(trade_date))
        self._safe_extend(counts, self._spawn(MarginUpdater).run(trade_date))
        self._safe_extend(counts, self._spawn(HkHoldUpdater).run(trade_date=trade_date))
        self._safe_extend(counts, self._spawn(MoneyFlowUpdater).run(trade_date))
        return counts

    def update_daily_data(
        self,
        trade_date: date,
        ts_codes: Sequence[str],
        index_codes: Sequence[str] | None = None,
    ) -> dict[str, int]:
        """Backward-compatible alias for the daily refresh workflow."""
        return self.run(trade_date, ts_codes, index_codes)
