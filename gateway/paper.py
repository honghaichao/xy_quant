"""Paper Gateway — 纸面盘仿真 Gateway。

不做真实券商连接，按回放数据价格撮合。实现 IGateway 接口，
替代 LiveEngine 中硬编码的 paper 撮合逻辑。

模式：
  - paper: 按当日收盘价/开盘价撮合
  - confirm: 按 order_queue 确认价撮合（人工确认）

使用场景：
  1. dispatch 模式: dispatcher.py 接管 order_queue 表，paper 模式自动按次日行情撮合
  2. 集成模式: LiveEngine 委托 PaperGateway 撮合（当前路线）
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

import duckdb
import pandas as pd

from gateway.base import (
    AccountInfo,
    IGateway,
    OrderRequest,
    OrderResponse,
    Position,
    Trade,
)
from config.settings import settings
from utils.logger import get_logger

log = get_logger("gateway.paper")


def _load_daily_bars_for_date(td: date) -> pd.DataFrame | None:
    """加载某个交易日所有股票的日线 OHLCV。"""
    from backtest.execution import load_full_daily_bars
    try:
        return load_full_daily_bars(td, td)
    except Exception:
        return None


def _code_to_ts(code: str) -> str:
    """纯数字代码 → ts_code: 000001 → 000001.SZ, 600519 → 600519.SH"""
    code = str(code).zfill(6)
    return f"{code}.SH" if code.startswith("6") else f"{code}.SZ"


class PaperGateway(IGateway):
    """纸面盘 Gateway — 用历史行情模拟撮合。

    不连接任何外部券商。send_order 时按传入的行情数据直接撮合，
    或延迟到下一个交易日按收盘价撮合。
    """

    def __init__(self, name: str = "paper") -> None:
        self._name = name
        self._connected = False
        self._config: dict[str, Any] = {}
        self._orders: dict[str, dict] = {}  # gateway_order_id → 订单详情

    # ── IGateway 基础属性 ──────────────────────────────

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self, config: dict | None = None) -> bool:
        self._config = config or {}
        self._connected = True
        log.info("PaperGateway connected")
        return True

    def close(self) -> None:
        self._connected = False
        self._orders.clear()
        log.info("PaperGateway closed")

    # ── 订单 ──────────────────────────────────────────

    def send_order(self, req: OrderRequest) -> OrderResponse:
        """纸面盘下单：立即按给定价格成交。

        实际撮合逻辑由 LiveEngine 完成，这里只生成响应。
        """
        oid = f"PAPER_{uuid.uuid4().hex[:12]}"
        self._orders[oid] = {"req": req, "status": "FILLED", "filled_price": req.price}
        return OrderResponse(
            ref_id=req.ref_id,
            gateway_order_id=oid,
            status="FILLED",
            filled_price=req.price,
            filled_volume=req.volume,
            message="paper filled",
        )

    def cancel_order(self, gateway_order_id: str) -> OrderResponse:
        if gateway_order_id in self._orders:
            self._orders[gateway_order_id]["status"] = "CANCELLED"
            return OrderResponse(
                ref_id=0,
                gateway_order_id=gateway_order_id,
                status="CANCELLED",
                message="cancelled",
            )
        return OrderResponse(
            ref_id=0,
            gateway_order_id=gateway_order_id,
            status="REJECTED",
            message="order not found",
        )

    def query_order(self, gateway_order_id: str) -> OrderResponse:
        o = self._orders.get(gateway_order_id)
        if o:
            return OrderResponse(
                ref_id=0,
                gateway_order_id=gateway_order_id,
                status=o["status"],
                filled_price=o.get("filled_price", 0),
                filled_volume=o.get("filled_volume", 0),
            )
        return OrderResponse(
            ref_id=0,
            gateway_order_id=gateway_order_id,
            status="REJECTED",
            message="order not found",
        )

    # ── 查询 ──────────────────────────────────────────

    def query_positions(self) -> list[Position]:
        """从 DuckDB positions 表读取当前持仓。"""
        conn = duckdb.connect(str(settings.duckdb_path), read_only=True)
        try:
            df = conn.execute(
                "SELECT code, name, shares, buy_price, current_price "
                "FROM positions WHERE status = 'holding'"
            ).fetchdf()
            return [
                Position(
                    symbol=row["code"],
                    name=row.get("name", row["code"]),
                    volume=int(row["shares"]),
                    avg_cost=float(row["buy_price"]),
                    current_price=float(row.get("current_price", 0)),
                    market_value=float(row["shares"]) * float(row.get("current_price", 0)),
                    unrealized_pnl=(
                        float(row.get("current_price", 0)) - float(row["buy_price"])
                    ) * float(row["shares"]),
                )
                for _, row in df.iterrows()
            ]
        finally:
            conn.close()

    def query_account(self) -> AccountInfo:
        """从 DuckDB portfolio_daily 表读取最新净值。"""
        conn = duckdb.connect(str(settings.duckdb_path), read_only=True)
        try:
            row = conn.execute(
                "SELECT cash, position_value, total, total_return "
                "FROM portfolio_daily ORDER BY date DESC LIMIT 1"
            ).fetchone()
            if row:
                return AccountInfo(
                    available_cash=float(row[0]),
                    position_value=float(row[1]),
                    total_asset=float(row[2]),
                    total_return=float(row[3]),
                )
        finally:
            conn.close()
        return AccountInfo()

    def query_trades(self, trade_date: date) -> list[Trade]:
        """从 DuckDB jq_live_trades 表读取。"""
        conn = duckdb.connect(str(settings.duckdb_path), read_only=True)
        try:
            df = conn.execute(
                "SELECT date, code, name, action, price, shares, amount, commission "
                "FROM jq_live_trades WHERE date = ?",
                [trade_date],
            ).fetchdf()
            return [
                Trade(
                    trade_id="",
                    gateway_order_id="",
                    symbol=row["code"],
                    action=row["action"],
                    price=float(row["price"]),
                    volume=int(row["shares"]),
                    amount=float(row.get("amount", 0)),
                    commission=float(row.get("commission", 0)),
                    trade_date=row["date"],
                )
                for _, row in df.iterrows()
            ]
        finally:
            conn.close()
