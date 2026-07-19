"""QMT xtquant SDK 客户端封装。

将 xtquant 的回调风格 API 封装为同步/异步统一接口。
仅在 Windows + xtquant 可用时生效，Linux/Mac 自动 fallback 到 stub。

xtquant 参考：
  - XtQuantTrader: 交易 API（order_stock_async, query_*）
  - XtQuantTraderCallback: 回调基类（OnOrderEvent, OnTradeEvent, ...）
  - 连接: trader.start() → trader.connect()
  - 撤单: trader.cancel_order_stock_async()
  - 查询: trader.query_stock_positions(), trader.query_stock_asset()
"""

from __future__ import annotations

import time
from typing import Any

try:
    import xtquant.xttrader as xttrader
    import xtquant.xtdata as xtdata
    HAS_XTQUANT = True
except ImportError:
    HAS_XTQUANT = False


class QmtClient:
    """QMT xtquant 交易客户端封装。

    管理一次连接生命周期，提供统一的 send_order / query_positions 等方法。
    回调事件统一转换为 dict 列表，上层 gateway 自行映射。
    """

    def __init__(self) -> None:
        self._trader = None
        self._connected = False
        self._session_id: int = 0
        self._events: list[dict[str, Any]] = []

    # ── 连接 ────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self, account: str, trade_server: str, quote_ip: str = "",
                session_id: int = 0) -> bool:
        """连接 QMT 交易终端。

        Args:
            account: 资金账号
            trade_server: 交易服务器地址
            quote_ip: 行情服务器地址（可选）
            session_id: 会话 ID（0=主会话）

        Returns:
            True=连接成功
        """
        if not HAS_XTQUANT:
            return False

        try:
            self._session_id = session_id
            self._trader = xttrader.XtQuantTrader(quote_ip or trade_server, session_id)
            fn = f"/tmp/qmt_cb_{session_id}.txt"
            cb = _QmtCallback(self._events)
            self._trader.register_callback(cb)

            self._trader.start()
            if self._trader.connect() != 0:
                return False

            # ping 一下确认连通
            asset = self._trader.query_stock_asset(account)
            if asset is None:
                return False

            self._connected = True
            return True
        except Exception:
            return False

    def close(self) -> None:
        """断开连接。"""
        self._connected = False
        self._trader = None
        self._events.clear()

    # ── 订单 ────────────────────────────────────────────

    def send_order(self, account: str, stock_code: str, order_type: int,
                   order_volume: int, price_type: int, price: float,
                   strategy_name: str = "", order_remark: str = "") -> int:
        """发送订单 — 映射到 xtquant order_stock_async。

        Args:
            account: 资金账号
            stock_code: 股票代码「000001.SZ」格式（QMT 原生格式）
            order_type: xtconstant.STOCK_BUY / STOCK_SELL
            order_volume: 股数
            price_type: xtconstant.FIX_PRICE / MARKET_SH_CONVERT_5_CANCEL ...
            price: 限价
            strategy_name: 策略备注
            order_remark: 订单备注

        Returns:
            订单编号（>0=成功，-1=失败）
        """
        if self._trader is None:
            return -1

        try:
            import xtquant.xtconstant as c
            seq = self._trader.order_stock_async(
                account, stock_code, order_type, order_volume,
                price_type, price, strategy_name, order_remark,
            )
            return seq
        except Exception:
            return -1

    def cancel_order(self, account: str, order_id: int) -> bool:
        """撤单。"""
        if self._trader is None:
            return False
        try:
            return self._trader.cancel_order_stock_async(account, order_id) == 0
        except Exception:
            return False

    # ── 查询 ────────────────────────────────────────────

    def query_positions(self, account: str) -> list[dict]:
        """查询持仓 → [{code, name, volume, avg_cost, market_value, ...}]。"""
        if self._trader is None:
            return []
        try:
            pos = self._trader.query_stock_positions(account)
            if pos is None:
                return []
            result: list[dict] = []
            for p in pos:
                result.append({
                    "code": getattr(p, "stock_code", ""),
                    "name": getattr(p, "stock_name", ""),
                    "volume": getattr(p, "volume", 0),
                    "avg_cost": getattr(p, "avg_cost", 0.0),
                    "market_value": getattr(p, "market_value", 0.0),
                    "unrealized_pnl": getattr(p, "profit", 0.0),
                })
            return result
        except Exception:
            return []

    def query_account(self, account: str) -> dict | None:
        """查询账户资产。"""
        if self._trader is None:
            return None
        try:
            a = self._trader.query_stock_asset(account)
            if a is None:
                return None
            return {
                "available_cash": getattr(a, "cash", 0.0),
                "frozen_cash": getattr(a, "frozen_cash", 0.0),
                "total_asset": getattr(a, "total_asset", 0.0),
                "position_value": getattr(a, "market_value", 0.0),
            }
        except Exception:
            return None

    def query_trades(self, account: str) -> list[dict]:
        """查询当日成交。"""
        if self._trader is None:
            return []
        try:
            trades = self._trader.query_stock_trades(account)
            if trades is None:
                return []
            result: list[dict] = []
            for t in trades:
                result.append({
                    "code": getattr(t, "stock_code", ""),
                    "action": "BUY" if getattr(t, "order_type", 0) in (23, 24) else "SELL",
                    "price": getattr(t, "price", 0.0),
                    "volume": getattr(t, "volume", 0),
                    "amount": getattr(t, "amount", 0.0),
                    "trade_id": str(getattr(t, "order_id", "")),
                })
            return result
        except Exception:
            return []

    def pull_events(self) -> list[dict]:
        """拉取回调事件列表，读后清空。"""
        evs, self._events = self._events, []
        return evs


class _QmtCallback:
    """QMT 回调适配器 — 所有异步回调转为 dict 存入事件列表。"""

    def __init__(self, events: list[dict]) -> None:
        self._events = events

    def OnOrderEvent(self, data):
        self._events.append({
            "type": "order",
            "order_id": getattr(data, "order_id", 0),
            "status": getattr(data, "order_status", ""),
            "filled_volume": getattr(data, "filled_volume", 0),
            "filled_price": getattr(data, "filled_price", 0.0),
        })

    def OnTradeEvent(self, data):
        self._events.append({
            "type": "trade",
            "order_id": getattr(data, "order_id", 0),
            "code": getattr(data, "stock_code", ""),
            "price": getattr(data, "price", 0.0),
            "volume": getattr(data, "volume", 0),
            "amount": getattr(data, "amount", 0.0),
        })

    def OnAccountEvent(self, data):
        self._events.append({
            "type": "account",
            "account_id": getattr(data, "account_id", ""),
            "available": getattr(data, "available", 0.0),
            "total_asset": getattr(data, "total_asset", 0.0),
        })

    def OnErrorEvent(self, error):
        self._events.append({
            "type": "error",
            "error_id": getattr(error, "error_id", 0),
            "error_msg": getattr(error, "error_msg", ""),
        })
