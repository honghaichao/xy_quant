"""聚宽兼容对象：Context / Portfolio / Position 只读视图 + G 全局容器。

字段名照聚宽（total_amount / closeable_amount / avg_cost / price / value）。
Portfolio.positions 的键同时接受 6 位码与带后缀形式（.XSHE/.SZ 等）。
"""

from __future__ import annotations

import pickle
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from jq_adapter.utils import get_code_part

if TYPE_CHECKING:
    from engine.account import Account, PositionState


class G:
    """聚宽 g 对象：任意属性容器，支持 pickle 持久化。"""

    def state_bytes(self) -> bytes:
        return pickle.dumps(self.__dict__)

    def load_bytes(self, raw: bytes) -> None:
        self.__dict__.update(pickle.loads(raw))

    def __repr__(self) -> str:
        return f"G({self.__dict__})"


class Position:
    """单只持仓的只读视图（聚宽字段名）。"""

    def __init__(self, code: str, state: "PositionState", price: float | None = None):
        self.security = code
        self._state = state
        self._price = price

    @property
    def total_amount(self) -> int:
        return self._state.total_amount

    @property
    def closeable_amount(self) -> int:
        return self._state.closeable_amount

    @property
    def avg_cost(self) -> float:
        return self._state.avg_cost

    @property
    def price(self) -> float:
        return self._price if self._price is not None else self._state.avg_cost

    @property
    def value(self) -> float:
        return self.total_amount * self.price

    def __repr__(self) -> str:
        return (f"Position({self.security}, amount={self.total_amount}, "
                f"closeable={self.closeable_amount}, avg_cost={self.avg_cost:.3f})")


class _PositionsView(dict):
    """positions 字典视图：键宽容（'000001' / '000001.XSHE' / '000001.SZ' 等价）。"""

    def __getitem__(self, key: str) -> Position:
        return super().__getitem__(get_code_part(key))

    def __contains__(self, key: object) -> bool:
        return super().__contains__(get_code_part(str(key)))

    def get(self, key: str, default: Any = None) -> Any:
        return super().get(get_code_part(key), default)


class Portfolio:
    """账户组合视图，实时反映 Account 状态。"""

    def __init__(self, account: "Account"):
        self._account = account
        self._price_map: dict[str, float] = {}

    def update_prices(self, price_map: dict[str, float]) -> None:
        """引擎在每个时间槽刷新最新可见价格。"""
        self._price_map.update(price_map)

    @property
    def available_cash(self) -> float:
        return self._account.cash

    @property
    def positions(self) -> _PositionsView:
        view = _PositionsView()
        for code, state in self._account.positions.items():
            view[code] = Position(code, state, self._price_map.get(code))
        return view

    @property
    def positions_value(self) -> float:
        return self._account.position_value(self._price_map)

    @property
    def total_value(self) -> float:
        return self._account.total_value(self._price_map)

    @property
    def starting_cash(self) -> float:
        return self._account.initial_cash

    def __repr__(self) -> str:
        return (f"Portfolio(cash={self.available_cash:.2f}, "
                f"positions={len(self._account.positions)}, total={self.total_value:.2f})")


class Context:
    """策略上下文。用户自定义属性落 _user_data（聚宽允许 context.xxx = ...）。"""

    _RESERVED = {"_user_data", "_portfolio", "current_dt", "previous_date", "run_params"}

    def __init__(self, portfolio: Portfolio, run_params: dict | None = None):
        object.__setattr__(self, "_user_data", {})
        object.__setattr__(self, "_portfolio", portfolio)
        object.__setattr__(self, "current_dt", None)
        object.__setattr__(self, "previous_date", None)
        object.__setattr__(self, "run_params", run_params or {})

    @property
    def portfolio(self) -> Portfolio:
        return self._portfolio

    def _set_clock(self, current_dt: datetime, previous_date: date) -> None:
        object.__setattr__(self, "current_dt", current_dt)
        object.__setattr__(self, "previous_date", previous_date)

    def __setattr__(self, key: str, value: Any) -> None:
        if key in self._RESERVED:
            object.__setattr__(self, key, value)
        else:
            self._user_data[key] = value

    def __getattr__(self, key: str) -> Any:
        try:
            return object.__getattribute__(self, "_user_data")[key]
        except KeyError:
            raise AttributeError(key) from None
