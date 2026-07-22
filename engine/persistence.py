"""实盘态持久化 — LiveEngine 的状态/交易/净值/订单表。

全部写操作经 utils/db.py connect_write（DuckDB 写锁重试 30×10s）。
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from pathlib import Path

import duckdb
import pandas as pd

from config.settings import settings
from utils.db import connect_write
from utils.logger import get_logger

logger = get_logger("engine.persistence")

DB_PATH = str(Path(settings.duckdb_path))


# ═══════════════════════════════════════════════════════════════
# DDL（幂等）
# ═══════════════════════════════════════════════════════════════

def ensure_tables() -> None:
    conn = connect_write(DB_PATH)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jq_live_state (
                strategy_id   VARCHAR NOT NULL,
                settle_date   DATE    NOT NULL,
                account_json  VARCHAR,
                g_blob        BLOB,
                updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY   (strategy_id, settle_date)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jq_live_trades (
                strategy_id   VARCHAR,
                date          DATE,
                code          VARCHAR,
                name          VARCHAR,
                action        VARCHAR,
                price         DOUBLE,
                shares        INTEGER,
                amount        DOUBLE,
                commission    DOUBLE,
                pnl           DOUBLE,
                pnl_pct       DOUBLE,
                reason        VARCHAR,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jq_live_nav (
                strategy_id   VARCHAR,
                date          DATE,
                initial_cash  DOUBLE,
                cash          DOUBLE,
                position_value DOUBLE,
                total         DOUBLE,
                total_return  DOUBLE,
                positions     INTEGER,
                notes         VARCHAR,
                PRIMARY KEY   (strategy_id, date)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS order_queue (
                id            INTEGER PRIMARY KEY,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                strategy      VARCHAR DEFAULT '',
                trade_date    DATE NOT NULL,
                code          VARCHAR NOT NULL,
                name          VARCHAR,
                action        VARCHAR NOT NULL,
                price         DECIMAL(12,3),
                shares        INTEGER,
                reason        VARCHAR,
                status        VARCHAR DEFAULT 'pending',
                confirmed_at  TIMESTAMP,
                confirmed_price DECIMAL(12,3),
                confirmed_shares INTEGER,
                notes         VARCHAR
            )
        """)
        # 旧表（generate_orders.py 建的）无 strategy 列，补齐
        conn.execute("ALTER TABLE order_queue ADD COLUMN IF NOT EXISTS strategy VARCHAR DEFAULT ''")
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# 状态快照
# ═══════════════════════════════════════════════════════════════

def save_snapshot(strategy_id: str, settle_date: date, account_json: str, g_blob: bytes) -> None:
    conn = connect_write(DB_PATH)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO jq_live_state (strategy_id, settle_date, account_json, g_blob)"
            " VALUES (?, ?, ?, ?)",
            [strategy_id, settle_date, account_json, g_blob],
        )
    finally:
        conn.close()


def load_latest_snapshot(strategy_id: str, asof: date | None = None) -> dict | None:
    """返回 (account_json, g_blob, settle_date) 或 None。"""
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        sql = "SELECT settle_date, account_json, g_blob FROM jq_live_state WHERE strategy_id = ?"
        params = [strategy_id]
        if asof is not None:
            sql += " AND settle_date <= ?"
            params.append(asof)
        sql += " ORDER BY settle_date DESC LIMIT 1"
        row = conn.execute(sql, params).fetchone()
        if row is None:
            return None
        return {"settle_date": row[0], "account_json": row[1], "g_blob": row[2]}
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# 交易/净值（逐个结算日幂等）
# ═══════════════════════════════════════════════════════════════

def write_trades(strategy_id: str, td: date, trades: list[dict]) -> None:
    conn = connect_write(DB_PATH)
    try:
        conn.execute(
            "DELETE FROM jq_live_trades WHERE strategy_id = ? AND date = ?",
            [strategy_id, td],
        )
        for t in trades:
            conn.execute(
                """INSERT INTO jq_live_trades
                   (strategy_id, date, code, name, action, price, shares,
                    amount, commission, pnl, pnl_pct, reason)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    strategy_id, td,
                    t["code"], t.get("name", t["code"]),
                    t["action"], t["price"], t["shares"],
                    t.get("amount", 0), t.get("commission", 0),
                    t.get("pnl", 0), t.get("pnl_pct", 0),
                    t.get("reason", ""),
                ],
            )
    finally:
        conn.close()


def write_nav(strategy_id: str, td: date, initial_cash: float, nav_row: dict) -> None:
    conn = connect_write(DB_PATH)
    try:
        conn.execute(
            "DELETE FROM jq_live_nav WHERE strategy_id = ? AND date = ?",
            [strategy_id, td],
        )
        conn.execute(
            """INSERT INTO jq_live_nav (strategy_id, date, initial_cash, cash,
               position_value, total, total_return, positions, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                strategy_id, td, initial_cash,
                nav_row.get("cash", 0), nav_row.get("position_value", 0),
                nav_row.get("total", 0), nav_row.get("total_return", 0),
                nav_row.get("positions", 0),
                nav_row.get("codes") or "",
            ],
        )
    finally:
        conn.close()


def write_order_queue(strategy_id: str, td: date, orders: list[dict]) -> None:
    """写入待确认订单（decide 预演产出）。"""
    if not orders:
        return
    conn = connect_write(DB_PATH)
    try:
        next_id = conn.execute("SELECT COALESCE(MAX(id), 0) FROM order_queue").fetchone()[0]
        for o in orders:
            next_id += 1
            conn.execute(
                """INSERT INTO order_queue
                   (id, strategy, trade_date, code, name, action, price, shares,
                    reason, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
                [
                    next_id, strategy_id, td,
                    o.get("code", ""), o.get("name", o.get("code", "")),
                    o.get("action", "BUY"), o.get("price", 0),
                    o.get("shares", 0), o.get("reason", "预演建议"),
                ],
            )
    finally:
        conn.close()


def read_confirmed_orders(strategy_id: str, td: date) -> list[dict]:
    """读取已确认订单（confirm 模式重放用），无则空。"""
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        rows = conn.execute(
            """SELECT code, action, confirmed_price, confirmed_shares, price
               FROM order_queue
               WHERE strategy = ? AND trade_date = ? AND status IN ('confirmed','executed')""",
            [strategy_id, td],
        ).fetchall()
        return [
            {"code": r[0], "action": r[1], "confirm_price": r[2] or r[4], "confirm_shares": r[3]}
            for r in rows
        ]
    except Exception:
        return []
    finally:
        conn.close()


def mark_orders_executed(strategy_id: str, td: date) -> None:
    """结算后将对应日 pending/confirmed 单置为 executed。"""
    conn = connect_write(DB_PATH)
    try:
        conn.execute(
            "UPDATE order_queue SET status = 'executed'"
            " WHERE strategy = ? AND trade_date = ? AND status IN ('pending','confirmed')",
            [strategy_id, td],
        )
    finally:
        conn.close()
