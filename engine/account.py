"""账务核心 — 回测引擎与实盘引擎共用的唯一资金/持仓/费用实现。

成交记录 dict 严格对齐 backtest/runner.py 的 trades 键
(date/code/name/action/price/shares/amount/commission/pnl/pnl_pct)，
使 backtest.metrics.compute_metrics 与 backtest.reporter.generate_all_reports 零改动可用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from utils.logger import get_logger

logger = get_logger("engine.account")

LOT_SIZE = 100  # A 股一手


@dataclass
class CostConfig:
    """费率配置（与 runner.py 口径一致：佣金双边，印花税仅卖出）。"""

    open_commission: float = 0.0003
    close_commission: float = 0.0003
    close_tax: float = 0.001
    min_commission: float = 0.0


@dataclass
class PositionState:
    """单只持仓状态。"""

    total_amount: int = 0
    closeable_amount: int = 0
    avg_cost: float = 0.0
    last_buy_date: date | None = None


@dataclass
class Account:
    """现金 + 持仓账本。code 一律为 6 位股票代码。"""

    initial_cash: float
    cost: CostConfig = field(default_factory=CostConfig)
    t_plus_1: bool = True
    cash: float = field(init=False)
    positions: dict[str, PositionState] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.cash = self.initial_cash

    # ── 日初 ─────────────────────────────────────────────

    def settle_new_day(self, td: date) -> None:
        """新交易日开始：T+1 解锁昨日买入。"""
        del td
        for pos in self.positions.values():
            pos.closeable_amount = pos.total_amount

    # ── 成交 ─────────────────────────────────────────────

    def buy(self, code: str, shares: int, price: float, dt: date,
            name: str = "", reason: str = "") -> dict | None:
        """买入。shares 向下取整到 100 股；现金（含佣金）不足或不足一手返回 None。"""
        shares = int(shares // LOT_SIZE) * LOT_SIZE
        if shares < LOT_SIZE or price <= 0:
            return None
        commission = max(shares * price * self.cost.open_commission, self.cost.min_commission)
        total_cost = shares * price + commission
        if total_cost > self.cash:
            return None

        self.cash -= total_cost
        pos = self.positions.get(code)
        if pos is None:
            pos = PositionState()
            self.positions[code] = pos
        # 加权均价（不含费用，沿 runner.py avg_cost=price 口径）
        prev_amount = pos.total_amount
        pos.avg_cost = (
            (pos.avg_cost * prev_amount + price * shares) / (prev_amount + shares)
            if prev_amount + shares else price
        )
        pos.total_amount += shares
        if not self.t_plus_1:
            pos.closeable_amount += shares
        pos.last_buy_date = dt

        return {
            "date": dt,
            "code": code,
            "name": name or code,
            "action": "买入",
            "price": round(price, 3),
            "shares": shares,
            "amount": round(total_cost, 2),
            "commission": round(commission, 2),
            "pnl": 0.0,
            "pnl_pct": 0.0,
            "reason": reason,
        }

    def sell(self, code: str, shares: int, price: float, dt: date,
             name: str = "", reason: str = "") -> dict | None:
        """卖出。上限为可卖数量（T+1）；shares<=0 或无持仓返回 None。"""
        pos = self.positions.get(code)
        if pos is None or price <= 0:
            return None
        shares = min(int(shares), pos.closeable_amount)
        if shares <= 0:
            return None

        gross = shares * price
        fee = max(gross * self.cost.close_commission, self.cost.min_commission) + gross * self.cost.close_tax
        proceeds = gross - fee
        pnl = (price - pos.avg_cost) * shares - fee
        pnl_pct = (price - pos.avg_cost) / pos.avg_cost * 100 if pos.avg_cost else 0.0

        self.cash += proceeds
        pos.total_amount -= shares
        pos.closeable_amount -= shares
        if pos.total_amount <= 0:
            del self.positions[code]

        return {
            "date": dt,
            "code": code,
            "name": name or code,
            "action": "卖出",
            "price": round(price, 3),
            "shares": shares,
            "amount": round(proceeds, 2),
            "commission": round(fee, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "reason": reason,
        }

    # ── 估值 ─────────────────────────────────────────────

    def position_value(self, price_map: dict[str, float]) -> float:
        """持仓市值；缺价的用 avg_cost 兜底（沿 runner.py:243 口径）。"""
        return sum(
            pos.total_amount * price_map.get(code, pos.avg_cost)
            for code, pos in self.positions.items()
        )

    def total_value(self, price_map: dict[str, float]) -> float:
        return self.cash + self.position_value(price_map)

    # ── 持久化 ────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "initial_cash": self.initial_cash,
            "cash": self.cash,
            "t_plus_1": self.t_plus_1,
            "cost": {
                "open_commission": self.cost.open_commission,
                "close_commission": self.cost.close_commission,
                "close_tax": self.cost.close_tax,
                "min_commission": self.cost.min_commission,
            },
            "positions": {
                code: {
                    "total_amount": p.total_amount,
                    "closeable_amount": p.closeable_amount,
                    "avg_cost": p.avg_cost,
                    "last_buy_date": p.last_buy_date.isoformat() if p.last_buy_date else None,
                }
                for code, p in self.positions.items()
            },
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Account":
        acct = cls(
            initial_cash=d["initial_cash"],
            cost=CostConfig(**d.get("cost", {})),
            t_plus_1=d.get("t_plus_1", True),
        )
        acct.cash = d["cash"]
        for code, p in d.get("positions", {}).items():
            acct.positions[code] = PositionState(
                total_amount=p["total_amount"],
                closeable_amount=p["closeable_amount"],
                avg_cost=p["avg_cost"],
                last_buy_date=date.fromisoformat(p["last_buy_date"]) if p.get("last_buy_date") else None,
            )
        return acct

    def copy(self) -> "Account":
        return Account.from_dict(self.to_dict())

    def to_json(self) -> str:
        import json
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, raw: str) -> "Account":
        import json
        return cls.from_dict(json.loads(raw))
