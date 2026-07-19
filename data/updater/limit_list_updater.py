"""涨跌停池更新器。"""

from __future__ import annotations

from datetime import date

from .base import BaseUpdater


class LimitListUpdater(BaseUpdater):
    """Refresh limit-up or limit-down pools into market storage."""

    source_capability = 'limit_pool'

    def run(self, trade_date: date, kind: str = 'U') -> dict[str, int]:
        """Fetch and persist a limit pool snapshot for one trade date."""
        return {
            'limit_list': self._upsert_market(
                'limit_list',
                self.source.fetch_limit_pool(trade_date, kind=kind),
            )
        }
