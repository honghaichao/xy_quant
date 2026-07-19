"""复权因子更新器。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from .base import BaseUpdater


class AdjFactorUpdater(BaseUpdater):
    """Refresh adjustment factors into market storage."""

    source_capability = 'adj_factor'

    def run(self, ts_codes: Sequence[str], start_date: date, end_date: date) -> dict[str, int]:
        """Fetch and persist adjustment factors for the requested symbols."""
        return {
            'adj_factor': self._upsert_market(
                'adj_factor',
                self.source.fetch_adj_factor(self._ensure_code_list(ts_codes), start_date, end_date),
            )
        }
