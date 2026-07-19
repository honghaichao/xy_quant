"""Gateway 模块 — 统一券商/仿真网关适配层。

导出：
  - GatewayManager: 多 gateway 实例管理与订单分发
  - PaperGateway: 纸面盘仿真 gateway（无需真实券商）
  - QmtGateway: 国金/QMT 券商 gateway（需要 Windows + xtquant）
  - IGateway / OrderRequest / OrderResponse / ...: 标准化接口与数据模型
"""

from gateway.base import (
    IGateway,
    OrderRequest,
    OrderResponse,
    Position,
    Trade,
    AccountInfo,
)
from gateway.manager import GatewayManager, get_manager
from gateway.paper import PaperGateway
from gateway.qmt import QmtGateway
from gateway.event import GatewayEvent, EventType

__all__ = [
    # 接口
    "IGateway",
    # 数据模型
    "OrderRequest",
    "OrderResponse",
    "Position",
    "Trade",
    "AccountInfo",
    # 事件
    "GatewayEvent",
    "EventType",
    # 实现
    "GatewayManager",
    "PaperGateway",
    "QmtGateway",
    # 入口
    "get_manager",
]
