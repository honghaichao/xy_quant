"""股东增减持更新器。"""

from __future__ import annotations

from datetime import date

from .base import BaseUpdater


class HoldertradeUpdater(BaseUpdater):
    """Refresh shareholder increase/decrease records into metadata storage."""

    def run(self, ts_code: str | None = None, ann_date: date | None = None) -> dict[str, int]:
        """Fetch and persist shareholder trade records."""
        return {
            'stk_holdertrade': self._upsert_meta(
                'stk_holdertrade',
                self.source.fetch_stk_holdertrade(ts_code=ts_code, ann_date=ann_date),
            )
        }
