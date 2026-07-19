"""Storage schema initialization service."""

from __future__ import annotations

from data.storage.factory import get_market_store, get_meta_store
from interfaces.market_store import IMarketStore
from interfaces.meta_store import IMetaStore


class SchemaInitializer:
    """Initialize storage schemas independently from updater execution."""

    def __init__(
        self,
        *,
        market_store: IMarketStore | None = None,
        meta_store: IMetaStore | None = None,
    ) -> None:
        self._market_store = market_store
        self._meta_store = meta_store

    def run(self) -> None:
        market_store = self._market_store or get_market_store("duckdb")
        try:
            market_store.init_schema()
        finally:
            market_store.close()

        meta_store = self._meta_store or get_meta_store("postgres")
        try:
            meta_store.init_schema()
        finally:
            meta_store.close()
