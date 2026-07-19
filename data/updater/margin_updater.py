"""融资融券更新器。"""

from __future__ import annotations

from datetime import date

from .base import BaseUpdater


class MarginUpdater(BaseUpdater):
    """Refresh margin-detail data into metadata storage."""

    def run(self, trade_date: date) -> dict[str, int]:
        """Fetch and persist margin-detail data for one trade date."""
        return {'margin_detail': self._upsert_meta('margin_detail', self.source.fetch_margin_detail(trade_date))}
