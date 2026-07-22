"""
回测指标计算 — 统一所有策略的绩效指标。

产出：
  total_return, annual_return, sharpe_ratio, sortino_ratio, calmar_ratio,
  max_drawdown, annual_volatility, win_rate, profit_loss_ratio,
  total_trades, num_buys, num_sells, winning_trades, losing_trades,
  monthly_returns

所有策略公用此模块，保证指标计算逻辑完全一致。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

RISK_FREE_RATE = 0.02
TRADING_DAYS_PER_YEAR = 252


def compute_metrics(
    equity_curve: list[dict],
    trades: list[dict],
    initial_cash: float,
) -> dict:
    """从权益曲线和交易记录计算全部绩效指标。

    Args:
        equity_curve: [{"date", "total", "cash", "position_value", "total_return"}, ...]
        trades: [{"date", "code", "action", "price", "shares", "amount", "commission", "pnl"}, ...]
        initial_cash: 初始资金

    Returns:
        dict with all metrics
    """
    if not equity_curve:
        return {"error": "no_data"}

    df = pd.DataFrame(equity_curve)
    df["daily_return"] = df["total"].pct_change().fillna(0)

    final_total = df["total"].iloc[-1]
    total_return = final_total / initial_cash - 1

    n_days = len(df)
    annual_return = (1 + total_return) ** (252 / max(n_days, 1)) - 1

    # ── Max drawdown ──
    peak = df["total"].cummax()
    drawdown_series = (df["total"] - peak) / peak
    max_dd = drawdown_series.min()

    # ── Sharpe ──
    daily_rf = RISK_FREE_RATE / TRADING_DAYS_PER_YEAR
    excess = df["daily_return"] - daily_rf
    std_daily = excess.std(ddof=1)
    sharpe = excess.mean() / std_daily * np.sqrt(TRADING_DAYS_PER_YEAR) if std_daily > 0 else 0

    # ── Sortino (只用下行波动) ──
    downside = df.loc[df["daily_return"] < 0, "daily_return"]
    if len(downside) > 0:
        downside_std = downside.std(ddof=1)
        sortino = (df["daily_return"].mean() - daily_rf) / downside_std * np.sqrt(TRADING_DAYS_PER_YEAR) if downside_std > 0 else 0
    else:
        sortino = np.inf if total_return > 0 else 0

    # ── Calmar ──
    calmar = annual_return / abs(max_dd) if max_dd != 0 else 0

    # ── 年化波动率 ──
    ann_vol = std_daily * np.sqrt(TRADING_DAYS_PER_YEAR)

    # ── 交易统计 ──
    sells = [t for t in trades if t["action"] == "卖出"]
    buys = [t for t in trades if t["action"] == "买入"]
    winning = [t for t in sells if t.get("pnl", 0) > 0]
    losing = [t for t in sells if t.get("pnl", 0) <= 0]

    win_rate = len(winning) / len(sells) if sells else 0

    # ── 盈亏比 ──
    avg_win = float(np.mean([t["pnl"] for t in winning])) if winning else 0
    avg_loss = abs(float(np.mean([t["pnl"] for t in losing]))) if losing else 0
    profit_loss_ratio = abs(avg_win / avg_loss) if avg_loss > 0 else 999

    # ── 月度收益 ──
    df["month"] = pd.to_datetime(df["date"]).dt.to_period("M")
    monthly = df.groupby("month").apply(
        lambda g: g["total"].iloc[-1] / g["total"].iloc[0] - 1, include_groups=False
    )
    monthly_returns = {str(k): round(v, 6) for k, v in monthly.items()} if not monthly.empty else {}

    return {
        "total_return": round(total_return, 4),
        "annual_return": round(annual_return, 4),
        "max_drawdown": round(max_dd, 4),
        "sharpe_ratio": round(sharpe, 4),
        "sortino_ratio": round(sortino, 4),
        "calmar_ratio": round(calmar, 4),
        "annual_volatility": round(ann_vol, 4),
        "win_rate": round(win_rate, 4),
        "profit_loss_ratio": round(profit_loss_ratio, 2),
        "total_trades": len(trades),
        "num_buys": len(buys),
        "num_sells": len(sells),
        "winning_trades": len(winning),
        "losing_trades": len(losing),
        "trading_days": n_days,
        "monthly_returns": monthly_returns,
    }
