"""北向持股更新器。"""

from __future__ import annotations

from datetime import date

from .base import BaseUpdater


class HkHoldUpdater(BaseUpdater):
    """Refresh Hong Kong connect holding data into metadata storage."""

    source_capability = 'hk_hold'

    def run(self, trade_date: date | None = None, ts_code: str | None = None) -> dict[str, int]:
        """Fetch and persist Hong Kong connect holdings."""
        return {'hk_hold': self._upsert_meta('hk_hold', self.source.fetch_hk_hold(trade_date=trade_date, ts_code=ts_code))}
