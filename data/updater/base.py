"""数据更新业务层抽象基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

import pandas as pd

from data.source.factory import get_data_source
from data.source.strategy import SourceSelectionPolicy
from data.storage.factory import get_market_store, get_meta_store
from interfaces.data_source import IDataSource
from interfaces.market_store import IMarketStore
from interfaces.meta_store import IMetaStore


class BaseUpdater(ABC):
    """Shared wiring and helper methods for updater services."""

    source_capability: str | None = None

    def __init__(
        self,
        source: IDataSource | None = None,
        market_store: IMarketStore | None = None,
        meta_store: IMetaStore | None = None,
        source_strategy: SourceSelectionPolicy | None = None,
    ) -> None:
        self._source_strategy = source_strategy or SourceSelectionPolicy(factory=get_data_source)
        self.source = source or self._resolve_default_source()
        self._market_store = market_store
        self._meta_store = meta_store

    @property
    def market_store(self) -> IMarketStore:
        if self._market_store is None:
            self._market_store = get_market_store('duckdb')
        return self._market_store

    @property
    def meta_store(self) -> IMetaStore:
        if self._meta_store is None:
            self._meta_store = get_meta_store('postgres')
        return self._meta_store

    def _resolve_default_source(self) -> IDataSource:
        return self._source_strategy.resolve(self.source_capability)

    @abstractmethod
    def run(self, *args: Any, **kwargs: Any) -> dict[str, int]:
        """Execute the updater workflow and return per-table row counts."""

    def close(self) -> None:
        """Close owned store resources."""
        for store in (self._market_store, self._meta_store):
            if store is None:
                continue
            close = getattr(store, 'close', None)
            if callable(close):
                close()

    def _upsert_market(self, table: str, frame: pd.DataFrame) -> int:
        """Persist a market-data frame if it contains rows."""
        if frame.empty:
            return 0
        return self.market_store.upsert(table, frame)

    def _upsert_meta(self, table: str, frame: pd.DataFrame) -> int:
        """Persist a metadata frame if it contains rows."""
        if frame.empty:
            return 0
        return self.meta_store.upsert(table, frame)

    @staticmethod
    def _safe_extend(target: dict[str, int], rows: dict[str, int]) -> dict[str, int]:
        """Merge per-table row counts into a single dictionary."""
        for key, value in rows.items():
            target[key] = target.get(key, 0) + value
        return target

    @staticmethod
    def _ensure_code_list(ts_codes: Sequence[str] | None) -> list[str]:
        """Normalize an optional security-code sequence to a list."""
        return list(ts_codes or [])
