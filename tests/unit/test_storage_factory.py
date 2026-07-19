"""Unit tests for storage factory registration."""

from __future__ import annotations

import pytest

from data.storage.duckdb_store import DuckDBMarketStore
from data.storage.factory import get_cache, get_market_store, get_meta_store
from data.storage.pg_store import PostgresMetaStore
from data.storage.redis_cache import RedisCache
from utils.exception import ConfigError


def test_factory_returns_default_storage_backends() -> None:
    """Factory resolves the default backend implementations."""
    market_store = get_market_store("duckdb")
    meta_store = get_meta_store("postgres")
    cache = get_cache("redis")

    assert isinstance(market_store, DuckDBMarketStore)
    assert isinstance(meta_store, PostgresMetaStore)
    assert isinstance(cache, RedisCache)

    market_store.close()
    meta_store.close()


@pytest.mark.parametrize(
    ("kind", "name", "expected_message"),
    [
        ("market", "sqlite", "Unsupported market store"),
        ("meta", "mysql", "Unsupported meta store"),
        ("cache", "memory", "Unsupported cache backend"),
    ],
)
def test_factory_rejects_unsupported_backend_names(
    kind: str,
    name: str,
    expected_message: str,
) -> None:
    """Factory raises ConfigError for unsupported backend names."""
    with pytest.raises(ConfigError, match=expected_message):
        if kind == "market":
            get_market_store(name)
        elif kind == "meta":
            get_meta_store(name)
        else:
            get_cache(name)
