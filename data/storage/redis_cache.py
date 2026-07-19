"""Redis-backed cache implementation."""

from __future__ import annotations

import json
from typing import Any

import redis

from config.settings import settings
from interfaces.cache import ICache


class RedisCache(ICache):
    """Redis-backed cache with JSON serialization."""

    def __init__(self, client: Any | None = None) -> None:
        """Initialize the cache with an optional injected Redis client."""
        self._client = client or redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            password=settings.redis_password or None,
            decode_responses=True,
        )

    def get(self, key: str) -> Any | None:
        """Return a cached value or ``None`` when missing."""
        value = self._client.get(key)
        if value is None:
            return None
        if isinstance(value, bytes):
            return json.loads(value.decode())
        return json.loads(str(value))

    def set(self, key: str, value: Any, ttl: int = 300) -> None:
        """Store a JSON-serializable value with a TTL in seconds."""
        self._client.set(key, json.dumps(value), ex=ttl)

    def delete(self, key: str) -> None:
        """Delete a cached value if present."""
        self._client.delete(key)

    def exists(self, key: str) -> bool:
        """Return whether the cache key exists."""
        return bool(self._client.exists(key))
