"""
实盘引擎 — 夜间结算 + 次日预演（一个进程调用完成两个周期）。

模型：每晚 23:05（数据管线 20:30-22:55 跑完）调用一次：
  1. settle: 对 [last_settled+1, latest_data_date] 每个交易日用真实数据重放 run_one_day
  2. decide: 下一交易日盘前+开盘槽预演 → order_queue pending + 飞书卡片

paper 模式：settle 按真实数据重放自动成交；confirm 模式：按 order_queue 人工回填价成交。

停机多日自动追结算（水位机制）；数据未到位自动跳过等下一晚。
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Literal

from engine.account import Account, CostConfig
from engine.backtest_engine import BacktestEngine
from engine.context import Context, G, Portfolio
from engine.clock import parse_time
from engine import persistence
from config.settings import get_trading_config
from data.api import get_trade_days
from utils.db import connect_write
from utils.logger import get_logger
from utils.stock_name import resolve_name, load_name_map

import duckdb

LATEST_BAR_CHECK = 100   # daily_bar 当日至少 100 行才算数据到位


class LiveEngine:
    def __init__(
        self,
        strategy_id: str,
        module: str,
        mode: Literal["paper", "confirm"] = "paper",
        initial_cash: float = 100_000.0,
        cost: CostConfig | None = None,
        write_positions: bool = True,
        fill_fallback: str = "market",
    ):
        self.strategy_id = strategy_id
        self.module = module
        self.mode = mode
        self.initial_cash = initial_cash
        self.cost = cost or CostConfig()
        self.write_positions = write_positions
        self.fill_fallback = fill_fallback
        self.logger = get_logger(f"live.{strategy_id}")

    # ══════════════════════════════════════════════════════════
    # 入口
    # ══════════════════════════════════════════════════════════

    def run_nightly(self, asof: date | None = None, dry_run: bool = False,
                    settle_only: bool = False, preview_only: bool = False) -> dict:
        """每晚一次：结算 → 预演。

        Returns:
            summary dict: {settled_dates, fills, nav, pending_orders, ...}
        """
        persistence.ensure_tables()
        self.logger.info(f"LiveEngine nightly: {self.strategy_id} mode={self.mode}"
                         f" dry={dry_run} settle_only={settle_only} preview_only={preview_only}")

        # 数据截至日
        latest = self._latest_data_date(asof)
        self.logger.info(f"数据截至: {latest}")

        # 恢复状态
        saved = persistence.load_latest_snapshot(self.strategy_id)
        account, g_obj, last_settled = self._restore(saved)

        pending = self._pending_settle_dates(last_settled, latest)
        self.logger.info(f"待结算: {pending} (上次结算: {last_settled})")

        settled_dates, fills, nav = [], [], {}
        if pending and not preview_only:
            settled_dates, fills, nav = self._settle(account, g_obj, pending, dry_run)
            last_settled = settled_dates[-1] if settled_dates else last_settled

        # 下一交易日预演
        next_td = self._next_trade_date(last_settled or latest)
        pending_orders = []
        if not settle_only and next_td:
            pending_orders = self._decide(account.copy(), g_obj, next_td, dry_run)

        summary = {
            "strategy": self.strategy_id,
            "last_settled": str(last_settled),
            "settled_dates": [str(d) for d in settled_dates],
            "fills": len(fills),
            "nav": nav,
            "next_trade_date": str(next_td) if next_td else None,
            "pending_orders": len(pending_orders),
            "dry_run": dry_run,
        }
        self.logger.info(f"Nightly done: {summary}")
        return summary

    # ══════════════════════════════════════════════════════════
    # 结算
    # ══════════════════════════════════════════════════════════

    def _settle(self, account: Account, g_obj: G, dates: list[date],
                dry_run: bool) -> tuple[list[date], list[dict], dict]:
        name_map = load_name_map()
        eng = self._build_engine(account, g_obj, dates[0], dates[-1])
        eng.setup()
        if g_obj.__dict__:
            eng.g.__dict__.update(g_obj.__dict__)   # restore 覆盖 initialize 默认值

        last_nav = {}
        for td in dates:
            self.logger.info(f"Settle {td}")
            bars_today = self._load_day_bars(td)
            bars_prev = self._load_prev_trade_bars(td)

            # confirm 模式：拿人工回填价（撮合时优先使用）
            if self.mode == "confirm":
                confirms = persistence.read_confirmed_orders(self.strategy_id, td)
                eng.price_overrides = {
                    c["code"]: float(c["confirm_price"])
                    for c in confirms if c.get("confirm_price")
                }
            eng.run_one_day(td, bars_today, bars_prev)
            eng.price_overrides = {}

            day_trades = [t for t in eng.trades if t["date"] == td]
            last_nav = eng.equity_curve[-1] if eng.equity_curve else {}
            if not dry_run:
                persistence.write_trades(self.strategy_id, td, day_trades)
                nav_row = dict(last_nav)
                nav_row["codes"] = eng.daily_positions[-1]["codes"] if eng.daily_positions else ""
                persistence.write_nav(self.strategy_id, td, account.initial_cash, nav_row)
                if self.write_positions:
                    self._sync_positions(td, day_trades, name_map)
                # 结算后通过 GatewayManager 回填 order_queue 状态
                self._gateway_settle_orders(self.strategy_id, td, day_trades)
                persistence.mark_orders_executed(self.strategy_id, td)
                persistence.save_snapshot(
                    self.strategy_id, td,
                    account.to_json(), eng.g.state_bytes(),
                )

        return dates, eng.trades, last_nav

    def _gateway_settle_orders(self, strategy_id: str, td: date,
                                trades: list[dict]) -> None:
        """结算后将已匹配的订单状态通过 PaperGateway 回写。

        运行期间 order_queue 中 pending 单被 GatewayManager 分派到
        PaperGateway 后已更新状态，这里做兜底：如果有遗漏的 pending 单
        （跑策略时未接入 gateway 管线），按已成交的交易记录回填。
        """
        import duckdb
        conn = duckdb.connect(persistence.DB_PATH, read_only=True)
        try:
            pending = conn.execute(
                "SELECT id, code, action, shares FROM order_queue "
                "WHERE strategy = ? AND trade_date = ? AND status = 'pending'",
                [strategy_id, td],
            ).fetchall()
        finally:
            conn.close()

        if not pending:
            return

        # 用成交记录匹配 pending 单
        trade_map: dict[tuple[str, str], list[dict]] = {}
        for t in trades:
            key = (t["code"], t["action"])
            trade_map.setdefault(key, []).append(t)

        from datetime import datetime
        for oid, code, action, shares in pending:
            key = (code, action)
            matched = trade_map.get(key, [])
            if matched:
                t = matched[0]
                conn = persistence.connect_write(persistence.DB_PATH)
                try:
                    conn.execute(
                        "UPDATE order_queue SET status = 'confirmed', "
                        "confirmed_at = ?, confirmed_price = ?, confirmed_shares = ? "
                        "WHERE id = ?",
                        [datetime.now(), t["price"], t["shares"], oid],
                    )
                finally:
                    conn.close()

    # ══════════════════════════════════════════════════════════
    # 预演
    # ══════════════════════════════════════════════════════════

    def _decide(self, account: Account, g_obj: G, next_td: date,
                dry_run: bool) -> list[dict]:
        """下一交易日盘前预演：只跑盘前+开盘槽，订单不落 Account。"""
        name_map = load_name_map()
        eng = self._build_engine(account, g_obj, next_td, next_td)
        # feed 空 today（纯盘前视图），prev = 实际 T-1
        eng._current_td = next_td
        eng._bars_today = None
        eng._bars_prev = self._load_prev_trade_bars(next_td)

        eng.setup()
        if g_obj.__dict__:
            eng.g.__dict__.update(g_obj.__dict__)

        eng.account.settle_new_day(next_td)
        # previous_date = 实际前一交易日（bars_prev 的日期）
        prev_date = next_td - timedelta(days=1)
        if eng._bars_prev is not None and not eng._bars_prev.empty:
            prev_date = eng._bars_prev["trade_date"].iloc[0].date()
        eng.context.previous_date = prev_date
        # 注入盘前价格：prev close → 策略层 last_price 绑定 T-1 收盘（选股用）
        bar_map: dict[str, float] = {}
        if eng._bars_prev is not None:
            for _, row in eng._bars_prev.iterrows():
                bar_map[row["code"]] = float(row["close"])
        eng.portfolio.update_prices(bar_map)
        if getattr(eng, '_slot_prices', None) is None:
            eng._slot_prices = {}
        eng._slot_prices = bar_map

        holds = {code: pos.total_amount for code, pos in account.positions.items()}
        if holds:
            g_obj._restore_hold_list = list(holds.keys())  # strategy JQ 侧读此字段
        else:
            g_obj._restore_hold_list = []

        # 跑盘前槽 + 开盘槽任务；槽保持 before_open → 所有订单进 _pending_orders 队列（不撮合）
        from engine.clock import sort_tasks
        sorted_tasks = sort_tasks(eng.tasks)
        preview = [t for t in sorted_tasks if t.slot.fill_kind in ("queue_to_open", "open")]
        eng._slot = parse_time("before_open")
        eng._run_slot_tasks(preview, next_td)

        # 从 pending_orders 提取建议（参考价 = T-1 收盘）
        held = {c: p.total_amount for c, p in eng.account.positions.items()}
        orders = []
        for code, kind, amount in eng._pending_orders:
            name = resolve_name(code, name_map)
            ref_price = bar_map.get(code, 0.0)
            if kind == "target_value":
                if amount <= 0:
                    side, shares = "SELL", held.get(code, 0)
                else:
                    side = "BUY"
                    shares = int(amount / ref_price / 100) * 100 if ref_price > 0 else 0
            elif kind in ("amount", "target_amount"):
                delta = int(amount) - (held.get(code, 0) if kind == "target_amount" else 0)
                side, shares = ("BUY", delta) if delta >= 0 else ("SELL", -delta)
            else:  # value
                side = "BUY" if amount >= 0 else "SELL"
                shares = int(abs(amount) / ref_price / 100) * 100 if ref_price > 0 else 0
            if shares <= 0:
                continue
            orders.append({
                "code": code, "name": name, "action": side,
                "price": round(ref_price, 3), "shares": shares,
                "reason": "预演建议", "kind": kind,
            })

        if not dry_run and orders:
            persistence.write_order_queue(self.strategy_id, next_td, orders)
            self._push_feishu(next_td, orders, account, eng)

        return orders

    # ══════════════════════════════════════════════════════════
    # 内部 helper
    # ══════════════════════════════════════════════════════════

    def _build_engine(self, account: Account, g_obj: G, start: date, end: date) -> BacktestEngine:
        from engine.backtest_engine import BacktestEngine
        eng = BacktestEngine(
            strategy=self.module, start=start, end=end,
            initial_cash=account.initial_cash, cost=account.cost,
            strategy_name=self.strategy_id,
        )
        eng.account = account
        eng.g = g_obj
        eng.portfolio = Portfolio(eng.account)
        eng.context = Context(eng.portfolio)
        return eng

    def _restore(self, saved: dict | None) -> tuple[Account, G, date | None]:
        if saved is None:
            acct = Account(initial_cash=self.initial_cash, cost=self.cost)
            g_obj = G()
            last_settled = None
        else:
            acct = Account.from_json(saved["account_json"])
            g_obj = G()
            try:
                g_obj.load_bytes(saved["g_blob"])
            except Exception:
                self.logger.warning("g_blob 损坏，重置")
            last_settled = saved["settle_date"]
        return acct, g_obj, last_settled

    def _pending_settle_dates(self, last: date | None, latest: date) -> list[date]:
        if latest is None:
            return []
        start = last + timedelta(days=1) if last else latest
        return get_trade_days(start, latest)

    def _latest_data_date(self, asof: date | None) -> date | None:
        import duckdb
        conn = duckdb.connect(persistence.DB_PATH, read_only=True)
        try:
            row = conn.execute("SELECT MAX(trade_date), COUNT(*) FROM daily_bar"
                               " WHERE trade_date >= ?",
                               [(asof - timedelta(days=30)).isoformat() if asof else "2026-01-01"]
                               ).fetchone()
            if row and row[1] and row[1] >= LATEST_BAR_CHECK:
                return row[0]
            return None
        finally:
            conn.close()

    def _next_trade_date(self, asof: date) -> date | None:
        td_list = get_trade_days(asof + timedelta(days=1), asof + timedelta(days=7))
        return td_list[0] if td_list else None

    @staticmethod
    def _load_prev_trade_bars(td: date):
        """加载 td 前一交易日的 bars（跨周末/节假日正确）。"""
        prev_dates = get_trade_days(td - timedelta(days=14), td - timedelta(days=1))
        if prev_dates:
            from backtest.execution import load_full_daily_bars as _load_bars
            return _load_bars(prev_dates[-1], prev_dates[-1])
        return None

    @staticmethod
    def _load_day_bars(td: date):
        from backtest.execution import load_full_daily_bars as _load_bars
        return _load_bars(td, td)

    def _sync_positions(self, td: date, trades: list[dict], name_map: dict[str, str]):
        strategy_tag = f"JQ_{self.strategy_id.upper()}"
        conn = connect_write(persistence.DB_PATH)
        try:
            # 幂等：先清掉当日已写入的买入行（结算重放场景）
            conn.execute(
                "DELETE FROM positions WHERE strategy=? AND buy_date=? AND status='holding'",
                [strategy_tag, td],
            )
            for t in trades:
                if t["action"] == "买入":
                    conn.execute("""
                        INSERT INTO positions
                        (code, name, strategy, signal_date, buy_date, shares, buy_price,
                         current_price, stop_loss_pct, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'holding')
                    """, [t["code"], t.get("name", t["code"]), strategy_tag,
                          td, td, t["shares"], t["price"],
                          t["price"], 0.05])
                else:
                    conn.execute("""
                        UPDATE positions SET status='sold', sell_date=?, sell_price=?
                        WHERE code=? AND status='holding' AND strategy=?
                    """, [td, t["price"], t["code"], strategy_tag])
        finally:
            conn.close()

    def _push_feishu(self, next_td: date, orders: list[dict],
                     account: Account, strategy_name: str) -> None:
        """发送飞书卡片（尝试消息格式，失败不阻流程）。"""
        try:
            from scripts.feishu_signal_notify import get_tenant_token, send_card
            token = get_tenant_token()
            if not token:
                return
            lines = [f"**持仓 {len(account.positions)} 只 · {self.mode} 模式**", ""]
            for o in orders[:8]:
                emoji = "🔴 卖" if o["action"] == "SELL" else "🟢 买"
                lines.append(f"{emoji} **{o['code']} {o.get('name', '')}** "
                             f"{o['shares']} 股 @ ~{o['price']}")
            card_content = {
                "config": {"wide_screen_mode": True},
                "header": {
                    "template": "blue",
                    "title": {"tag": "plain_text", "content": f"🐟 菜场大妈预演 · {next_td}"},
                },
                "elements": [{"tag": "div",
                              "text": {"tag": "lark_md", "content": "\n".join(lines)}}],
            }
            card = {
                "msg_type": "interactive",
                "content": json.dumps(card_content, ensure_ascii=False),
            }
            send_card(token, "ou_113faaff836977aa0e1efb1a67707e0b", card)
        except Exception:
            self.logger.warning("飞书推送失败", exc_info=True)
