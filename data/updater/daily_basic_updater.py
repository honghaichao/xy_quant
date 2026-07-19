"""每日指标更新器。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from .base import BaseUpdater


class DailyBasicUpdater(BaseUpdater):
    """Refresh daily-basic metrics into market storage."""

    source_capability = 'daily_basic'

    def run(
        self,
        ts_codes: Sequence[str],
        trade_date: date | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, int]:
        """Fetch and persist daily-basic metrics for the requested symbols."""
        return {
            'daily_basic': self._upsert_market(
                'daily_basic',
                self.source.fetch_daily_basic(
                    self._ensure_code_list(ts_codes),
                    trade_date=trade_date,
                    start_date=start_date,
                    end_date=end_date,
                ),
            )
        }
