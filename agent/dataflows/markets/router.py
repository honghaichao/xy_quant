"""市场路由器 - MarketRouter (A股 only)."""
from typing import Any


class HKStockData:
    """港股数据 (存根 — 暂不实现)."""
    pass


class USStockData:
    """美股数据 (存根 — 暂不实现)."""
    pass


class MarketRouter:
    """市场路由器。当前仅支持A股。"""

    def get_market(self, symbol: str) -> str:
        symbol = str(symbol)
        if symbol.startswith("6"):
            return "SH"
        return "SZ"

    @property
    def hk_data(self):
        if not hasattr(self, "_hk_data"):
            self._hk_data = HKStockData()
        return self._hk_data

    @property
    def us_data(self):
        if not hasattr(self, "_us_data"):
            self._us_data = USStockData()
        return self._us_data
