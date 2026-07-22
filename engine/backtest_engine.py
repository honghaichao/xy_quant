"""统一回测引擎 — 聚宽策略的日循环与撮合核心。

run() 返回 dict 与 backtest/runner.py:205-215 完全同形
(start/end/strategy_name/initial_cash/final_value/metrics/trades/equity_curve/daily_positions)，
直接接入 backtest.metrics.compute_metrics 与 backtest.reporter.generate_all_reports。

run_one_day() 是单日步进原语，LiveEngine 结算重放复用同一代码路径。
"""

from __future__ import annotations

from datetime import date, datetime, time as dtime
from typing import Any

import pandas as pd

from backtest.execution import (
    load_daily_open_fallback,
    load_full_daily_bars,
    load_minute_bar_at,
    load_minute_first_bar,
    load_name_map,
    load_trade_dates,
    load_universe_meta,
)
from backtest.metrics import compute_metrics
from engine.account import Account, CostConfig
from engine.api import build_namespace
from engine.clock import (
    FILL_CLOSE,
    FILL_MINUTE,
    FILL_OPEN,
    FILL_QUEUE_TO_OPEN,
    FILL_REJECT,
    ScheduledTask,
    Slot,
    parse_time,
    sort_tasks,
)
from engine.context import Context, G, Portfolio
from engine.loader import StrategyModule, load_strategy
from engine.market_data import CurrentDataView
from jq_adapter.utils import normalize_code
from utils.logger import get_logger

LOT = 100


