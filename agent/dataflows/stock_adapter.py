"""股票数据适配器 — 为 Agent 提供统一的数据获取接口。"""
from typing import Any

import duckdb
import pandas as pd

from agent.dataflows.markets.router import MarketRouter
from config.settings import settings


class StockDataAdapter:
    """股票数据适配器，优先从本地 DuckDB 获取数据。"""

    def __init__(self) -> None:
        self._db_path = settings.duckdb_path

    def _get_conn(self, read_only: bool = True) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(self._db_path, read_only=read_only)

    @staticmethod
    def _code_to_ts_code(code: str) -> str:
        code = str(code)
        return f"{code}.SH" if code.startswith("6") else f"{code}.SZ"

    # ═══════════════════════════════════════════════════════════════
    # 现有方法
    # ═══════════════════════════════════════════════════════════════

    def get_kline(self, code: str, start_date: str | None = None,
                  end_date: str | None = None, limit: int = 250) -> pd.DataFrame:
        """获取 K 线数据。"""
        ts_code = self._code_to_ts_code(code)
        conn = self._get_conn(read_only=True)
        try:
            sql = (
                "SELECT trade_date AS date, open, high, low, close, vol AS volume, amount, "
                "       (close / LAG(close) OVER (ORDER BY trade_date) - 1) * 100 AS pct_change "
                "FROM daily_bar WHERE ts_code = ? ORDER BY trade_date DESC LIMIT ?"
            )
            df = conn.execute(sql, [ts_code, limit]).fetchdf()
            df = df.sort_values("date").reset_index(drop=True)

            # 补最新基本面
            basic = self._get_latest_daily_basic(conn, ts_code)
            if basic is not None:
                for col in ["pe_ttm", "pe", "pb", "total_mv", "circ_mv", "turnover_rate"]:
                    val = basic.get(col)
                    if val is not None:
                        df[col] = val
            return df
        finally:
            conn.close()

    def get_daily_basic(self, code: str, limit: int = 250) -> pd.DataFrame:
        """获取每日指标 (PE, PB, 总市值等)。"""
        ts_code = self._code_to_ts_code(code)
        conn = self._get_conn(read_only=True)
        try:
            sql = (
                "SELECT trade_date, close, pe_ttm, pe, ps_ttm, pb, total_mv, circ_mv, turnover_rate "
                "FROM daily_basic WHERE ts_code = ? ORDER BY trade_date DESC LIMIT ?"
            )
            df = conn.execute(sql, [ts_code, limit]).fetchdf()
            return df.sort_values("trade_date").reset_index(drop=True)
        finally:
            conn.close()

    def get_stock_name(self, code: str) -> str:
        """获取股票名称。"""
        # Try PG first, fallback to DuckDB
        try:
            from data.storage.factory import get_meta_store
            store = get_meta_store("postgres")
            try:
                ts_code = self._code_to_ts_code(code)
                df = store.query(
                    "SELECT name FROM stock_basic WHERE ts_code = %s", params=(ts_code,)
                )
                if len(df) > 0:
                    return str(df.iloc[0, 0])
            finally:
                store.close()
        except Exception:
            pass
        return code

    # ═══════════════════════════════════════════════════════════════
    # Agent 专用方法（2026-07-19 新增）
    # ═══════════════════════════════════════════════════════════════

    def get_market_data(self, code: str, start_date: str | None = None,
                        end_date: str | None = None) -> pd.DataFrame:
        """获取市场数据（K 线 + 指标），兼容 analyzer.py 的调用。

        返回列: date, open, high, low, close, volume, pct_change, pe_ttm, pb, total_mv
        如果无数据返回空 DataFrame。
        """
        limit = 250
        if start_date and end_date:
            # 估算天数
            try:
                from datetime import datetime
                s = datetime.strptime(str(start_date)[:8], "%Y%m%d")
                e = datetime.strptime(str(end_date)[:8], "%Y%m%d")
                limit = max(250, (e - s).days + 1)
            except Exception:
                pass
        return self.get_kline(code, start_date=start_date, end_date=end_date, limit=limit)

    def get_fundamentals(self, code: str) -> dict[str, Any]:
        """获取基本面数据，兼容 analyzer.py 的调用。

        从 DuckDB daily_basic 最新一条 + PG fina_indicator 补充。
        返回: {profitability: {...}, valuation: {...}, growth: {...}}
        """
        ts_code = self._code_to_ts_code(code)
        result: dict[str, Any] = {
            "profitability": {},
            "valuation": {},
            "growth": {},
        }
        conn = self._get_conn(read_only=True)
        try:
            row = conn.execute(
                "SELECT pe_ttm, pe, pb, ps_ttm, total_mv, circ_mv, turnover_rate "
                "FROM daily_basic WHERE ts_code = ? ORDER BY trade_date DESC LIMIT 1",
                [ts_code],
            ).fetchone()
            if row:
                result["valuation"] = {
                    "pe_ttm": float(row[0]) if row[0] is not None else 0.0,
                    "pe": float(row[1]) if row[1] is not None else 0.0,
                    "pb": float(row[2]) if row[2] is not None else 0.0,
                    "ps_ttm": float(row[3]) if row[3] is not None else 0.0,
                    "total_mv": float(row[4]) if row[4] is not None else 0.0,
                    "circ_mv": float(row[5]) if row[5] is not None else 0.0,
                    "turnover_rate": float(row[6]) if row[6] is not None else 0.0,
                }
        finally:
            conn.close()

        # 尝试从 PG 补充财务指标（盈利能力 + 增长率）
        try:
            from data.storage.factory import get_meta_store
            store = get_meta_store("postgres")
            try:
                df = store.query(
                    "SELECT netprofit_yoy, profit_dedt, roe, roa, "
                    "       total_revenue_yoy, or_yoy, gp_yoy "
                    "FROM fina_indicator WHERE ts_code = %s "
                    "ORDER BY end_date DESC LIMIT 1",
                    params=(ts_code,),
                )
                if len(df) > 0:
                    row = df.iloc[0]
                    result["profitability"] = {
                        "roe": float(row.get("roe", 0) or 0),
                        "roa": float(row.get("roa", 0) or 0),
                        "deducted_profit": float(row.get("profit_dedt", 0) or 0),
                    }
                    result["growth"] = {
                        "revenue_yoy": float(row.get("total_revenue_yoy", 0) or 0),
                        "netprofit_yoy": float(row.get("netprofit_yoy", 0) or 0),
                        "or_yoy": float(row.get("or_yoy", 0) or 0),
                    }
            finally:
                store.close()
        except Exception:
            # PG 不可用不是致命错误
            pass

        return result

    # ═══════════════════════════════════════════════════════════════
    # 内部 helper
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _get_latest_daily_basic(conn: duckdb.DuckDBPyConnection,
                                 ts_code: str) -> dict[str, Any] | None:
        """取最新一条 daily_basic 的快照值。"""
        try:
            row = conn.execute(
                "SELECT pe_ttm, pe, pb, total_mv, circ_mv, turnover_rate "
                "FROM daily_basic WHERE ts_code = ? ORDER BY trade_date DESC LIMIT 1",
                [ts_code],
            ).fetchone()
            if row is None:
                return None
            return {
                "pe_ttm": row[0], "pe": row[1], "pb": row[2],
                "total_mv": row[3], "circ_mv": row[4], "turnover_rate": row[5],
            }
        except Exception:
            return None
