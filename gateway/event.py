"""Gateway 事件定义 — 标准化的事件类型与数据模型。

用于 Gateway → 上层业务模块 的异步通知（后续扩展实时推送用）。
当前阶段（离线调度）直接在 GatewayManager.dispatch_pending_orders() 中同步处理。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class EventType(str, Enum):
    """Gateway 事件类型"""
    ORDER_SUBMITTED = "order_submitted"       # 订单已提交到柜台
    ORDER_FILLED = "order_filled"             # 订单全部成交
    ORDER_PARTIAL_FILLED = "order_partial_filled"  # 部分成交
    ORDER_REJECTED = "order_rejected"         # 订单被拒
    ORDER_CANCELLED = "order_cancelled"       # 已撤单
    TRADE = "trade"                           # 成交推送
    POSITION_CHANGED = "position_changed"     # 持仓变动
    ACCOUNT_CHANGED = "account_changed"       # 账户资金变动
    CONNECTION_LOST = "connection_lost"       # 连接断开
    ERROR = "error"                           # 通用错误


@dataclass
class GatewayEvent:
    """标准化 Gateway 事件"""
    type: EventType
    gateway_name: str
    data: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    message: str = ""

    def __repr__(self) -> str:
        return f"GatewayEvent({self.type.value} from {self.gateway_name})"
