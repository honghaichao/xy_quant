"""缓存接口。"""
from abc import ABC, abstractmethod
from typing import Any


class ICache(ABC):
    """Cache interface."""

    @abstractmethod
    def get(self, key: str) -> Any | None:
        """Get cached value."""

    @abstractmethod
    def set(self, key: str, value: Any, ttl: int = 300) -> None:
        """Set cached value."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete cached value."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check whether key exists."""
