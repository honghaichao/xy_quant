"""Unit tests for Redis-backed cache implementation."""

from __future__ import annotations

import json
from typing import Any

from data.storage.redis_cache import RedisCache


class FakeRedisClient:
    """Simple in-memory Redis-like client for unit tests."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttl_by_key: dict[str, int] = {}

    def get(self, key: str) -> str | None:
        """Return stored value if present."""
        return self.values.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        """Store a serialized value with optional TTL."""
        self.values[key] = value
        if ex is not None:
            self.ttl_by_key[key] = ex

    def delete(self, key: str) -> None:
        """Delete stored key if present."""
        self.values.pop(key, None)
        self.ttl_by_key.pop(key, None)

    def exists(self, key: str) -> int:
        """Return Redis-style existence flag."""
        return int(key in self.values)


def test_cache_round_trip_and_ttl() -> None:
    """Cache serializes values, restores them, and respects TTL wiring."""
    client = FakeRedisClient()
    cache = RedisCache(client=client)
    payload: dict[str, Any] = {"alpha": 1, "items": [1, 2, 3]}

    cache.set("demo", payload, ttl=120)

    assert client.values["demo"] == json.dumps(payload)
    assert client.ttl_by_key["demo"] == 120
    assert cache.exists("demo") is True
    assert cache.get("demo") == payload


def test_cache_delete_and_missing_value() -> None:
    """Cache delete removes values and missing keys return None."""
    client = FakeRedisClient()
    cache = RedisCache(client=client)

    assert cache.get("missing") is None
    assert cache.exists("missing") is False

    cache.set("demo", [1, 2, 3])
    cache.delete("demo")

    assert cache.exists("demo") is False
    assert cache.get("demo") is None
