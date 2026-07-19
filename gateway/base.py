"""Gateway 抽象接口 — 统一券商/仿真网关的业务对象与接口。

参考 vnpy Gateway 设计模式，标准化 Order/Position/Trade/AccountInfo 数据类以及
IGateway 抽象接口。所有 gateway 适配器（Paper / QMT / CTP）都需实现此接口。

设计原则：
  - 数据类不可变（@dataclass frozen），作为标准化契约
  - IGateway 是纯粹抽象层，不含任何实现细节
  - 订单、成交、持仓三态分离，各自独立管理
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal


# ═══════════════════════════════════════════════════════════════
# 标准化业务对象
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class OrderRequest:
    """下单请求 — 业务层→Gateway 的标准化入参。

    所有 Gateway 实现都接收此对象，封装具体券商 API 参数差异。
    """
    symbol: str                # 股票代码（统一格式: 000001.SZ / 600519.SH）
    action: Literal["BUY", "SELL"]
    price: float               # 限价（0=市价委托）
    volume: int                # 股数（已取整为 100 的整数倍）
    order_type: Literal["LIMIT", "MARKET"] = "LIMIT"
    strategy_id: str = ""      # 关联策略 ID
    ref_id: int = 0            # order_queue.id 关联，用于回写状态

    def __repr__(self) -> str:
        return (
            f"OrderReq({self.action} {self.symbol} "
            f"x{self.volume} @ {self.price:.2f})"
        )


@dataclass(frozen=True)
class OrderResponse:
    """订单响应 — Gateway→业务层 的标准化回执。"""
    ref_id: int
    gateway_order_id: str      # 柜台/仿真订单 ID
    status: Literal["SUBMITTED", "PARTIAL_FILLED", "FILLED", "REJECTED", "CANCELLED"]
    filled_price: float = 0.0
    filled_volume: int = 0
    message: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass(frozen=True)
class Position:
    """持仓快照"""
    symbol: str
    name: str = ""
    volume: int = 0            # 当前持仓股数
    avg_cost: float = 0.0      # 平均成本
    current_price: float = 0.0
    market_value: float = 0.0
    unrealized_pnl: float = 0.0


@dataclass(frozen=True)
class Trade:
    """成交记录（从柜台回执解析）"""
    trade_id: str
    gateway_order_id: str
    symbol: str
    action: Literal["BUY", "SELL"]
    price: float
    volume: int
    amount: float              # price * volume
    commission: float = 0.0
    trade_date: date | None = None
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass(frozen=True)
class AccountInfo:
    """账户资金信息"""
    available_cash: float = 0.0
    frozen_cash: float = 0.0
    total_asset: float = 0.0   # 总资产（含持仓市值）
    position_value: float = 0.0
    total_return: float = 0.0  # 累计收益率


# ═══════════════════════════════════════════════════════════════
# Gateway 抽象接口
# ═══════════════════════════════════════════════════════════════

class IGateway(ABC):
    """统一 Gateway 接口 — 所有券商/仿真适配器须实现此接口。

    生命周期: connect → operate → close
    所有方法应线程安全（当前阶段单线程调用即可）。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Gateway 名称标识，如 'paper' / 'qmt' / 'ctp'。"""
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """当前连接状态。"""
        ...

    @abstractmethod
    def connect(self, config: dict | None = None) -> bool:
        """建立连接/初始化。

        Args:
            config: 连接配置字典，key 由各实现自行定义。

        Returns:
            True=连接成功，False=失败（上层可重试）。
        """
        ...

    @abstractmethod
    def close(self) -> None:
        """关闭连接，释放资源。幂等。"""
        ...

    @abstractmethod
    def send_order(self, req: OrderRequest) -> OrderResponse:
        """发送订单指令。

        Args:
            req: 下单请求（含策略关联、关联 ref_id）。

        Returns:
            OrderResponse（SUBMITTED / REJECTED / ...）。

        Raises:
            ConnectionError: 连接已断开
            RuntimeError: 券商 API 异常
        """
        ...

    @abstractmethod
    def cancel_order(self, gateway_order_id: str) -> OrderResponse:
        """撤单。

        Args:
            gateway_order_id: 柜台订单 ID。

        Returns:
            OrderResponse（CANCELLED / REJECTED）。
        """
        ...

    @abstractmethod
    def query_positions(self) -> list[Position]:
        """查询当前持仓列表。"""
        ...

    @abstractmethod
    def query_account(self) -> AccountInfo:
        """查询账户资金信息。"""
        ...

    @abstractmethod
    def query_trades(self, trade_date: date) -> list[Trade]:
        """查询某个交易日的成交记录。

        Args:
            trade_date: 交易日。

        Returns:
            成交列表（可空）。
        """
        ...

    @abstractmethod
    def query_order(self, gateway_order_id: str) -> OrderResponse:
        """查询单个订单的当前状态。

        Args:
            gateway_order_id: 柜台订单 ID。

        Returns:
            OrderResponse（含最新成交状态）。
        """
        ...
