"""Explicit data-source selection policy."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Final, cast

from config.settings import settings
from data.source.factory import get_data_source
from interfaces.data_source import IDataSource

DEFAULT_PREFERRED_SOURCES_BY_CAPABILITY: Final[dict[str, tuple[str, ...]]] = {
    "minute_bar": ("tushare",),
    "limit_pool": ("tushare",),
    "hk_hold": ("tushare",),
    "concept_money_flow": ("tushare",),
    "industry_money_flow": ("tushare",),
    "stock_money_flow": ("tushare",),
    "daily_bar": ("tushare",),
    "adj_factor": ("tushare",),
    "daily_basic": ("tushare",),
    "stock_basic": ("tushare",),
    "trade_calendar": ("tushare",),
    "stock_suspend": ("tushare",),
}


class SourceSelectionPolicy:
    """Resolve data sources from explicit capability-aware preferences."""

    def __init__(
        self,
        *,
        factory: Callable[[str], Any] = get_data_source,
        preferred_sources_by_capability: Mapping[str, tuple[str, ...]] | None = None,
        primary_source: str | None = None,
        fallback_source: str | None = None,
    ) -> None:
        self._factory = factory
        self._preferred_sources_by_capability = dict(
            preferred_sources_by_capability or DEFAULT_PREFERRED_SOURCES_BY_CAPABILITY
        )
        self._primary_source = primary_source or settings.primary_data_source
        self._fallback_source = fallback_source or settings.fallback_data_source

    def resolve(self, capability: str | None) -> IDataSource:
        candidate_names = self.candidate_names(capability)
        if capability is None:
            return cast(IDataSource, self._factory(candidate_names[0]))

        for source_name in candidate_names:
            data_source = cast(IDataSource, self._factory(source_name))
            if data_source.supports(capability):
                return data_source
        return cast(IDataSource, self._factory(candidate_names[0]))

    def candidate_names(self, capability: str | None) -> list[str]:
        names: list[str] = []
        preferred_sources = () if capability is None else self._preferred_sources_by_capability.get(capability, ())
        for source_name in (*preferred_sources, self._primary_source, self._fallback_source):
            if source_name and source_name not in names:
                names.append(source_name)
        return names
