#!/usr/bin/env python3
"""Build positions from daily_signals buy-signals.

Picks top-N buy signals (by score) each day, allocates equal capital
(~50 万 total / max 10 positions), and writes/updates the positions table.

Usage:
    .venv/bin/python scripts/build_positions.py                        # only latest signals date
    .venv/bin/python scripts/build_positions.py --start 20260714       # range
    .venv/bin/python scripts/build_positions.py --dry-run               # print instead of write
    .venv/bin/python scripts/build_positions.py --max-positions 5       # fewer concurrent holds
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import json
from datetime import date as date_type

import duckdb
import pandas as pd

from config.settings import get_trading_config, settings
from utils.db import connect_write
from utils.logger import get_logger
from utils.stock_name import load_name_map, resolve_name
from engine.position_sizer import PositionSizer, create_sizer, DEFAULT_TOTAL_CAPITAL

logger = get_logger("build_positions")

_cfg = get_trading_config()

DB_PATH = str(Path(settings.duckdb_path))
INIT_CASH = _cfg.initial_cash
FEE_RATE = _cfg.fee_rate           # 万五手续费
MAX_POSITIONS = _cfg.max_positions # 单日最大持仓数
FIXED_SL_PCT = _cfg.fixed_stop_loss_pct  # 固定止损
SIZER_ENABLED: bool = getattr(_cfg, "position_sizer_enabled", True)
SIZER_TOTAL_CAPITAL: float = getattr(_cfg, "sizer_total_capital", DEFAULT_TOTAL_CAPITAL)

# ── strategy → position sizing（settings.yaml trading.strategy_alloc）──
STRATEGY_ALLOC: dict[str, float] = _cfg.strategy_alloc
MAX_PER_STRATEGY: dict[str, int] = getattr(_cfg, "max_per_strategy", None) or {}
MARKET_FILTER_ENABLED: bool = getattr(_cfg, "market_filter_enabled", False)
MARKET_FILTER_INDEX: str = getattr(_cfg, "market_filter_index", "000001.SH")
MARKET_FILTER_MA: int = getattr(_cfg, "market_filter_ma_period", 20)
FACTOR_FILTER_ENABLED: bool = getattr(_cfg, "factor_filter_enabled", False)
FACTOR_FILTER_TOP_FRACTION: float = 0.25   # 因子得分前 25% 才建仓


def _index_above_ma(conn: duckdb.DuckDBPyConnection, target_date: str) -> bool:
    """Return True if 上证 close >= MA20 on the last trading day before target_date."""
    try:
        row = conn.execute("""
            WITH recent AS (
                SELECT close FROM index_daily
                WHERE ts_code = ? AND trade_date <= ?
                ORDER BY trade_date DESC
                LIMIT ?
            )
            SELECT * FROM recent
        """, [MARKET_FILTER_INDEX, target_date, MARKET_FILTER_MA]).fetchall()
        if len(row) < MARKET_FILTER_MA:
            return True   # 数据不足时不拦
        closes = [float(r[0]) for r in reversed(row)]
        ma = sum(closes) / len(closes)
        latest = closes[-1]
        return latest >= ma
    except Exception:
        return True   # 容错：查不到指数数据也不拦


def _fetch_today_buy_candidates(conn: duckdb.DuckDBPyConnection, target_date: str) -> pd.DataFrame:
    """Return all stocks with any buy signal on *target_date*, ranked by score."""
    buy_cols = [f"signal_buy_{s.lower()}" for s in STRATEGY_ALLOC]

    # build WHERE clause
    clauses = " OR ".join(f'"{c}" = true' for c in buy_cols)
    sql = f"""
        SELECT code, name, close, change_pct, score_b1, score_b2, score_blk,
               score_blkB2, score_scb, score_dz30,
               signal_buy_b1, signal_buy_b2, signal_buy_blk,
               signal_buy_blkB2, signal_buy_scb, signal_buy_dz30,
               score_s1, signal_跌破多空线, signal_止损
        FROM daily_signals
        WHERE date = ? AND ({clauses})
    """
    df = conn.execute(sql, [target_date]).fetchdf()
    if df.empty:
        return df

    # Compute best-score-per-stock across strategies
    strategy_cols = [(f"score_{s.lower()}", f"signal_buy_{s.lower()}", s) for s in STRATEGY_ALLOC]
    best_scores = []
    best_strats = []
    for _, row in df.iterrows():
        best_s, best_strat = 0.0, ""
        for sc, sig, strat in strategy_cols:
            if row.get(sig) and row.get(sc, 0) > best_s:
                best_s = float(row.get(sc, 0) or 0)
                best_strat = strat
        best_scores.append(best_s)
        best_strats.append(best_strat)

    df["best_score"] = best_scores
    df["best_strategy"] = best_strats
    df = df.sort_values("best_score", ascending=False)
    return df


def _position_size(price: float, weight: float, total_cash: float = INIT_CASH) -> int:
    """Return number of shares (multiples of 100) for given price and allocation weight."""
    budget = total_cash * weight / MAX_POSITIONS
    raw = int(budget / (price * (1 + FEE_RATE)) / 100) * 100
    return max(0, raw)


def _is_holding(conn: duckdb.DuckDBPyConnection, code: str) -> bool:
    r = conn.execute(
        "SELECT 1 FROM positions WHERE code = ? AND status = 'holding'", [code]
    ).fetchone()
    return r is not None


def _open_count(conn: duckdb.DuckDBPyConnection) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM positions WHERE status = 'holding'"
    ).fetchone()[0]


def _fetch_today_sell_signals(conn: duckdb.DuckDBPyConnection, target_date: str) -> pd.DataFrame:
    """Return all stocks with sell signals on target_date that are currently holding."""
    sql = """
        SELECT ds.code, ds.name, ds.close, ds.signal_s1_full, ds.signal_s1_half,
               ds.signal_跌破多空线, ds.signal_止损
        FROM daily_signals ds
        INNER JOIN positions p ON ds.code = p.code AND p.status = 'holding'
        WHERE ds.date = ?
          AND (ds.signal_s1_full = true OR ds.signal_s1_half = true
               OR ds.signal_跌破多空线 = true OR ds.signal_止损 = true)
    """
    return conn.execute(sql, [target_date]).fetchdf()


def _process_sells(conn: duckdb.DuckDBPyConnection, sell_date: str,
                   sell_df: pd.DataFrame, name_map: dict, dry_run: bool) -> int:
    """Sell holding positions that triggered exit signals. Return count sold."""
    sold = 0
    for _, row in sell_df.iterrows():
        code = str(row["code"])
        close = float(row["close"])

        # Determine sell reason
        reasons = []
        if row.get("signal_s1_full"): reasons.append("S1_FULL")
        if row.get("signal_s1_half"): reasons.append("S1_HALF")
        if row.get("signal_跌破多空线"): reasons.append("跌破多空线")
        if row.get("signal_止损"): reasons.append("止损")
        reason = ",".join(reasons) if reasons else "信号卖出"

        # Get buy price
        buy_rec = conn.execute(
            "SELECT buy_price, shares FROM positions WHERE code=? AND status='holding'",
            [code]
        ).fetchone()
        if not buy_rec:
            continue
        buy_price, shares = buy_rec[0], buy_rec[1]
        profit_loss = round((close - buy_price) * shares, 2)
        profit_pct = round((close - buy_price) / buy_price * 100, 2) if buy_price else 0

        if not dry_run:
            conn.execute(
                """UPDATE positions SET status='sold', sell_date=?, sell_price=?,
                   sell_reason=?, profit_loss=?, profit_pct=?, current_price=?
                   WHERE code=? AND status='holding'""",
                [sell_date, close, reason, profit_loss, profit_pct, close, code],
            )
        sold += 1
        logger.info(f"  SELL {code} {name_map.get(code, code)} @ {close} "
                     f"reason={reason} P&L={profit_loss}")
    return sold


def run(
    start_date: str | None = None,
    end_date: str | None = None,
    max_positions: int = MAX_POSITIONS,
    dry_run: bool = False,
) -> dict:
    """Main entry point."""
    name_map = load_name_map()

    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        if start_date and end_date:
            dates = [
                str(r[0])
                for r in conn.execute(
                    "SELECT DISTINCT date FROM daily_signals WHERE date BETWEEN ? AND ? ORDER BY date",
                    [start_date, end_date],
                ).fetchall()
            ]
        elif start_date:
            dates = [start_date]
        else:
            # latest
            row = conn.execute("SELECT MAX(date) FROM daily_signals").fetchone()
            if not row or not row[0]:
                logger.error("No daily_signals data")
                return {"error": "no_data"}
            dates = [str(row[0])]
    finally:
        conn.close()

    total_bought = 0
    total_sold = 0
    details: list[dict] = []

    w_conn = connect_write(DB_PATH)
    try:
        # ── Step 0: 先平仓（卖出信号/止损）──
        for td in dates:
            sell_df = _fetch_today_sell_signals(w_conn, td)
            if not sell_df.empty:
                sold = _process_sells(w_conn, td, sell_df, name_map, dry_run)
                total_sold += sold
                if sold:
                    logger.info(f"{td}: sold {sold} positions (→ {_open_count(w_conn)} holding)")

        # ── Step 1: 建仓 ──
        for td in dates:
            # 大盘状态过滤：MA20 之下只平仓不建仓
            if MARKET_FILTER_ENABLED and not _index_above_ma(w_conn, td):
                logger.info(f"{td}: {MARKET_FILTER_INDEX} below MA{MARKET_FILTER_MA} — skip buy, keep cash")
                continue

            # Re-use the write connection for reads (DuckDB single-config rule)
            df = _fetch_today_buy_candidates(w_conn, td)

            if df.empty:
                logger.info(f"{td}: no buy candidates")
                continue

            open_slots = max_positions - _open_count(w_conn)
            if open_slots <= 0:
                logger.info(f"{td}: portfolio full ({max_positions} holding), skip new entries")
                continue

            # 因子交叉过滤：买入候选只保留因子得分前 TOP_FRACTION 的
            factor_ok: set[str] = set()
            if FACTOR_FILTER_ENABLED:
                try:
                    from engine.factor_scorer import score_snapshot
                    scorer = score_snapshot(target_date=date_type.fromisoformat(td), top_n=2000)
                    cutoff = int(len(scorer.top_codes) * FACTOR_FILTER_TOP_FRACTION)
                    factor_ok = set(scorer.top_codes[:max(cutoff, 50)])
                except Exception:
                    logger.warning(f"因子过滤不可用，跳过")

            # ── 动态仓位分配 (PositionSizer) ──
            if SIZER_ENABLED:
                sizer = create_sizer(DB_PATH, total_capital=SIZER_TOTAL_CAPITAL)
                sizer.register_from_config(STRATEGY_ALLOC)
                candidates = []
                for _, row in df.iterrows():
                    code = str(row["code"])
                    if factor_ok and code not in factor_ok:
                        continue
                    if _is_holding(w_conn, code):
                        continue
                    strategy = row["best_strategy"]
                    cap = MAX_PER_STRATEGY.get(strategy)
                    if cap is not None:
                        n = w_conn.execute(
                            "SELECT COUNT(*) FROM positions WHERE strategy=? AND status='holding'",
                            [strategy],
                        ).fetchone()[0]
                        if n >= cap:
                            continue
                    if strategy not in STRATEGY_ALLOC or STRATEGY_ALLOC[strategy] <= 0:
                        continue
                    candidates.append({
                        "code": code,
                        "strategy": strategy,
                        "price": float(row["close"]),
                        "name": resolve_name(code, name_map),
                        "change_pct": float(row.get("change_pct", 0) or 0),
                        "score_b1": float(row.get("score_b1", 0) or 0),
                        "score_b2": float(row.get("score_b2", 0) or 0),
                    })
                allocated = sizer.allocate(candidates)
                bought_today = 0
                for c in allocated:
                    if not dry_run:
                        w_conn.execute(
                            """INSERT INTO positions
                               (code, name, strategy, signal_date, buy_date, shares, buy_price,
                                buy_change_pct, buy_score_b1, buy_score_b2,
                                current_price, stop_loss_pct, status)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'holding')""",
                            [
                                c["code"], c.get("name", ""), c["strategy"], td, td,
                                c["shares"], c["price"],
                                round(c.get("change_pct", 0) or 0, 2),
                                c.get("score_b1", 0),
                                c.get("score_b2", 0),
                                c["price"], round(FIXED_SL_PCT, 4),
                            ],
                        )
                    bought_today += 1
                    details.append({
                        "date": td, "code": c["code"],
                        "name": c.get("name", ""),
                        "strategy": c["strategy"],
                        "price": c["price"], "shares": c["shares"],
                    })
            else:
                # ── 回退到固定仓位 ──
                bought_today = 0
                for _, row in df.iterrows():
                    if bought_today >= open_slots:
                        break
                    code = str(row["code"])
                    if factor_ok and code not in factor_ok:
                        continue
                    if _is_holding(w_conn, code):
                        continue
                    strategy = row["best_strategy"]
                    cap = MAX_PER_STRATEGY.get(strategy)
                    if cap is not None:
                        n = w_conn.execute(
                            "SELECT COUNT(*) FROM positions WHERE strategy=? AND status='holding'",
                            [strategy],
                        ).fetchone()[0]
                        if n >= cap:
                            continue
                    if strategy not in STRATEGY_ALLOC or STRATEGY_ALLOC[strategy] <= 0:
                        continue
                    price = float(row["close"])
                    weight = STRATEGY_ALLOC.get(strategy, 0.10)
                    shares = _position_size(price, weight)
                    if shares < 100:
                        continue
                    name = resolve_name(code, name_map)
                    change_pct = float(row.get("change_pct", 0) or 0)
                    if not dry_run:
                        w_conn.execute(
                            """INSERT INTO positions
                               (code, name, strategy, signal_date, buy_date, shares, buy_price,
                                buy_change_pct, buy_score_b1, buy_score_b2,
                                current_price, stop_loss_pct, status)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'holding')""",
                            [
                                code, name, strategy, td, td, shares, price,
                                round(change_pct, 2),
                                float(row.get("score_b1", 0) or 0),
                                float(row.get("score_b2", 0) or 0),
                                price, round(FIXED_SL_PCT, 4),
                            ],
                        )
                    bought_today += 1
                    details.append({
                        "date": td, "code": code, "name": name,
                        "strategy": strategy, "price": price, "shares": shares,
                    })
            if bought_today:
                logger.info(
                    f"{td}: bought {bought_today} positions "
                    f"(→ {_open_count(w_conn)} total holding)"
                )
            total_bought += bought_today

        if not dry_run:
            w_conn.commit()
    finally:
        w_conn.close()

    if not dry_run and total_bought:
        logger.info(f"Built {total_bought} positions across {len(dates)} dates")

    return {
        "dates_processed": len(dates),
        "total_bought": total_bought,
        "total_sold": total_sold,
        "positions": details[:20],  # first 20
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Build positions from buy signals")
    p.add_argument("--start", type=str, default=None, help="YYYY-MM-DD start (default: latest)")
    p.add_argument("--end", type=str, default=None, help="YYYY-MM-DD end")
    p.add_argument("--max-positions", type=int, default=MAX_POSITIONS,
                   help="Max concurrent holdings (default: 10)")
    p.add_argument("--dry-run", action="store_true", help="Show candidates, don't write")
    args = p.parse_args()

    try:
        result = run(
            start_date=args.start,
            end_date=args.end,
            max_positions=args.max_positions,
            dry_run=args.dry_run,
        )
        if args.dry_run:
            print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        else:
            logger.info(f"Done: {json.dumps({k: v for k, v in result.items() if k != 'positions'}, default=str)}")
        return 0
    except Exception:
        logger.exception("build_positions failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
