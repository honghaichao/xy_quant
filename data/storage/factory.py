"""Storage factory."""

from __future__ import annotations

from data.storage.duckdb_store import DuckDBMarketStore
from data.storage.pg_store import PostgresMetaStore
from data.storage.redis_cache import RedisCache
from interfaces.cache import ICache
from interfaces.market_store import IMarketStore
from interfaces.meta_store import IMetaStore
from utils.exception import ConfigError

MARKET_STORE_REGISTRY: dict[str, type[IMarketStore]] = {"duckdb": DuckDBMarketStore}
META_STORE_REGISTRY: dict[str, type[IMetaStore]] = {"postgres": PostgresMetaStore}
CACHE_REGISTRY: dict[str, type[ICache]] = {"redis": RedisCache}


def get_market_store(name: str, read_only: bool = False) -> IMarketStore:
    """Get market store by name.

    Set read_only=True to avoid DuckDB write-lock contention during concurrent reads (e.g. backtests).
    """
    store_class = MARKET_STORE_REGISTRY.get(name)
    if store_class is None:
        raise ConfigError(f"Unsupported market store: {name}")
    if name == "duckdb":
        return store_class(read_only=read_only)
    return store_class()


def get_meta_store(name: str) -> IMetaStore:
    """Get meta store by name."""
    store_class = META_STORE_REGISTRY.get(name)
    if store_class is None:
        raise ConfigError(f"Unsupported meta store: {name}")
    return store_class()


def get_cache(name: str) -> ICache:
    """Get cache backend by name."""
    cache_class = CACHE_REGISTRY.get(name)
    if cache_class is None:
        raise ConfigError(f"Unsupported cache backend: {name}")
    return cache_class()
