"""QMT Gateway — 国金/QMT 券商适配器。

实现 IGateway 接口，通过 xtquant SDK 与 QMT 交易终端通信。
仅在 Windows + xtquant 可用时能真正连接，Mac 上 connect() 返回 False。

与 PaperGateway 的区别：
  - PaperGateway: 用历史行情撮合，不依赖真实券商
  - QmtGateway: 真实下单到券商柜台，连接 QMT 极简交易终端

用法:
    gw = QmtGateway()
    if gw.connect({"account": "...", "server": "..."}):
        resp = gw.send_order(OrderRequest(...))
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from gateway.base import (
    AccountInfo,
    IGateway,
    OrderRequest,
    OrderResponse,
    Position,
    Trade,
)
from gateway.qmt.client import HAS_XTQUANT, QmtClient
from utils.logger import get_logger

log = get_logger("gateway.qmt")

# 代码格式转换: xy_quant 内部代码 → QMT 代码 (000001 → 000001.SZ)
def _to_qmt_code(code: str) -> str:
    code = str(code).zfill(6)
    if "." not in code:
        return f"{code}.SH" if code.startswith("6") else f"{code}.SZ"
    return code


# QMT 代码 → xy_quant 内部代码
def _from_qmt_code(qmt_code: str) -> str:
    return qmt_code.split(".")[0] if "." in qmt_code else qmt_code


class QmtGateway(IGateway):
    """QMT 券商网关 — 通过 xtquant 连接国金等券商交易终端。"""

    def __init__(self, name: str = "qmt") -> None:
        self._name = name
        self._client = QmtClient()
        self._account: str = ""
        self._orders: dict[str, dict] = {}  # gateway_order_id → {req, ...}

    # ── IGateway 基础属性 ──────────────────────────────

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_connected(self) -> bool:
        return self._client.is_connected

    def connect(self, config: dict | None = None) -> bool:
        if not HAS_XTQUANT:
            log.warning("xtquant 不可用（非 Windows 环境），QmtGateway 无法连接")
            return False

        cfg = config or {}
        account = cfg.get("account", "")
        server = cfg.get("server", "")
        quote_ip = cfg.get("quote_ip", "")

        if not account or not server:
            log.error("QMT 连接需要 account 和 server")
            return False

        self._account = account
        ok = self._client.connect(account, server, quote_ip)
        if ok:
            log.info(f"QmtGateway 连接成功: account={account}")
        return ok

    def close(self) -> None:
        self._client.close()
        self._orders.clear()

    # ── 订单 ──────────────────────────────────────────

    def send_order(self, req: OrderRequest) -> OrderResponse:
        if not self.is_connected:
            return OrderResponse(
                ref_id=req.ref_id,
                gateway_order_id="",
                status="REJECTED",
                message="QMT 未连接",
            )

        try:
            import xtquant.xtconstant as c

            order_type = c.STOCK_BUY if req.action == "BUY" else c.STOCK_SELL
            price_type = c.FIX_PRICE if req.order_type == "LIMIT" else c.MARKET_SH_CONVERT_5_CANCEL
            qmt_code = _to_qmt_code(req.symbol)

            seq = self._client.send_order(
                account=self._account,
                stock_code=qmt_code,
                order_type=order_type,
                order_volume=req.volume,
                price_type=price_type,
                price=req.price,
                strategy_name=req.strategy_id or "xy_quant",
                order_remark=f"ref:{req.ref_id}",
            )

            oid = f"QMT_{seq}" if seq > 0 else f"QMT_REJ_{uuid.uuid4().hex[:8]}"
            self._orders[oid] = {"req": req, "seq": seq}

            if seq > 0:
                return OrderResponse(
                    ref_id=req.ref_id,
                    gateway_order_id=oid,
                    status="SUBMITTED",
                    filled_price=0,
                    message=f"seq={seq}",
                )
            else:
                return OrderResponse(
                    ref_id=req.ref_id,
                    gateway_order_id=oid,
                    status="REJECTED",
                    message="QMT 返回序列号无效",
                )

        except Exception as e:
            return OrderResponse(
                ref_id=req.ref_id,
                gateway_order_id="",
                status="REJECTED",
                message=str(e),
            )

    def cancel_order(self, gateway_order_id: str) -> OrderResponse:
        if not self.is_connected:
            return OrderResponse(
                ref_id=0,
                gateway_order_id=gateway_order_id,
                status="REJECTED",
                message="QMT 未连接",
            )

        o = self._orders.get(gateway_order_id)
        if o is None:
            return OrderResponse(
                ref_id=0,
                gateway_order_id=gateway_order_id,
                status="REJECTED",
                message="订单不存在",
            )

        seq = o.get("seq", 0)
        ok = self._client.cancel_order(self._account, seq)
        return OrderResponse(
            ref_id=0,
            gateway_order_id=gateway_order_id,
            status="CANCELLED" if ok else "REJECTED",
            message="OK" if ok else "撤单失败",
        )

    def query_order(self, gateway_order_id: str) -> OrderResponse:
        # 从回调事件中检查最新状态
        events = self._client.pull_events()
        for ev in events:
            if ev.get("type") == "order":
                eid = f"QMT_{ev.get('order_id')}"
                if eid == gateway_order_id:
                    status = ev.get("status", "")
                    if status == "56":        # 全部成交
                        return OrderResponse(
                            ref_id=0, gateway_order_id=gateway_order_id,
                            status="FILLED",
                            filled_price=ev.get("filled_price", 0),
                            filled_volume=ev.get("filled_volume", 0),
                        )
                    elif status == "48":      # 已报（等待）
                        return OrderResponse(
                            ref_id=0, gateway_order_id=gateway_order_id,
                            status="SUBMITTED",
                        )
                    elif status in ("49", "50", "51", "52", "53", "54", "55"):
                        return OrderResponse(
                            ref_id=0, gateway_order_id=gateway_order_id,
                            status="PARTIAL_FILLED",
                            filled_volume=ev.get("filled_volume", 0),
                        )
        # 默认返回已提交
        return OrderResponse(
            ref_id=0, gateway_order_id=gateway_order_id,
            status="SUBMITTED", message="无状态更新",
        )

    # ── 查询 ──────────────────────────────────────────

    def query_positions(self) -> list[Position]:
        raw = self._client.query_positions(self._account)
        return [
            Position(
                symbol=_from_qmt_code(p["code"]),
                name=p.get("name", ""),
                volume=p.get("volume", 0),
                avg_cost=p.get("avg_cost", 0),
                market_value=p.get("market_value", 0),
                unrealized_pnl=p.get("unrealized_pnl", 0),
            )
            for p in raw
        ]

    def query_account(self) -> AccountInfo:
        raw = self._client.query_account(self._account)
        if raw is None:
            return AccountInfo()
        return AccountInfo(
            available_cash=raw.get("available_cash", 0),
            frozen_cash=raw.get("frozen_cash", 0),
            total_asset=raw.get("total_asset", 0),
            position_value=raw.get("position_value", 0),
        )

    def query_trades(self, trade_date: date) -> list[Trade]:
        raw = self._client.query_trades(self._account)
        return [
            Trade(
                trade_id=t.get("trade_id", ""),
                gateway_order_id="",
                symbol=_from_qmt_code(t["code"]),
                action=t.get("action", "BUY"),
                price=t.get("price", 0),
                volume=t.get("volume", 0),
                amount=t.get("amount", 0),
                trade_date=trade_date,
            )
            for t in raw
        ]
