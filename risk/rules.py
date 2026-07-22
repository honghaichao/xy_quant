"""风控规则引擎 — 独立的组合风控计算模块。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from utils.logger import get_logger

logger = get_logger("risk_engine")


@dataclass
class RiskLimits:
    """Risk control limits configuration."""

    # Stop loss
    fixed_stop_loss_pct: float = 0.05
    trailing_stop: bool = True
    trailing_stop_pct: float = 0.03

    # Take profit
    fixed_take_profit_pct: float = 0.15

    # Position sizing
    max_single_position_pct: float = 0.30
    max_total_positions: int = 10
    max_industry_concentration: float = 0.40

    # Portfolio
    max_drawdown_pct: float = 0.20
    daily_loss_limit_pct: float = 0.05

    # VaR
    var_confidence: float = 0.95
    var_horizon_days: int = 1


class RiskEngine:
    """Portfolio-level risk management engine."""

    def __init__(self, limits: RiskLimits | None = None, config_path: str | None = None):
        self.limits = limits or RiskLimits()

    # ── 止损止盈 ───────────────────────────────────────────────

    def check_stop_loss(self, entry_price: float, current_price: float) -> tuple[bool, str]:
        """Check if a position has hit stop loss.

        Returns (triggered, reason).
        """
        pnl_pct = (current_price - entry_price) / entry_price
        if pnl_pct <= -self.limits.fixed_stop_loss_pct:
            return True, f"固定止损触发: {pnl_pct*100:.1f}% <= -{self.limits.fixed_stop_loss_pct*100:.0f}%"
        return False, ""

    def check_take_profit(self, entry_price: float, current_price: float) -> tuple[bool, str]:
        """Check if a position has hit take profit."""
        pnl_pct = (current_price - entry_price) / entry_price
        if pnl_pct >= self.limits.fixed_take_profit_pct:
            return True, f"止盈触发: {pnl_pct*100:.1f}% >= {self.limits.fixed_take_profit_pct*100:.0f}%"
        return False, ""

    def trailing_stop_price(self, price_series: pd.Series) -> pd.Series:
        """Compute trailing stop prices from a price series."""
        peak = price_series.cummax()
        return peak * (1 - self.limits.trailing_stop_pct)

    def time_stop(self, entry_date: date, current_date: date, max_days: int = 20) -> bool:
        """Time-based stop: exit if held beyond max_days without profit."""
        return (current_date - entry_date).days > max_days

    # ── 仓位管理 ───────────────────────────────────────────────

    def calculate_position_size(
        self,
        method: str,
        price: float,
        capital: float,
        win_rate: float | None = None,
        avg_win: float | None = None,
        avg_loss: float | None = None,
    ) -> int:
        """Calculate recommended position size in shares.

        Methods: 'equal_weight', 'kelly', 'fixed_pct'
        """
        if method == "kelly" and win_rate is not None and avg_win is not None and avg_loss is not None:
            fraction = self._kelly_criterion(win_rate, avg_win, avg_loss)
            fraction = min(fraction, self.limits.max_single_position_pct)
        elif method == "equal_weight":
            fraction = min(1.0 / max(self.limits.max_total_positions, 1), self.limits.max_single_position_pct)
        else:
            fraction = self.limits.max_single_position_pct

        allocation = capital * fraction
        size = int(allocation / price / 100) * 100  # round to 100-share lots
        return max(size, 100)

    def _kelly_criterion(self, win_rate: float, avg_win: float, avg_loss: float) -> float:
        """Kelly fraction = W - (1-W)/R where R = avg_win/avg_loss."""
        if avg_loss == 0:
            return min(win_rate, self.limits.max_single_position_pct)
        r = avg_win / abs(avg_loss)
        fraction = win_rate - (1 - win_rate) / r
        return max(0.0, min(fraction, self.limits.max_single_position_pct))

    # ── VaR / CVaR ─────────────────────────────────────────────

    def calculate_var(self, returns: pd.Series | np.ndarray, confidence: float | None = None) -> float:
        """Historical Value at Risk."""
        conf = confidence or self.limits.var_confidence
        if isinstance(returns, pd.Series):
            returns = returns.dropna().values
        return float(np.percentile(returns, (1 - conf) * 100))

    def calculate_cvar(self, returns: pd.Series | np.ndarray, confidence: float | None = None) -> float:
        """Conditional Value at Risk (expected shortfall)."""
        conf = confidence or self.limits.var_confidence
        if isinstance(returns, pd.Series):
            returns = returns.dropna().values
        var = self.calculate_var(returns, conf)
        tail = returns[returns <= var]
        return float(tail.mean()) if len(tail) > 0 else var

    def max_drawdown(self, equity_curve: pd.Series) -> tuple[float, int]:
        """Calculate max drawdown and duration (in days)."""
        cummax = equity_curve.cummax()
        drawdowns = (equity_curve - cummax) / cummax
        max_dd = float(drawdowns.min())
        # Duration: longest period under water
        underwater = drawdowns < 0
        if not underwater.any():
            return 0.0, 0
        dd_periods = underwater.astype(int).groupby((~underwater).cumsum()).sum()
        max_duration = int(dd_periods.max()) if not dd_periods.empty else 0
        return max_dd, max_duration

    # ── 组合风控检查 ───────────────────────────────────────────

    def check_portfolio_limits(
        self,
        positions: dict[str, dict[str, Any]],
        total_capital: float,
    ) -> list[str]:
        """Check portfolio-level risk limits. Returns list of violation messages."""
        violations: list[str] = []

        # Position concentration
        for code, pos in positions.items():
            pos_value = pos.get("current_value", 0)
            pct = pos_value / total_capital if total_capital > 0 else 0
            if pct > self.limits.max_single_position_pct:
                violations.append(
                    f"单仓超标: {code} {pct*100:.1f}% > {self.limits.max_single_position_pct*100:.0f}%"
                )

        # Total positions
        if len(positions) > self.limits.max_total_positions:
            violations.append(
                f"持仓数量超标: {len(positions)} > {self.limits.max_total_positions}"
            )

        # Top 3 concentration
        values = sorted(
            [p.get("current_value", 0) for p in positions.values()], reverse=True
        )
        if len(values) >= 3 and total_capital > 0:
            top3_pct = sum(values[:3]) / total_capital
            if top3_pct > self.limits.max_industry_concentration:
                violations.append(f"Top3集中度超标: {top3_pct*100:.1f}%")

        return violations

    def check_drawdown_limit(self, equity_curve: pd.Series) -> tuple[bool, str]:
        """Check if portfolio drawdown exceeds limit."""
        max_dd, duration = self.max_drawdown(equity_curve)
        if abs(max_dd) >= self.limits.max_drawdown_pct:
            return True, f"最大回撤超标: {max_dd*100:.2f}% > {self.limits.max_drawdown_pct*100:.0f}%"
        return False, ""

    def run_portfolio_risk_check(
        self,
        positions: dict[str, dict[str, Any]],
        total_capital: float,
        returns: pd.Series | None = None,
        equity_curve: pd.Series | None = None,
    ) -> dict[str, Any]:
        """Complete portfolio risk check. Returns risk report dict."""
        report: dict[str, Any] = {
            "violations": self.check_portfolio_limits(positions, total_capital),
            "stop_loss_triggers": [],
            "take_profit_triggers": [],
            "vaR_95": None,
            "cvaR_95": None,
            "max_drawdown": None,
            "max_drawdown_duration": None,
        }

        # Check stop loss / take profit for each position
        for code, pos in positions.items():
            entry = pos.get("entry_price")
            current = pos.get("current_price")
            if entry and current:
                triggered, reason = self.check_stop_loss(entry, current)
                if triggered:
                    report["stop_loss_triggers"].append({"code": code, "reason": reason})
                triggered, reason = self.check_take_profit(entry, current)
                if triggered:
                    report["take_profit_triggers"].append({"code": code, "reason": reason})

        # VaR
        if returns is not None and len(returns) > 0:
            report["vaR_95"] = self.calculate_var(returns)
            report["cvaR_95"] = self.calculate_cvar(returns)

        # Drawdown
        if equity_curve is not None and len(equity_curve) > 0:
            report["max_drawdown"], report["max_drawdown_duration"] = self.max_drawdown(equity_curve)

        return report
