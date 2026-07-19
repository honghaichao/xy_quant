"""龙虎榜更新器。"""

from __future__ import annotations

from datetime import date

from .base import BaseUpdater


class TopListUpdater(BaseUpdater):
    """Refresh top-list data into metadata storage."""

    def run(self, trade_date: date) -> dict[str, int]:
        """Fetch and persist top-list data for one trade date."""
        return {'top_list': self._upsert_meta('top_list', self.source.fetch_top_list(trade_date))}
