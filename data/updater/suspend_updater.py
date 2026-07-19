"""停复牌更新器。"""

from __future__ import annotations

from datetime import date

from .base import BaseUpdater


class SuspendUpdater(BaseUpdater):
    """Refresh suspension data into metadata storage."""

    source_capability = 'stock_suspend'

    def run(self, trade_date: date | None = None, ts_code: str | None = None) -> dict[str, int]:
        """Fetch and persist suspension records."""
        return {
            'stock_suspend': self._upsert_meta(
                'stock_suspend',
                self.source.fetch_stock_suspend(trade_date=trade_date, ts_code=ts_code),
            )
        }
