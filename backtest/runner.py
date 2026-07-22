"""
回测运行器 — 策略无关的核心回测循环。

职责：
  1. 加载日线 + 分钟线数据
  2. 逐日循环：选股 → 用分钟价执行 → 用收盘价估值
  3. 收集 trades + equity_curve
  4. 计算指标

使用方式：
    from backtest.runner import BacktestRunner
    from strategies.caimadama import CaiMaDamaStrategy

    strategy = CaiMaDamaStrategy(top_n=5)
    strategy.load_context_data(start, end)

    runner = BacktestRunner(strategy, start=date(2026,1,1), end=date(2026,7,14))
    result = runner.run()
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from backtest.execution import (
    load_trade_dates,
    load_full_daily_bars,
    load_minute_first_bar,
    load_daily_open_fallback,
    load_benchmark,
)
from backtest.metrics import compute_metrics
from utils.logger import get_logger

logger = get_logger("backtest.runner")


class BacktestRunner:
    """策略无关的回测运行器。

    策略只需提供：
      - strategy_name: str
      - select_stocks(ctx) → list[str]
      - name_map() → dict[str, str]
    """

    def __init__(
        self,
        strategy: Any,  # 任何有 select_stocks() + name_map() + strategy_name 的对象
        start: date,
        end: date,
        initial_cash: float = 500_000.0,
        commission: float = 0.0003,
        stamp_duty: float = 0.001,
        benchmark_code: str = "000300.SH",
    ):
        self.strategy = strategy
        self.start = start
        self.end = end
        self.initial_cash = initial_cash
        self.commission = commission
        self.stamp_duty = stamp_duty
        self.benchmark_code = benchmark_code

        # 运行时状态
        self.cash = initial_cash
        self.positions: dict[str, dict] = {}  # code → {shares, avg_cost}
        self.equity_curve: list[dict] = []
        self.trades: list[dict] = []
        self.daily_positions: list[dict] = []

        self._name_map: dict[str, str] = {}

    def run(self) -> dict:
        """执行回测。返回完整结果 dict。"""
        name_map = getattr(self.strategy, "name_map", lambda: {})()
        self._name_map = name_map

        # ── 加载数据 ──
        logger.info("加载交易日列表...")
        dates = load_trade_dates(self.start, self.end)
        logger.info(f"共 {len(dates)} 个交易日")

        logger.info("加载全量日线...")
        all_bars = load_full_daily_bars(self.start, self.end)
        logger.info(f"日线: {len(all_bars)} 行")

        # 按日期分组
        bars_by_date: dict[date, pd.DataFrame] = {}
        for d, group in all_bars.groupby("trade_date"):
            bars_by_date[d.date()] = group

        logger.info(f"开始回测: {self.start} ~ {self.end}")

        with Progress(
            SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
            BarColumn(), TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        ) as progress:
            task = progress.add_task("[cyan]回测中...", total=len(dates))

            for i, td in enumerate(dates):
                progress.update(task, completed=i + 1)

                day_df = bars_by_date.get(td)
                if day_df is None or day_df.empty:
                    self._record_equity(td, day_df)
                    continue

                # ── 选股（策略自己决定用哪天数据）──
                # 传给策略 current_date + 全部 bars_by_date，策略自己判断取哪天
                choice = self.strategy.select_stocks({
                    "current_date": td,
                    "bars_by_date": bars_by_date,  # 策略可取任意历史日期的数据
                    "all_dates": dates,
                    "current_index": i,
                    "current_positions": self.positions,
                })

                # ── 执行价（策略指定的执行时间）──
                # 策略可以定义 execution_time: "open" 或 "minute_0931"
                need_prices = set(self.positions.keys()) | set(choice)
                exec_time = getattr(self.strategy, "execution_time", "minute_0931")
                if exec_time == "open":
                    exec_prices = self._load_daily_open_prices(list(need_prices), td)
                else:
                    exec_prices = self._load_execution_prices(list(need_prices), td)

                # ── 卖出不在选股池的 ──
                for code in list(self.positions):
                    if code not in choice:
                        price = exec_prices.get(code)
                        if price is None or price <= 0:
                            continue
                        pos = self.positions[code]
                        shares = pos["shares"]
                        gross = shares * price
                        sell_commission = gross * (self.commission + self.stamp_duty)
                        proceeds = gross - sell_commission
                        sell_pnl = (price - pos["avg_cost"]) * shares - sell_commission
                        self.cash += proceeds
                        self.trades.append({
                            "date": td,
                            "code": code,
                            "name": name_map.get(code, code),
                            "action": "卖出",
                            "price": round(price, 3),
                            "shares": shares,
                            "amount": round(proceeds, 2),
                            "commission": round(sell_commission, 2),
                            "pnl": round(sell_pnl, 2),
                            "pnl_pct": round((price - pos["avg_cost"]) / pos["avg_cost"] * 100, 2) if pos["avg_cost"] else 0,
                        })
                        del self.positions[code]

                # ── 买入 ──
                to_buy = [c for c in choice if c not in self.positions]
                if to_buy:
                    n_target = self._get_strategy_top_n()
                    position_value = sum(
                        p["shares"] * exec_prices.get(c, p["avg_cost"])
                        for c, p in self.positions.items()
                    )
                    total_equity = self.cash + position_value
                    per_stock_value = total_equity / max(n_target, 1)

                    for code in to_buy:
                        price = exec_prices.get(code)
                        if price is None or price <= 0:
                            continue
                        max_shares = int(self.cash * 0.95 / price / 100) * 100
                        target_shares = int(per_stock_value / price / 100) * 100
                        shares = min(target_shares, max_shares)
                        if shares < 100:
                            continue
                        cost = shares * price * (1 + self.commission)
                        if cost > self.cash:
                            continue
                        self.cash -= cost
                        self.positions[code] = {"shares": shares, "avg_cost": price}
                        self.trades.append({
                            "date": td,
                            "code": code,
                            "name": name_map.get(code, code),
                            "action": "买入",
                            "price": round(price, 3),
                            "shares": shares,
                            "amount": round(cost, 2),
                            "commission": round(shares * price * self.commission, 2),
                            "pnl": 0.0,
                            "pnl_pct": 0.0,
                        })

                self._record_equity(td, day_df)

        # ── 计算指标 ──
        final_value = self.equity_curve[-1]["total"] if self.equity_curve else self.initial_cash
        metrics = compute_metrics(self.equity_curve, self.trades, self.initial_cash)

        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "strategy_name": getattr(self.strategy, "strategy_name", "unknown"),
            "initial_cash": self.initial_cash,
            "final_value": round(final_value, 2),
            "metrics": metrics,
            "trades": self.trades,
            "equity_curve": self.equity_curve,
            "daily_positions": self.daily_positions,
        }

    def _get_strategy_top_n(self) -> int:
        """尝试从策略对象读取 top_n，取不到默认 5"""
        return getattr(self.strategy, "top_n", 5)

    def _load_daily_open_prices(self, codes: list[str], td: date) -> dict[str, float]:
        """用日线 open 做执行价"""
        return load_daily_open_fallback(codes, td)

    def _load_execution_prices(self, codes: list[str], td: date) -> dict[str, float]:
        """加载执行价：分钟线 9:31 → 日线 open → 持仓均价"""
        minute = load_minute_first_bar(codes, td)
        missing = [c for c in codes if c not in minute]
        daily = load_daily_open_fallback(missing, td) if missing else {}
        result = {**daily, **minute}
        for code in codes:
            if code not in result and code in self.positions:
                result[code] = self.positions[code]["avg_cost"]
        return result

    def _record_equity(self, td: date, day_df: pd.DataFrame | None = None):
        """用当日收盘价估值"""
        close_prices = {}
        if day_df is not None:
            for _, row in day_df.iterrows():
                close_prices[row["code"]] = float(row["close"]) if pd.notna(row["close"]) else 0.0
        position_value = sum(
            p["shares"] * close_prices.get(c, p["avg_cost"])
            for c, p in self.positions.items()
        )
        total = self.cash + position_value
        self.equity_curve.append({
            "date": td,
            "cash": round(self.cash, 2),
            "position_value": round(position_value, 2),
            "total": round(total, 2),
            "total_return": total / self.initial_cash - 1,
            "positions": len(self.positions),
        })
        self.daily_positions.append({
            "date": td,
            "codes": ",".join(self.positions.keys()),
            "count": len(self.positions),
        })
