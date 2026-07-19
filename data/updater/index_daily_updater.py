"""指数日线更新器。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from .base import BaseUpdater


class IndexDailyUpdater(BaseUpdater):
    """Refresh index daily bars into market storage."""

    def run(self, index_codes: Sequence[str], start_date: date, end_date: date) -> dict[str, int]:
        """Fetch and persist index daily bars for each requested index."""
        counts: dict[str, int] = {}
        for index_code in index_codes:
            counts[f'index_daily:{index_code}'] = self._upsert_market(
                'index_daily',
                self.source.fetch_index_daily(index_code, start_date, end_date),
            )
        return counts
