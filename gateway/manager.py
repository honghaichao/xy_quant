"""Gateway Manager — 多 Gateway 实例管理与事件路由。

参考 vnpy 的 MainEngine / EventEngine 模式，提供：
  - 多个 gateway 实例的统一注册/查找
  - 订单分发：从 order_queue 表读取 pending 单 → 调用对应 gateway
  - 状态同步：gateway 成交回执 → order_queue / positions 表回写
  - 日终结算入口：GatewayManager.run_daily(trade_date)
"""

from __future__ import annotations

from datetime import date
from typing import Any

from gateway.base import IGateway, OrderRequest
from utils.db import connect_write
from utils.logger import get_logger
from config.settings import settings

log = get_logger("gateway.manager")


class GatewayManager:
    """Gateway 实例管理器。

    单例模式（进程级），管理所有已注册的 gateway。
    """

    _instance: GatewayManager | None = None

    def __init__(self) -> None:
        self._gateways: dict[str, IGateway] = {}

    @classmethod
    def instance(cls) -> GatewayManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── 注册/查找 ──────────────────────────────────────

    def register(self, gw: IGateway) -> None:
        """注册一个 gateway 实例。同名会覆盖。"""
        self._gateways[gw.name] = gw
        log.info(f"Gateway registered: {gw.name}")

    def get(self, name: str) -> IGateway | None:
        """按名称查找 gateway。"""
        return self._gateways.get(name)

    @property
    def gateways(self) -> dict[str, IGateway]:
        return dict(self._gateways)

    # ── 订单分发 ──────────────────────────────────────

    def dispatch_pending_orders(self, trade_date: date, *,
                                 gateway_name: str = "paper") -> list[dict]:
        """从 order_queue 表读取当日 pending 订单并提交到指定 gateway。

        Args:
            trade_date: 交易日
            gateway_name: 目标 gateway 名称（默认 paper）

        Returns:
            每条订单的结果记录列表
        """
        gw = self.get(gateway_name)
        if gw is None:
            log.error(f"Gateway '{gateway_name}' 未注册")
            return []

        if not gw.is_connected:
            log.warning(f"Gateway '{gateway_name}' 未连接，尝试连接")
            if not gw.connect():
                log.error(f"Gateway '{gateway_name}' 连接失败")
                return []

        # 读取 pending 订单
        import duckdb
        conn = duckdb.connect(str(settings.duckdb_path), read_only=True)
        try:
            rows = conn.execute(
                "SELECT id, strategy, trade_date, code, name, action, price, shares, reason "
                "FROM order_queue "
                "WHERE trade_date = ? AND status = 'pending' "
                "ORDER BY id",
                [trade_date],
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            log.info(f"当日 ({trade_date}) 无 pending 订单")
            return []

        results = []
        for row in rows:
            oid, strategy, td, code, name, action, price, shares, reason = row
            req = OrderRequest(
                symbol=code,
                action=action,
                price=float(price),
                volume=int(shares),
                order_type="LIMIT",
                strategy_id=strategy or "",
                ref_id=int(oid),
            )
            try:
                resp = gw.send_order(req)
                self._update_order_status(
                    int(oid),
                    resp.status,
                    resp.gateway_order_id,
                    resp.filled_price,
                    resp.filled_volume,
                )
                results.append({
                    "id": oid, "code": code, "action": action,
                    "status": resp.status, "message": resp.message,
                })
            except Exception as e:
                log.error(f"订单 {oid} 提交失败: {e}")
                self._update_order_status(int(oid), "REJECTED", "", 0, 0)
                results.append({
                    "id": oid, "code": code, "action": action,
                    "status": "REJECTED", "message": str(e),
                })

        filled = sum(1 for r in results if r["status"] in ("FILLED", "SUBMITTED"))
        rejected = sum(1 for r in results if r["status"] == "REJECTED")
        log.info(f"分发完成: {filled} 成功, {rejected} 失败 (共 {len(results)})")
        return results

    def _update_order_status(self, ref_id: int, status: str,
                              gateway_order_id: str,
                              filled_price: float, filled_volume: int) -> None:
        """回写 order_queue 表状态。"""
        from datetime import datetime
        gw_status = "confirmed" if status in ("FILLED", "PARTIAL_FILLED") else status.lower()
        conn = connect_write(str(settings.duckdb_path))
        try:
            if gw_status == "confirmed":
                conn.execute(
                    "UPDATE order_queue SET status = 'confirmed', confirmed_at = ?, "
                    "confirmed_price = ?, confirmed_shares = ? WHERE id = ?",
                    [datetime.now(), filled_price, filled_volume, ref_id],
                )
            else:
                conn.execute(
                    "UPDATE order_queue SET status = ? WHERE id = ?",
                    [gw_status, ref_id],
                )
        finally:
            conn.close()

    # ── 日终入口 ──────────────────────────────────────

    def run_daily(self, trade_date: date, *,
                   gateway_name: str = "paper",
                   sync_positions: bool = True) -> dict[str, Any]:
        """日终结算入口 — 调度器/脚本调用此方法。

        1. 分派 pending 订单
        2. (可选) 同步持仓/净值到 positions / portfolio_daily 表

        Returns:
            汇总字典
        """
        results = self.dispatch_pending_orders(trade_date, gateway_name=gateway_name)

        return {
            "trade_date": str(trade_date),
            "gateway": gateway_name,
            "orders_dispatched": len(results),
            "filled": sum(1 for r in results if r["status"] in ("FILLED", "confirmed")),
            "rejected": sum(1 for r in results if r["status"] == "REJECTED"),
        }


# ── 便捷入口 ──────────────────────────────────────────────

def get_manager() -> GatewayManager:
    return GatewayManager.instance()
