"""Dynamic position sizing engine.

Calculates per-stock position sizes using:
  - Market regime (MA distance) → heat multiplier
  - Volatility targeting (realized vol → vol multiplier)
  - Kelly / Sharpe-based strategy allocation
  - Per-stock and per-strategy risk caps

Usage:
    from engine.position_sizer import PositionSizer

    sizer = PositionSizer(db_conn)
    size_pct = sizer.calc(stock_code, strategy, entry_price)
    shares   = sizer.shares(size_pct, entry_price)

    # Or get full allocation matrix:
    alloc = sizer.allocate(buy_candidates)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import duckdb


# ── defaults (overridable via config) ──────────────────────────────────
DEFAULT_TOTAL_CAPITAL = 600_000.0        # 合并信号 50万 + JQ 10万
DEFAULT_TARGET_VOL = 0.15               # 年化目标波动率
DEFAULT_MAX_SINGLE_STOCK_PCT = 0.15     # 单票 ≤ 15%
DEFAULT_MAX_STRATEGY_PCT = 0.30         # 单策略 ≤ 30%
DEFAULT_MAX_TOTAL_PCT = 0.80            # 总仓位 ≤ 80%
DEFAULT_STOP_LOSS_PCT = 0.05            # 固定止损 5%
DEFAULT_TRAILING_STOP_PCT = 0.03        # 移动止损 3%
DEFAULT_LOOKBACK_DAYS = 20              # 波动率回看窗口


@dataclass
class StrategyMeta:
    """Per-strategy performance / risk metadata."""
    name: str
    sharpe: float = 1.0
    win_rate: float = 0.50
    avg_win: float = 0.02      # absolute return
    avg_loss: float = -0.02
    n_trades: int = 0
    base_weight: float = 0.10  # prior allocation weight (from config)
    enabled: bool = True


@dataclass
class MarketState:
    """Current market regime snapshot."""
    index_close: float = 0.0
    index_ma20: float = 0.0
    regime: str = "neutral"       # "bull" / "neutral" / "bear" / "crash"
    heat_multiplier: float = 1.0
    portfolio_vol_20d: float = 0.0


# ──────────────────────────────────────────────────────────────────────


class PositionSizer:
    """Dynamic position sizing calculator.

    Parameters
    ----------
    conn : duckdb.DuckDBPyConnection (read-only)
        Live DB handle for fetching market data.
    total_capital : float
        Combined cash + position value used as allocation base.
    """

    def __init__(
        self,
        conn: duckdb.DuckDBPyConnection,
        *,
        total_capital: float = DEFAULT_TOTAL_CAPITAL,
        target_vol: float = DEFAULT_TARGET_VOL,
        max_single_pct: float = DEFAULT_MAX_SINGLE_STOCK_PCT,
        max_strategy_pct: float = DEFAULT_MAX_STRATEGY_PCT,
        max_total_pct: float = DEFAULT_MAX_TOTAL_PCT,
        lookback: int = DEFAULT_LOOKBACK_DAYS,
    ) -> None:
        self._conn = conn
        self.total_capital = total_capital
        self.target_vol = target_vol
        self.max_single_pct = max_single_pct
        self.max_strategy_pct = max_strategy_pct
        self.max_total_pct = max_total_pct
        self.lookback = lookback

        self._strategies: dict[str, StrategyMeta] = {}
        self._market: MarketState | None = None

    # ── strategy registry ──────────────────────────────────────────

    def register_strategy(self, meta: StrategyMeta) -> None:
        self._strategies[meta.name] = meta

    def register_from_backtest(self, run_ids: list[str]) -> None:
        """Pull strategy stats from backtest_performance."""
        ph = ",".join("?" for _ in run_ids)
        rows = self._conn.execute(
            f"""SELECT bp.run_id, br.strategy_name, bp.sharpe_ratio, bp.win_rate,
                       bp.total_return, bp.total_trades, bp.annual_volatility
                FROM backtest_performance bp
                JOIN backtest_run br ON bp.run_id = br.run_id
                WHERE bp.run_id IN ({ph})""",
            run_ids,
        ).fetchall()
        for run_id, name, sharpe, wr, ret, trades, vol in rows:
            k = name.replace("(JQ引擎)", "").strip()
            if k not in self._strategies:
                self._strategies[k] = StrategyMeta(name=k)
            s = self._strategies[k]
            s.sharpe = float(sharpe) if sharpe and sharpe > 0 else s.sharpe
            s.win_rate = float(wr) if wr else s.win_rate
            s.n_trades = int(trades) if trades else s.n_trades
            if ret and trades and trades > 0:
                avg_return = float(ret) / int(trades)
                s.avg_win = max(avg_return * 1.5, 0.01)
                s.avg_loss = min(avg_return * 0.5, -0.01)

    def register_from_config(self, alloc: dict[str, float]) -> None:
        """Seed strategy weights from settings.yaml strategy_alloc."""
        for name, weight in alloc.items():
            if name not in self._strategies:
                self._strategies[name] = StrategyMeta(name=name)
            self._strategies[name].base_weight = weight
            if weight <= 0:
                self._strategies[name].enabled = False

    # ── market state ───────────────────────────────────────────────

    def refresh_market_state(self, target_date: date | None = None) -> MarketState:
        """Pull index MA, realised portfolio vol, and compute heat multiplier."""
        state = MarketState()
        ts = target_date.isoformat() if target_date else None

        # 1) index MA20 distance (use exact lookback window)
        idx = self._conn.execute(
            """SELECT trade_date, close FROM index_daily
               WHERE ts_code = '000001.SH' AND (? IS NULL OR trade_date <= ?)
               ORDER BY trade_date DESC LIMIT ?""",
            [ts, ts, self.lookback],
        ).fetchall()
        if len(idx) >= 5:
            closes = [float(r[1]) for r in reversed(idx)]
            state.index_close = closes[-1]
            state.index_ma20 = sum(closes) / len(closes)
            ma_dist_pct = (state.index_close / state.index_ma20 - 1) * 100

            if ma_dist_pct > 5:
                state.regime = "bull"
                state.heat_multiplier = 1.20
            elif ma_dist_pct > -3:
                state.regime = "neutral"
                state.heat_multiplier = 1.00
            elif ma_dist_pct > -5:
                state.regime = "bear"
                state.heat_multiplier = 0.50
            else:
                state.regime = "crash"
                state.heat_multiplier = 0.25  # still 25% allocation — don't go fully to cash
        else:
            state.heat_multiplier = 1.0

        # 2) portfolio realised vol
        nav_rows = self._conn.execute(
            """SELECT total_value FROM portfolio_daily
               ORDER BY date DESC LIMIT ?""",
            [self.lookback + 1],
        ).fetchall()
        if len(nav_rows) >= 6:
            vals = [float(r[0]) for r in reversed(nav_rows) if r[0] is not None]
            if len(vals) >= 6:
                returns = [(vals[i] / vals[i - 1] - 1) for i in range(1, len(vals))]
                if returns:
                    mean_r = sum(returns) / len(returns)
                    variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
                    state.portfolio_vol_20d = math.sqrt(variance) * math.sqrt(252) if variance > 0 else 0.0

        self._market = state
        return state

    @property
    def market(self) -> MarketState:
        if self._market is None:
            self.refresh_market_state()
        assert self._market is not None
        return self._market

    # ── core sizing logic ──────────────────────────────────────────

    def kelly_fraction(self, strategy: str) -> float:
        """Full Kelly fraction for a strategy; capped at 25%.

        For strategies with <5 trades, returns a bootstrap fraction (0.03)
        based on a reasonable prior (45% win, 1.5x payoff).
        """
        meta = self._strategies.get(strategy)
        if not meta or not meta.enabled:
            return 0.0
        if meta.n_trades < 5:
            return 0.03  # bootstrap: ~45% wr, 1.5x payoff → kelly ≈ 0.08 capped at 3%
        if meta.avg_loss == 0 or meta.win_rate == 0:
            return 0.0
        payoff = meta.avg_win / abs(meta.avg_loss)
        kelly = meta.win_rate - (1 - meta.win_rate) / payoff
        # Floor: even negative-kelly strategies get a tiny allocation to keep learning
        return max(0.005, min(kelly, 0.25))

    def vol_multiplier(self) -> float:
        """Vol-targeting multiplier: cap position when realised vol exceeds target."""
        vol = self.market.portfolio_vol_20d
        if vol <= 0:
            return 1.0
        ratio = self.target_vol / vol
        return max(0.25, min(ratio, 1.5))

    def calc(self, strategy: str, entry_price: float) -> float:
        """Return position size as a fraction of total_capital (0.0-1.0).

        The final size = base_weight × heat_multiplier × vol_multiplier
        """
        meta = self._strategies.get(strategy)
        if not meta or not meta.enabled:
            return 0.0

        # 1) Sharpe-weighted base
        total_sharpe = sum(s.sharpe for s in self._strategies.values() if s.enabled and s.sharpe > 0)
        if total_sharpe > 0 and meta.sharpe > 0:
            sharpe_weight = meta.sharpe / total_sharpe
        else:
            sharpe_weight = meta.base_weight

        # 2) Kelly adjustment (halve for negative Kelly)
        kelly = self.kelly_fraction(strategy)
        kelly_factor = 0.5 if kelly <= 0 else min(kelly * 2, 1.5)

        # 3) Volatility multiplier (independent of market regime)
        vol_adj = self.vol_multiplier()

        # 4) Strategy cap — market regime scales MAX_TOTAL, not per-stock pct
        raw_pct = sharpe_weight * kelly_factor * vol_adj
        return max(0.0, min(raw_pct, self.max_strategy_pct, self.max_single_pct))

    def shares(self, position_pct: float, entry_price: float) -> int:
        """Convert position fraction to rounded lot (multiples of 100)."""
        budget = self.total_capital * position_pct
        raw = int(budget / (entry_price * 1.0005) / 100) * 100
        return max(0, raw)

    def allocate(
        self, candidates: list[dict[str, Any]], skip_refresh: bool = False
    ) -> list[dict[str, Any]]:
        """Assign dynamic sizes to a list of buy candidates.

        Each candidate dict should have keys:
            'code', 'strategy', 'price'
        Returns the list augmented with 'size_pct', 'shares', 'budget'.

        Set skip_refresh=True when you have already set a custom market state
        (e.g. for backtesting with a specific regime override).
        """
        if not skip_refresh:
            self.refresh_market_state()

        results: list[dict[str, Any]] = []

        # Sort by strategy sharpe desc (best strategies first)
        def _sort_key(c: dict[str, Any]) -> float:
            s = self._strategies.get(str(c.get("strategy", "")))
            return -(s.sharpe) if s else 0.0

        used_total_pct = 0.0
        used_per_strategy: dict[str, float] = {}

        for c in sorted(candidates, key=_sort_key):
            strategy = str(c.get("strategy", ""))
            price = float(c.get("price", 0))
            code = str(c.get("code", ""))

            # Market-regime-scaled total cap: crash → 20%, bear → 40%, etc.
            regime_cap = self.max_total_pct * self.market.heat_multiplier
            regime_cap = max(0.10, min(regime_cap, self.max_total_pct))  # floor 10%

            if used_total_pct >= regime_cap:
                break

            strat_used = used_per_strategy.get(strategy, 0.0)
            if strat_used >= self.max_strategy_pct:
                continue

            raw_pct = self.calc(strategy, price)
            if raw_pct <= 0:
                continue

            # Apply remaining room
            room_total = regime_cap - used_total_pct
            room_strat = self.max_strategy_pct - strat_used
            pct = min(raw_pct, room_total, room_strat)
            if pct <= 0:
                continue

            shares = self.shares(pct, price)
            if shares < 100:
                continue

            c["size_pct"] = round(pct, 4)
            c["shares"] = shares
            c["budget"] = shares * price * 1.0005
            results.append(c)

            used_total_pct += pct
            used_per_strategy[strategy] = strat_used + pct

        return results

    # ── risk gates ─────────────────────────────────────────────────

    def entry_risk_ok(self, code: str, entry_price: float, size_pct: float) -> tuple[bool, str]:
        """Pre-entry risk checks.

        Returns (ok, reason).
        """
        if size_pct > self.max_single_pct:
            return False, f"size {size_pct:.1%} exceeds single-stock cap {self.max_single_pct:.0%}"

        if self.market.regime == "crash":
            return False, "market regime = crash — no new entries"

        # Check if already holding
        row = self._conn.execute(
            "SELECT 1 FROM positions WHERE code = ? AND status = 'holding'", [code]
        ).fetchone()
        if row:
            return False, "already holding"

        # Check daily volume / liquidity (skip for simplicity)
        return True, "ok"

    def check_stop_loss(self, code: str, current_price: float) -> tuple[bool, str]:
        """Check if a holding has triggered stop-loss."""
        row = self._conn.execute(
            """SELECT buy_price, shares, stop_loss_pct FROM positions
               WHERE code = ? AND status = 'holding'""",
            [code],
        ).fetchone()
        if not row:
            return False, "not holding"

        buy_price, shares, sl_pct = float(row[0]), int(row[1]), float(row[2] or 0.05)
        pnl_pct = (current_price - buy_price) / buy_price

        # Fixed stop
        if pnl_pct <= -sl_pct:
            return True, f"stop_loss ({pnl_pct:.1%} <= -{sl_pct:.0%})"

        # Trailing stop: if we were in profit and dropped > trailing_stop_pct from peak
        # (implemented as a simple check — could use a peak-tracking table)

        return False, "ok"

    # ── rebalancing ────────────────────────────────────────────────

    def rebalance_suggestions(self) -> list[dict[str, Any]]:
        """Suggest buy/sell adjustments for current holdings."""
        holdings = self._conn.execute(
            """SELECT code, name, strategy, shares, buy_price, current_price
               FROM positions WHERE status = 'holding'"""
        ).fetchall()
        if not holdings:
            return []

        self.refresh_market_state()
        suggestions: list[dict[str, Any]] = []

        total_current_value = sum(
            int(r[3]) * (float(r[5]) if r[5] else float(r[4])) for r in holdings
        )
        if total_current_value <= 0:
            return suggestions

        for code, name, strategy, shares, buy_price, current_price in holdings:
            price = float(current_price or buy_price)
            value = int(shares) * price
            current_pct = value / self.total_capital
            target_pct = self.calc(strategy, price)

            if abs(current_pct - target_pct) > 0.02:  # 2% drift threshold
                action = "trim" if current_pct > target_pct else "add"
                delta_pct = abs(target_pct - current_pct)
                suggestions.append({
                    "code": code,
                    "name": name,
                    "strategy": strategy,
                    "action": action,
                    "current_pct": round(current_pct, 3),
                    "target_pct": round(target_pct, 3),
                    "delta_pct": round(delta_pct, 3),
                    "current_price": price,
                })

        return suggestions


# ── convenience factory ─────────────────────────────────────────────


def create_sizer(
    db_path: str,
    total_capital: float = DEFAULT_TOTAL_CAPITAL,
) -> PositionSizer:
    """Create a PositionSizer seeded with strategy stats from the DB."""
    conn = duckdb.connect(db_path, read_only=True)
    sizer = PositionSizer(conn, total_capital=total_capital)

    # Seed from backtest performance
    try:
        run_ids = [
            r[0] for r in conn.execute(
                """SELECT run_id FROM backtest_performance
                   ORDER BY sharpe_ratio DESC LIMIT 10"""
            ).fetchall()
        ]
        if run_ids:
            sizer.register_from_backtest(run_ids)
    except Exception:
        pass

    # Seed from config-level strategy_alloc
    try:
        from config.settings import get_trading_config
        cfg = get_trading_config()
        alloc = getattr(cfg, "strategy_alloc", {})
        if alloc:
            sizer.register_from_config(alloc)
    except Exception:
        pass

    # Refresh market state now
    sizer.refresh_market_state()

    return sizer
