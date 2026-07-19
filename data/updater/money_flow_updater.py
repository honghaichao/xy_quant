"""资金流更新器。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from utils.exception import PartialUpdateError
from utils.logger import get_logger

from .base import BaseUpdater

logger = get_logger(__name__)


class MoneyFlowUpdater(BaseUpdater):
    """Refresh concept, industry, and stock money-flow tables."""

    source_capability = 'stock_money_flow'

    def run(self, trade_date: date) -> dict[str, int]:
        """Fetch and persist all money-flow tables for one trade date."""
        counts: dict[str, int] = {}
        failures: dict[str, str] = {}

        self._run_subtable(
            counts,
            failures,
            'concept_money_flow',
            lambda: self.source.fetch_concept_money_flow(trade_date),
        )
        self._run_subtable(
            counts,
            failures,
            'industry_money_flow',
            lambda: self.source.fetch_industry_money_flow(trade_date),
        )
        self._run_subtable(
            counts,
            failures,
            'stock_money_flow',
            lambda: self.source.fetch_stock_money_flow(trade_date),
        )

        if failures:
            raise PartialUpdateError(
                f"MoneyFlowUpdater completed with skipped subtables on {trade_date.isoformat()}",
                counts=counts,
                failures=failures,
            )
        return counts

    def _run_subtable(
        self,
        counts: dict[str, int],
        failures: dict[str, str],
        table: str,
        fetcher: Callable[[], object],
    ) -> None:
        try:
            counts[table] = self._upsert_meta(table, fetcher())
        except Exception as exc:  # noqa: BLE001
            counts[table] = 0
            failures[table] = str(exc)
            logger.warning(f'Skipping money-flow subtable {table} due to error: {exc}')
