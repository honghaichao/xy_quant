"""板块与指数成分更新器。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from .base import BaseUpdater


class MemberUpdater(BaseUpdater):
    """Refresh concept, industry, and index membership tables."""

    def run(
        self,
        concept_codes: Sequence[str] | None = None,
        industry_codes: Sequence[str] | None = None,
        index_codes: Sequence[str] | None = None,
        trade_date: date | None = None,
    ) -> dict[str, int]:
        """Fetch and persist requested member tables."""
        counts: dict[str, int] = {}
        concept_code_list = list(concept_codes or [])
        industry_code_list = list(industry_codes or [])
        index_code_list = list(index_codes or [])

        if concept_code_list:
            counts['concept_list'] = self._upsert_meta('concept_list', self.source.fetch_concept_list())
            for concept_code in concept_code_list:
                counts[f'concept_member:{concept_code}'] = self._upsert_meta(
                    'concept_member',
                    self.source.fetch_concept_member(concept_code),
                )

        if industry_code_list:
            counts['industry_list'] = self._upsert_meta('industry_list', self.source.fetch_industry_list())
            for industry_code in industry_code_list:
                counts[f'industry_member:{industry_code}'] = self._upsert_meta(
                    'industry_member',
                    self.source.fetch_industry_member(industry_code),
                )

        for index_code in index_code_list:
            counts[f'index_weight:{index_code}'] = self._upsert_meta(
                'index_weight',
                self.source.fetch_index_weight(index_code, trade_date=trade_date),
            )
        return counts