class BacktestEngine:
    """聚宽策略回测引擎（非 Backtrader，多股组合原生支持）。"""

    def __init__(
        self,
        strategy: str,
        start: date,
        end: date,
        initial_cash: float = 500_000.0,
        cost: CostConfig | None = None,
        benchmark_code: str = "000300.SH",
        t_plus_1: bool = True,
        cash_reserve: float = 0.05,
        strategy_name: str | None = None,
        run_params: dict | None = None,
        bootstrap_first_day: bool = False,
    ):
        """bootstrap_first_day: 首日盘前视图用首日自身 bar 充当 T-1（复刻旧 runner 首日
        取当日数据的口径，仅平价验证用；默认 False = 严格 T-1 无未来函数）。"""
        self.strategy_path = strategy
        self.start = start
        self.end = end
        self.benchmark_code = benchmark_code
        self.cash_reserve = cash_reserve
        self.strategy_name = strategy_name or strategy
        self.run_params = run_params or {}
        self.bootstrap_first_day = bootstrap_first_day

        self.logger = get_logger(f"engine.{self.strategy_name}")
        self.account = Account(initial_cash=initial_cash,
                               cost=cost or CostConfig(), t_plus_1=t_plus_1)
        self.portfolio = Portfolio(self.account)
        self.g = G()
        self.context = Context(self.portfolio, run_params=self.run_params)

        # 撮合状态
        self.slippage_fixed = 0.0
        self.slippage_pct = 0.0
        self.price_overrides: dict[str, float] = {}   # confirm 模式人工回填价（LiveEngine 注入）
        self.tasks: list[ScheduledTask] = []
        self._task_seq = 0
        self._pending_orders: list[tuple[str, str, float]] = []   # 盘前排队
        self._slot: Slot = parse_time("before_open")
        self._slot_prices: dict[str, float] = {}
        self._current_td: date | None = None
        self._prev_trade_date: date | None = None
        self._bars_today: pd.DataFrame | None = None
        self._bars_prev: pd.DataFrame | None = None
        self._fund_flow_prev: pd.DataFrame | None = None
        self._reject_orders = False

        # 结果
        self.trades: list[dict] = []
        self.equity_curve: list[dict] = []
        self.daily_positions: list[dict] = []

        # 数据缓存
        self._meta: pd.DataFrame | None = None
        self._name_map: dict[str, str] = {}

        self.strategy: StrategyModule | None = None

    # ══════════════════════════════════════════════════════════
    # 引擎接口（供 engine/api.py 注入的函数回调）
    # ══════════════════════════════════════════════════════════

    def register_task(self, task: ScheduledTask) -> None:
        task.seq = self._task_seq
        self._task_seq += 1
        self.tasks.append(task)

    def set_benchmark_code(self, security: str) -> None:
        self.benchmark_code = normalize_code(security)

    def current_data_view(self) -> CurrentDataView:
        return CurrentDataView(
            bars_today=self._bars_today, bars_prev=self._bars_prev,
            meta=self._meta, slot=self._slot, slot_prices=self._slot_prices,
            fund_flow_prev=self._fund_flow_prev,
        )

    def submit_order(self, code: str, kind: str, amount: float) -> dict | None:
        """下单入口。盘前槽排队；交易时段按当前槽价格立即撮合；收盘后拒单。"""
        if self._reject_orders or self._slot.fill_kind == FILL_REJECT:
            self.logger.warning(f"[{self._current_td}] 收盘后下单被拒绝: {code} {kind} {amount}")
            return None
        if self._slot.fill_kind == FILL_QUEUE_TO_OPEN:
            self._pending_orders.append((code, kind, amount))
            return None
        return self._execute_order(code, kind, amount)

    # ══════════════════════════════════════════════════════════
    # 撮合
    # ══════════════════════════════════════════════════════════

    def _fill_price(self, code: str, side: str) -> float | None:
        """当前槽成交价 + 滑点。人工确认价（confirm 模式）优先。缺价按槽语义回落，仍缺返回 None。"""
        if code in self.price_overrides:
            return self.price_overrides[code]
        price = self._slot_prices.get(code)
        if price is None:
            price = self._fetch_slot_price(code)
        if price is None or price <= 0:
            return None
        if side == "buy":
            return price * (1 + self.slippage_pct / 2) + self.slippage_fixed / 2
        return price * (1 - self.slippage_pct / 2) - self.slippage_fixed / 2

    def _fetch_slot_price(self, code: str) -> float | None:
        """单只懒加载当前槽价格（并入 _slot_prices 缓存）。"""
        td = self._current_td
        assert td is not None
        kind = self._slot.fill_kind
        price: float | None = None
        if kind == FILL_OPEN:
            got = load_minute_first_bar([code], td)
            if code not in got:
                got = load_daily_open_fallback([code], td)
            price = got.get(code)
            if price is None and code in self.account.positions:
                price = self.account.positions[code].avg_cost   # runner.py:233 口径
        elif kind == FILL_MINUTE:
            price = load_minute_bar_at([code], td, self._slot.hhmm).get(code)
        elif kind == FILL_CLOSE:
            price = self._close_price(code)
        if price is not None:
            self._slot_prices[code] = price
        return price

    def _close_price(self, code: str) -> float | None:
        if self._bars_today is None:
            return None
        rows = self._bars_today[self._bars_today["code"] == code]
        if rows.empty or pd.isna(rows.iloc[0]["close"]):
            return None
        return float(rows.iloc[0]["close"])

    def _execute_order(self, code: str, kind: str, amount: float) -> dict | None:
        pos = self.account.positions.get(code)
        held = pos.total_amount if pos else 0

        # 意向股数（正=买，负=卖）
        if kind == "amount":
            delta = int(amount)
        elif kind == "target_amount":
            delta = int(amount) - held
        elif kind in ("value", "target_value"):
            side_probe = "buy" if (kind == "value" and amount >= 0) else None
            # 需要价格换算股数
            probe_price = self._fill_price(code, side_probe or "sell")
            if probe_price is None:
                self.logger.warning(f"[{self._current_td}] {code} 无成交价，订单跳过")
                return None
            if kind == "value":
                delta = int(amount / probe_price / LOT) * LOT
            else:
                current_value = held * probe_price
                diff = amount - current_value
                if diff >= 0:
                    delta = int(diff / probe_price / LOT) * LOT
                else:
                    delta = -min(int(-diff / probe_price / LOT) * LOT, held) if amount > 0 else -held
        else:
            raise ValueError(f"未知订单类型: {kind}")

        if delta == 0:
            return None
        td = self._current_td
        name = self._name_map.get(code, code)

        if delta > 0:
            price = self._fill_price(code, "buy")
            if price is None:
                return None
            # 现金预留口径对齐 runner.py:176（cash*0.95 上限）
            max_shares = int(self.account.cash * (1 - self.cash_reserve) / price / LOT) * LOT
            shares = min(delta, max_shares)
            trade = self.account.buy(code, shares, price, td, name=name)
        else:
            price = self._fill_price(code, "sell")
            if price is None:
                return None
            trade = self.account.sell(code, -delta, price, td, name=name)

        if trade:
            self.trades.append(trade)
            self.portfolio.update_prices({code: price})
        return trade

    def _flush_pending(self) -> None:
        """开盘批：按提交顺序撮合盘前排队订单。"""
        pending, self._pending_orders = self._pending_orders, []
        for code, kind, amount in pending:
            self._execute_order(code, kind, amount)

    # ══════════════════════════════════════════════════════════
    # 日循环
    # ══════════════════════════════════════════════════════════

    def _enter_slot(self, slot: Slot) -> None:
        """切换时间槽：重置槽价格缓存，预取持仓价格并刷新 portfolio。"""
        self._slot = slot
        self._slot_prices = {}
        td = self._current_td
        held = list(self.account.positions.keys())
        if not held or td is None:
            return
        if slot.fill_kind == FILL_OPEN:
            got = load_minute_first_bar(held, td)
            missing = [c for c in held if c not in got]
            if missing:
                got.update(load_daily_open_fallback(missing, td))
            for c in held:
                if c not in got:
                    got[c] = self.account.positions[c].avg_cost
            self._slot_prices.update(got)
        elif slot.fill_kind == FILL_MINUTE:
            self._slot_prices.update(load_minute_bar_at(held, td, slot.hhmm))
        elif slot.fill_kind == FILL_CLOSE:
            for c in held:
                p = self._close_price(c)
                if p is not None:
                    self._slot_prices[c] = p
        self.portfolio.update_prices(self._slot_prices)

    def _should_fire(self, task: ScheduledTask, td: date) -> bool:
        if task.freq == "weekly":
            return td.weekday() == task.weekday
        if task.freq == "monthly":
            return td.day >= (task.monthday or 1) and (
                self._prev_trade_date is None
                or self._prev_trade_date.month != td.month
                or self._prev_trade_date.day < (task.monthday or 1) <= td.day
            )
        return True

    def _run_slot_tasks(self, tasks: list[ScheduledTask], td: date) -> None:
        for task in tasks:
            if not self._should_fire(task, td):
                continue
            try:
                task.func(self.context)
            except Exception:
                self.logger.exception(f"[{td}] 任务 {task.func.__name__} 异常")

    def run_one_day(self, td: date, bars_today: pd.DataFrame | None,
                    bars_prev: pd.DataFrame | None,
                    fund_flow_prev: pd.DataFrame | None = None) -> None:
        """单日步进（回测与实盘结算共用）。"""
        self._current_td = td
        self._bars_today = bars_today
        self._bars_prev = bars_prev
        self._fund_flow_prev = fund_flow_prev
        self._reject_orders = False
        self.account.settle_new_day(td)

        sorted_tasks = sort_tasks(self.tasks)
        pre_open = [t for t in sorted_tasks if t.slot.fill_kind == FILL_QUEUE_TO_OPEN]
        open_slot = [t for t in sorted_tasks if t.slot.fill_kind == FILL_OPEN]
        intraday = [t for t in sorted_tasks if t.slot.fill_kind == FILL_MINUTE]
        close_slot = [t for t in sorted_tasks if t.slot.fill_kind == FILL_CLOSE]
        after = [t for t in sorted_tasks if t.slot.fill_kind == FILL_REJECT]

        # 1) 盘前
        self._slot = parse_time("before_open")
        self._slot_prices = {}
        self.context._set_clock(datetime.combine(td, dtime(9, 0)), self._prev_trade_date or td)
        if self.strategy and self.strategy.before_trading_start:
            self.strategy.before_trading_start(self.context)
        self._run_slot_tasks(pre_open, td)

        # 2) 开盘批（先撮合盘前排队单，再跑开盘槽任务 + handle_data）
        self._enter_slot(parse_time("open"))
        self.context._set_clock(datetime.combine(td, dtime(9, 31)), self._prev_trade_date or td)
        self._flush_pending()
        self._run_slot_tasks(open_slot, td)
        if self.strategy and self.strategy.handle_data:
            self.strategy.handle_data(self.context, None)

        # 3) 盘中槽（逐槽切换价格）
        for task in intraday:
            self._enter_slot(task.slot)
            hh, mm = divmod(task.slot.minutes, 60)
            self.context._set_clock(datetime.combine(td, dtime(hh, mm)), self._prev_trade_date or td)
            self._run_slot_tasks([task], td)

        # 4) 收盘槽
        if close_slot:
            self._enter_slot(parse_time("close"))
            self.context._set_clock(datetime.combine(td, dtime(15, 0)), self._prev_trade_date or td)
            self._run_slot_tasks(close_slot, td)

        # 5) 收盘估值（口径同 runner.py:236-259）
        self._record_equity(td)

        # 6) after_trading_end（禁止下单）
        self._reject_orders = True
        self.context._set_clock(datetime.combine(td, dtime(15, 30)), self._prev_trade_date or td)
        if self.strategy and self.strategy.after_trading_end:
            self.strategy.after_trading_end(self.context)
        self._run_slot_tasks(after, td)

        self._prev_trade_date = td

    def _record_equity(self, td: date) -> None:
        close_prices: dict[str, float] = {}
        if self._bars_today is not None:
            for _, row in self._bars_today.iterrows():
                if pd.notna(row["close"]):
                    close_prices[row["code"]] = float(row["close"])
        position_value = self.account.position_value(close_prices)
        total = self.account.cash + position_value
        self.portfolio.update_prices(close_prices)
        self.equity_curve.append({
            "date": td,
            "cash": round(self.account.cash, 2),
            "position_value": round(position_value, 2),
            "total": round(total, 2),
            "total_return": total / self.account.initial_cash - 1,
            "positions": len(self.account.positions),
        })
        self.daily_positions.append({
            "date": td,
            "codes": ",".join(self.account.positions.keys()),
            "count": len(self.account.positions),
        })

    # ══════════════════════════════════════════════════════════
    # 入口
    # ══════════════════════════════════════════════════════════

    def setup(self) -> None:
        """加载策略 + 元数据（LiveEngine 也调用）。"""
        self._meta = load_universe_meta()
        self._name_map = load_name_map()
        namespace = build_namespace(self, self.context, self.g)
        self.strategy = load_strategy(self.strategy_path, namespace)
        self.strategy.initialize(self.context)
        if self.strategy.process_initialize:
            self.strategy.process_initialize(self.context)

    def run(self) -> dict[str, Any]:
        self.logger.info(f"加载交易日与全量日线: {self.start} ~ {self.end}")
        dates = load_trade_dates(self.start, self.end)
        if not dates:
            raise RuntimeError(f"区间内无交易日: {self.start} ~ {self.end}")
        bars = load_full_daily_bars(self.start, self.end)
        bars_by_date = {d: g for d, g in bars.groupby(bars["trade_date"].dt.date)}
        self.logger.info(f"共 {len(dates)} 个交易日, 日线 {len(bars)} 行")

        # 加载历史资金流（用于回测 T-1 注入）
        from backtest.execution import load_daily_money_flow
        mf = load_daily_money_flow(self.start, self.end)
        fund_flow_by_date: dict = {}
        if not mf.empty:
            mf["trade_date"] = pd.to_datetime(mf["trade_date"])
            fund_flow_by_date = {d: g for d, g in mf.groupby(mf["trade_date"].dt.date)}
            self.logger.info(f"资金流: {len(mf)} 行, {len(fund_flow_by_date)} 天")
        else:
            self.logger.info("资金流数据为空，跳过")

        self.setup()

        for i, td in enumerate(dates):
            if i == 0:
                prev = bars_by_date.get(td) if self.bootstrap_first_day else None
            else:
                prev = bars_by_date.get(dates[i - 1])
            # T-1 fund flow: use previous trading day's flow
            mf_prev = fund_flow_by_date.get(dates[i - 1]) if i > 0 and fund_flow_by_date else None
            self.run_one_day(td, bars_by_date.get(td), prev, fund_flow_prev=mf_prev)
            if (i + 1) % 20 == 0 or i == len(dates) - 1:
                eq = self.equity_curve[-1]
                self.logger.info(
                    f"[{i+1}/{len(dates)}] {td} 总值={eq['total']:,.0f} 持仓={eq['positions']}")

        if self.strategy and self.strategy.on_strategy_end:
            self.strategy.on_strategy_end(self.context)

        final_value = self.equity_curve[-1]["total"] if self.equity_curve else self.account.initial_cash
        metrics = compute_metrics(self.equity_curve, self.trades, self.account.initial_cash)
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "strategy_name": self.strategy_name,
            "initial_cash": self.account.initial_cash,
            "final_value": round(final_value, 2),
            "metrics": metrics,
            "trades": self.trades,
            "equity_curve": self.equity_curve,
            "daily_positions": self.daily_positions,
        }
