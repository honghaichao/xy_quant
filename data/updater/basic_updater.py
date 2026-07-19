"""股票基础信息更新器。"""

from __future__ import annotations

from .base import BaseUpdater


class BasicUpdater(BaseUpdater):
    """Refresh stock master data into metadata storage."""

    source_capability = 'stock_basic'

    def run(self) -> dict[str, int]:
        """Fetch and persist stock basics."""
        return {'stock_basic': self._upsert_meta('stock_basic', self.source.fetch_stock_basic())}
