"""财务数据更新器。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from .base import BaseUpdater


class FinanceUpdater(BaseUpdater):
    """Refresh quarterly statements and dividend data into metadata storage."""

    def run(
        self,
        ts_codes: Sequence[str],
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, int]:
        """Update financial statements for each requested symbol."""
        counts: dict[str, int] = {
            'income': 0,
            'balancesheet': 0,
            'cashflow': 0,
            'fina_indicator': 0,
            'dividend': 0,
        }
        for ts_code in ts_codes:
            counts['income'] += self._upsert_meta(
                'income',
                self.source.fetch_income(ts_code, start_date=start_date, end_date=end_date),
            )
            counts['balancesheet'] += self._upsert_meta(
                'balancesheet',
                self.source.fetch_balancesheet(ts_code, start_date=start_date, end_date=end_date),
            )
            counts['cashflow'] += self._upsert_meta(
                'cashflow',
                self.source.fetch_cashflow(ts_code, start_date=start_date, end_date=end_date),
            )
            counts['fina_indicator'] += self._upsert_meta(
                'fina_indicator',
                self.source.fetch_fina_indicator(ts_code, start_date=start_date, end_date=end_date),
            )
            counts['dividend'] += self._upsert_meta('dividend', self.source.fetch_dividend(ts_code))
        return counts

    def update_financials(
        self,
        ts_codes: Sequence[str],
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, int]:
        """Backward-compatible alias for the finance refresh workflow."""
        return self.run(ts_codes, start_date=start_date, end_date=end_date)
