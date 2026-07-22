"""
Portfolio Strategy Base Class

Portfolio mode strategy where ONE Cerebro instance manages ALL stocks in a SINGLE account.

Key Difference from single-stock strategy:
- Single: One stock per Cerebro, one strategy instance
- Portfolio: All stocks in ONE Cerebro, strategy walks ALL stocks daily

Usage:
    class MyPortfolioStrategy(PortfolioStrategy):
        def calculate_score(self, data) -> float:
            return score
"""

from __future__ import annotations

import backtrader as bt
import numpy as np
from datetime import datetime
from typing import Any


class PortfolioStrategy(bt.Strategy):
    """
    Portfolio Strategy Base Class — one Cerebro instance manages all stocks
    in a single account. The strategy walks ALL stocks daily.
    """

    params = (
        ("threshold", 8.0),
        ("stop_loss_pct", 0.05),
        ("min_data_points", 60),
        ("max_positions", 10),
        ("debug_mode", False),
    )

    def __init__(self, **kwargs: Any) -> None:
        self.daily_values: list[float] = [self.broker.getvalue()]
        self.daily_dates: list[datetime] = []
        self.daily_signals: list[dict[str, Any]] = []
        self._current_date: datetime | None = None
        self.pending_orders: dict[str, Any] = {}

    def calculate_score(self, data: Any) -> float:
        """Calculate buy score for a stock. Override in subclass."""
        raise NotImplementedError("Subclass must implement calculate_score(data)")

    def calculate_s1_score(self, data: Any) -> float:
        """Calculate S1 sell score. >=10 = full sell, >=5 = half sell."""
        return 0.0

    def next(self) -> None:  # type: ignore[override]
        self._current_date = (
            self.datas[0].datetime.datetime(0)
            if self.datas and len(self.datas) > 0
            else None
        )
        signals: list[tuple[str, str, float]] = []
        for data in self.datas:
            position = self.getposition(data)
            if position.size > 0:
                s1 = self.calculate_s1_score(data)
                if s1 > 10:
                    signals.append(("sell", data._name, s1))
                elif s1 > 5:
                    signals.append(("sell_half", data._name, s1))
            else:
                score = self.calculate_score(data)
                if score >= self.params.threshold:
                    signals.append(("buy", data._name, score))
        self._execute_signals(signals)
        self.daily_values.append(self.broker.getvalue())
        self.daily_dates.append(self._current_date)
        self.daily_signals.append({"date": self._current_date, "signals": signals})

    def _execute_signals(self, signals: list[tuple[str, str, float]]) -> None:
        if not signals:
            return
        cash = self.broker.getcash()
        for action, code, score in signals:
            data = self._get_data_by_name(code)
            if data is None:
                continue
            if action == "buy":
                pos = self.getposition(data)
                if pos.size > 0:
                    continue
                price = data.close[0]
                if price <= 0:
                    continue
                size = int(cash * 0.95 / price / 100) * 100
                if size >= 100:
                    self.buy(data=data, size=size)
            elif action == "sell":
                pos = self.getposition(data)
                if pos.size > 0:
                    self.close(data=data)
            elif action == "sell_half":
                pos = self.getposition(data)
                if pos.size > 0:
                    half = pos.size // 2
                    if half > 0:
                        self.close(data=data, size=half)

    def _get_data_by_name(self, name: str) -> Any:
        for data in self.datas:
            if data._name == name:
                return data
        return None

    def get_portfolio_value(self) -> list[float]:
        return self.daily_values

    def get_portfolio_metrics(self) -> dict[str, Any]:
        if len(self.daily_values) < 2:
            return {
                "total_return": 0.0, "annualized_return": 0.0,
                "max_drawdown": 0.0, "sharpe_ratio": 0.0,
            }
        import numpy as np
        values = np.array(self.daily_values)
        init, final = values[0], values[-1]
        total_return = (final - init) / init * 100
        n = len(values)
        ann = ((final / init) ** (252 / n) - 1) * 100 if n > 1 else 0.0
        cummax = np.maximum.accumulate(values)
        dd = np.min((values - cummax) / cummax * 100)
        daily_r = np.diff(values) / values[:-1]
        daily_r = np.where(np.isfinite(daily_r), daily_r, 0.0)
        sr = (np.mean(daily_r) - 0.03 / 252) / np.std(daily_r) * np.sqrt(252) if np.std(daily_r) > 0 else 0.0
        return {
            "total_return": total_return, "annualized_return": ann,
            "max_drawdown": dd, "sharpe_ratio": sr,
            "initial_value": init, "final_value": final, "trading_days": n - 1,
        }
