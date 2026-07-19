"""日线行情更新器。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from .base import BaseUpdater


class DailyBarUpdater(BaseUpdater):
    """Refresh daily bars into market storage."""

    source_capability = 'daily_bar'

    def run(self, ts_codes: Sequence[str] | None, start_date: date, end_date: date) -> dict[str, int]:
        """Fetch and persist daily bars for the requested symbols."""
        return {
            'daily_bar': self._upsert_market(
                'daily_bar',
                self.source.fetch_daily_bar(self._ensure_code_list(ts_codes), start_date, end_date),
            )
        }
