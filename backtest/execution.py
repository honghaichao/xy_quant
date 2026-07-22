"""
回测数据层 — 执行价加载、全量日线、分钟线第一笔成交价。

职责：
  - 加载交易日期列表
  - 加载全量日线 OHLCV（带市值）
  - 加载分钟线第一笔成交价（9:31）作为执行价
  - 日线 open 回落（分钟线缺失时）
  - 加载基准数据（沪深 300）
  - 加载全市场元数据 + 分红数据

所有函数从 DuckDB / PostgreSQL 读取，用 read_only 连接，不写库。
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import psycopg

from config.settings import settings

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = str(PROJECT_ROOT / "data_store" / "market.duckdb")


def _to_ts(code: str) -> str:
    """纯数字代码 → 带交易所后缀"""
    code = str(code).strip()
    if len(code) == 6:
        return f"{code}.SH" if code.startswith("6") else f"{code}.SZ"
    return code


# ═══════════════════════════════════════════════════════════════
# 交易日历
# ═══════════════════════════════════════════════════════════════

def load_trade_dates(start: date, end: date) -> list[date]:
    """获取回测区间内所有交易日"""
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        rows = conn.execute(
            "SELECT DISTINCT trade_date FROM daily_bar "
            "WHERE trade_date >= ? AND trade_date <= ? ORDER BY trade_date",
            [start.isoformat(), end.isoformat()],
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# 日线数据
# ═══════════════════════════════════════════════════════════════

def load_full_daily_bars(start: date, end: date) -> pd.DataFrame:
    """一次性加载回测区间内的全量日线 OHLCV + total_mv + pe + pb。

    排除科创(688)、北交(920)。
    """
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        df = conn.execute("""
            SELECT d.trade_date, d.ts_code, d.open, d.high, d.low, d.close,
                   d.pre_close, d.vol,
                   b.total_mv, b.pe, b.pb
            FROM daily_bar d
            LEFT JOIN daily_basic b ON d.ts_code = b.ts_code AND d.trade_date = b.trade_date
            WHERE d.trade_date >= ? AND d.trade_date <= ?
            ORDER BY d.trade_date, d.ts_code
        """, [start.isoformat(), end.isoformat()]).fetchdf()
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df["code"] = df["ts_code"].str[:6]
        df = df[~df["code"].str.startswith("688")]
        df = df[~df["code"].str.startswith("920")]
        return df
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# 分钟线执行价
# ═══════════════════════════════════════════════════════════════

def load_minute_first_bar(codes: list[str], td: date) -> dict[str, float]:
    """加载一批股票在交易日 td 的 9:31 第一根分钟线 close。

    这就是 "真实成交价" — 集合竞价后第一笔撮合价。
    分钟线缺失时返回空 dict（调用方回落 load_daily_open_fallback）。

    注意：通过 minute_bar 视图查询（底层 UNION ALL 79 张月表），
    数据量 17 亿行但 DuckDB 分区裁剪后只扫当月的表。
    """
    if not codes:
        return {}
    ts_codes = [_to_ts(c) for c in codes]
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        placeholders = ",".join(["?" for _ in ts_codes])
        rows = conn.execute(f"""
            SELECT ts_code, close
            FROM (
                SELECT ts_code, close,
                       ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY datetime) AS rn
                FROM minute_bar
                WHERE ts_code IN ({placeholders})
                  AND datetime >= ?::TIMESTAMP
                  AND datetime <  ?::TIMESTAMP
            ) sub
            WHERE rn = 1
        """, ts_codes + [f"{td.isoformat()} 09:29:00", f"{td.isoformat()} 09:35:00"]).fetchall()
        result = {}
        for ts, price in rows:
            code = ts.split(".")[0]
            result[code] = float(price)
        return result
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# 指定时点分钟价 + 回落
# ═══════════════════════════════════════════════════════════════

def load_minute_bar_at(codes: list[str], td: date, hhmm: str) -> dict[str, float]:
    """加载指定时点（如 14:50）分钟 close，回落日线 close。

    与 load_minute_first_bar 同构；缺失时回落日线 close。
    """
    if not codes:
        return {}
    ts_codes = [_to_ts(c) for c in codes]
    ts_start = f"{td.isoformat()} {hhmm}:00"
    ts_end = f"{td.isoformat()} {hhmm}:59"
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        placeholders = ",".join(["?" for _ in ts_codes])
        rows = conn.execute(f"""
            SELECT ts_code, close
            FROM (
                SELECT ts_code, close,
                       ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY datetime) AS rn
                FROM minute_bar
                WHERE ts_code IN ({placeholders})
                  AND datetime >= ?::TIMESTAMP
                  AND datetime <  ?::TIMESTAMP
            ) sub
            WHERE rn = 1
        """, ts_codes + [ts_start, ts_end]).fetchall()
        result = {ts.split(".")[0]: float(close) for ts, close in rows}
        missing = [c for c in codes if c not in result]
        if missing:
            result.update(_load_daily_close_fallback(missing, td))
        return result
    finally:
        conn.close()


def _load_daily_close_fallback(codes: list[str], td: date) -> dict[str, float]:
    ts_codes = [_to_ts(c) for c in codes]
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        placeholders = ",".join(["?" for _ in ts_codes])
        rows = conn.execute(f"""
            SELECT ts_code, close FROM daily_bar
            WHERE ts_code IN ({placeholders}) AND trade_date = ?
        """, ts_codes + [td.isoformat()]).fetchall()
        return {ts.split(".")[0]: float(close)
                for ts, close in rows if close and close > 0}
    finally:
        conn.close()


def load_daily_open_fallback(codes: list[str], td: date) -> dict[str, float]:
    """日线 open 做回落 — 分钟线没有数据的股票用集合竞价开盘价"""
    if not codes:
        return {}
    ts_codes = [_to_ts(c) for c in codes]
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        placeholders = ",".join(["?" for _ in ts_codes])
        rows = conn.execute(f"""
            SELECT ts_code, open FROM daily_bar
            WHERE ts_code IN ({placeholders})
              AND trade_date = ?
        """, ts_codes + [td.isoformat()]).fetchall()
        result = {}
        for ts, open_price in rows:
            code = ts.split(".")[0]
            if open_price and open_price > 0:
                result[code] = float(open_price)
        return result
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# 基准数据
# ═══════════════════════════════════════════════════════════════

def load_benchmark(bench_code: str, start: date, end: date) -> pd.DataFrame | None:
    """加载基准指数日线（默认 000300.SH 沪深 300）"""
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        df = conn.execute(
            """SELECT trade_date, close
               FROM daily_bar
               WHERE ts_code = ? AND trade_date >= ? AND trade_date <= ?
               ORDER BY trade_date""",
            [bench_code, start.isoformat(), end.isoformat()],
        ).fetchdf()
        if not df.empty:
            df["trade_date"] = pd.to_datetime(df["trade_date"])
        return df
    except Exception:
        return None
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════
# 全市场元数据
# ═══════════════════════════════════════════════════════════════

def load_universe_meta() -> pd.DataFrame:
    """股票名称 + ST 标记 + 上市/退市日期（从 PG stock_basic）

    Returns:
        DataFrame indexed by code, columns: [ts_code, name, is_st, list_date, delist_date]
    """
    pg = psycopg.connect(settings.pg_dsn)
    try:
        df = pd.read_sql("SELECT ts_code, name, list_date, delist_date FROM stock_basic", pg)
        df["code"] = df["ts_code"].str[:6]
        df = df.set_index("code")
        df["is_st"] = df["name"].str.contains("ST|\\*ST|退", na=False)
        df["list_date"] = pd.to_datetime(df["list_date"], errors='coerce')
        df["delist_date"] = pd.to_datetime(df["delist_date"], errors='coerce')
        return df
    finally:
        pg.close()


def load_name_map() -> dict[str, str]:
    """code → 中文名称 映射"""
    pg = psycopg.connect(settings.pg_dsn)
    try:
        rows = pg.execute("SELECT ts_code, name FROM stock_basic").fetchall()
        return {r[0].split(".")[0]: r[1] for r in rows}
    finally:
        pg.close()


# ═══════════════════════════════════════════════════════════════
# 分红数据
# ═══════════════════════════════════════════════════════════════

def load_dividend_map(ref_date: date) -> dict[str, float]:
    """返回过去一年每股现金分红总额 dict[code] → cash_div（元/股）"""
    pg = psycopg.connect(settings.pg_dsn)
    one_year_ago = (ref_date - timedelta(days=365)).isoformat()
    try:
        rows = pg.execute(
            """SELECT SUBSTRING(ts_code, 1, 6) AS code, SUM(cash_div) AS total_div
               FROM dividend
               WHERE record_date >= %s AND record_date <= %s AND cash_div > 0
               GROUP BY SUBSTRING(ts_code, 1, 6)""",
            [one_year_ago, ref_date.isoformat()],
        ).fetchall()
        return {r[0]: float(r[1]) for r in rows}
    except Exception:
        return {}
    finally:
        pg.close()


# ═══════════════════════════════════════════════════════════════
# 资金流数据
# ═══════════════════════════════════════════════════════════════

def load_daily_money_flow(start: date, end: date) -> pd.DataFrame:
    """加载历史每日个股资金流（PostgreSQL stock_money_flow 表）。

    返回 DataFrame，列: trade_date, ts_code, name, main_inflow, main_inflow_pct,
    super_inflow, big_inflow, mid_inflow, small_inflow。
    用于回测中填充 T-1 资金流字段。
    """
    import psycopg as _psycopg
    from config.settings import settings as _settings

    conn = _psycopg.connect(_settings.pg_dsn)
    try:
        rows = conn.execute(
            """SELECT trade_date, ts_code, name,
                      main_inflow, main_inflow_pct,
                      super_inflow, big_inflow, mid_inflow, small_inflow
               FROM stock_money_flow
               WHERE trade_date BETWEEN %s AND %s
               ORDER BY trade_date, ts_code""",
            [start, end],
        ).fetchall()
        if not rows:
            return pd.DataFrame()
        cols = ["trade_date", "ts_code", "name",
                "main_inflow", "main_inflow_pct",
                "super_inflow", "big_inflow", "mid_inflow", "small_inflow"]
        return pd.DataFrame(rows, columns=cols)
    except Exception:
        return pd.DataFrame()
    finally:
        conn.close()
