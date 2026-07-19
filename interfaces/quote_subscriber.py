"""行情订阅接口(P6)。"""
from abc import ABC, abstractmethod
from collections.abc import Callable


class IQuoteSubscriber(ABC):
    """Quote subscriber interface for live trading phase."""

    @abstractmethod
    def subscribe(self, symbols: list[str], callback: Callable[..., None]) -> None:
        """Subscribe symbols with callback."""

    @abstractmethod
    def unsubscribe(self, symbols: list[str]) -> None:
        """Unsubscribe symbols."""
