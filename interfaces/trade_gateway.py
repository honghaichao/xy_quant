"""交易网关接口(P4 起)。"""
from abc import ABC, abstractmethod
from typing import Any


class ITradeGateway(ABC):
    """Trading gateway interface."""

    @abstractmethod
    def place_order(self, **kwargs: Any) -> str:
        """Place an order and return order id."""

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""

    @abstractmethod
    def get_positions(self) -> list[dict[str, Any]]:
        """Return current positions."""
