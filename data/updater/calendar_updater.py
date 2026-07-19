"""交易日历更新器。"""

from __future__ import annotations

from datetime import date

from .base import BaseUpdater


class CalendarUpdater(BaseUpdater):
    """Refresh the trading calendar into metadata storage."""

    source_capability = 'trade_calendar'

    def run(self, start_date: date, end_date: date) -> dict[str, int]:
        """Fetch and persist the trading calendar for the requested range."""
        return {
            'trade_calendar': self._upsert_meta(
                'trade_calendar',
                self.source.fetch_trade_calendar(start_date, end_date),
            )
        }
