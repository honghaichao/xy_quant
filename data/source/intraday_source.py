"""盘中实时数据采集器 - 基于 AKShare 封装。

不实现 IDataSource 接口（盘中数据源仅此一家，无需抽象）。

Usage:
    from data.source.intraday_source import IntradayFetcher
    fetcher = IntradayFetcher()
    spot = fetcher.fetch_spot()           # 全市场实时快照
    flow = fetcher.fetch_fund_flow()      # 个股资金流(今日)
    sector = fetcher.fetch_sector_flow()  # 行业资金流(今日)
"""

from __future__ import annotations

import time
from datetime import datetime

import pandas as pd

from utils.logger import get_logger
from utils.retry import retry_on

logger = get_logger("intraday_source")

_RETRY = retry_on(Exception, attempts=3, min_wait=10, max_wait=60)

# ── rate limit helpers ──────────────────────────────────────────
_MIN_INTERVAL = 3.0  # seconds between AKShare calls


class IntradayFetcher:
    """AKShare-based intraday data fetcher with rate limiting."""

    def __init__(self) -> None:
        self._last_call = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < _MIN_INTERVAL:
            time.sleep(_MIN_INTERVAL - elapsed)
        self._last_call = time.monotonic()

    # ── spot snapshot ─────────────────────────────────────────

    @_RETRY
    def fetch_spot(self) -> pd.DataFrame:
        """全市场实时行情快照 — 腾讯财经 API (免费, 无 IP 限制)。"""
        import re
        import time as _time

        import duckdb
        import requests
        from config.settings import settings

        self._throttle()

        # Get stock list from DB
        conn = duckdb.connect(str(settings.duckdb_path), read_only=True)
        try:
            codes = [
                row[0] for row in
                conn.execute(
                    "SELECT DISTINCT ts_code FROM daily_bar "
                    "WHERE trade_date = (SELECT MAX(trade_date) FROM daily_bar)"
                ).fetchall()
            ]
        finally:
            conn.close()

        # Build Tencent format: sh600030, sz000001, bj920xxx
        qt_codes: list[str] = []
        for c in codes:
            bare = c.split(".")[0]
            if c.endswith(".SH"):
                qt_codes.append(f"sh{bare}")
            elif c.endswith(".BJ"):
                qt_codes.append(f"bj{bare}")
            else:
                qt_codes.append(f"sz{bare}")

        records: list[dict] = []
        now = datetime.now()
        batch_size = 200

        for i in range(0, len(qt_codes), batch_size):
            batch = qt_codes[i : i + batch_size]
            url = "http://qt.gtimg.cn/q=" + ",".join(batch)
            try:
                r = requests.get(url, timeout=60)
                text = r.content.decode("gbk", errors="replace")
                for m in re.finditer(r"\"(.*?)\"", text):
                    parts = m.group(1).split("~")
                    if len(parts) < 40:
                        continue
                    try:
                        pre = float(parts[4]) if parts[4] else 0.0
                        close = float(parts[3]) if parts[3] else 0.0
                        records.append({
                            "ts_code": parts[2],
                            "name": parts[1],
                            "close": close,
                            "pre_close": pre,
                            "open": float(parts[5]) if parts[5] else 0.0,
                            "volume": float(parts[6]) if parts[6] else 0.0,
                            "pct_chg": round((close - pre) / pre * 100, 2) if pre > 0 else 0.0,
                            "high": float(parts[33]) if parts[33] else 0.0,
                            "low": float(parts[34]) if parts[34] else 0.0,
                            "amount": float(parts[37]) if parts[37] else 0.0,
                            "turnover_rate": float(parts[38]) if parts[38] else 0.0,
                            "pe": float(parts[39]) if parts[39] else 0.0,
                            "fetch_time": now,
                        })
                    except (ValueError, IndexError):
                        continue
            except Exception as e:
                logger.warning(f"Tencent batch {i}: {e}")
                _time.sleep(1)
                continue
            _time.sleep(0.1)  # polite to server

        logger.info(f"fetch_spot: {len(records)} stocks from Tencent")
        return pd.DataFrame(records)

    # ── fund flow ─────────────────────────────────────────────

    @_RETRY
    def fetch_fund_flow_rank(self) -> pd.DataFrame:
        """个股资金流排名(今日) — AKShare stock_individual_fund_flow_rank。"""
        import akshare as ak

        self._throttle()
        raw = ak.stock_individual_fund_flow_rank(indicator="今日")
        if raw is None or raw.empty:
            logger.warning("fetch_fund_flow_rank returned empty")
            return pd.DataFrame()

        df = raw.copy()
        col_map = {
            "代码": "ts_code", "名称": "name", "最新价": "close",
            "涨跌幅": "pct_chg",
            "今日主力净流入-净额": "main_inflow",
            "今日主力净流入-净占比": "main_inflow_pct",
            "今日超大单净流入-净额": "super_inflow",
            "今日大单净流入-净额": "big_inflow",
            "今日中单净流入-净额": "mid_inflow",
            "今日小单净流入-净额": "small_inflow",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        df["fetch_time"] = datetime.now()
        keep = [c for c in col_map.values() if c in df.columns] + ["fetch_time"]
        return df[keep]

    @_RETRY
    def fetch_sector_fund_flow(self, indicator: str = "今日") -> pd.DataFrame:
        """行业+概念资金流排名(今日) — AKShare stock_sector_fund_flow_rank。

        Returns concatenated DataFrame with sector_type column.
        """
        import akshare as ak

        frames = []
        for stype in ["行业资金流", "概念资金流"]:
            self._throttle()
            try:
                raw = ak.stock_sector_fund_flow_rank(indicator=indicator, sector_type=stype)
                if raw is not None and not raw.empty:
                    r = raw.copy()
                    col_map = {
                        "名称": "name", "今日涨跌幅": "pct_chg",
                        "今日主力净流入-净额": "main_inflow",
                        "今日主力净流入-净占比": "main_inflow_pct",
                        "今日超大单净流入-净额": "super_inflow",
                        "今日大单净流入-净额": "big_inflow",
                        "今日中单净流入-净额": "mid_inflow",
                        "今日小单净流入-净额": "small_inflow",
                        "今日主力净流入最大股": "top_stock",
                    }
                    r = r.rename(columns={k: v for k, v in col_map.items() if k in r.columns})
                    r["sector_type"] = stype.replace("资金流", "")  # "行业" / "概念"
                    r["fetch_time"] = datetime.now()
                    keep = [c for c in set(list(col_map.values()) + ["sector_type", "fetch_time"]) if c in r.columns]
                    frames.append(r[keep])
            except Exception as e:
                logger.warning(f"fetch_sector_fund_flow({stype}): {e}")

        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    # ── minute K-line (today) ─────────────────────────────────

    @_RETRY
    def fetch_minute_today(self, code: str, period: str = "1") -> pd.DataFrame:
        """当日分钟K线 (1min) — AKShare stock_zh_a_hist_min_em。"""
        import akshare as ak

        self._throttle()
        today_str = datetime.now().strftime("%Y-%m-%d")
        raw = ak.stock_zh_a_hist_min_em(
            symbol=code,
            start_date=f"{today_str} 09:30:00",
            end_date=f"{today_str} 15:00:00",
            period=period,
        )
        if raw is None or raw.empty:
            return pd.DataFrame()

        df = raw.copy()
        col_map = {"时间": "datetime", "开盘": "open", "收盘": "close",
                    "最高": "high", "最低": "low", "成交量": "volume", "成交额": "amount"}
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        df["ts_code"] = code
        df["freq"] = f"{period}min"
        return df

    @_RETRY
    def fetch_tick(self, code: str) -> pd.DataFrame:
        """当日分笔成交 (tick) — AKShare stock_zh_a_tick_tx_js。"""
        import akshare as ak

        self._throttle()
        symbol = f"sz{code}" if code.startswith(("0", "3")) else f"sh{code}"
        raw = ak.stock_zh_a_tick_tx_js(symbol=symbol)
        if raw is None or raw.empty:
            return pd.DataFrame()

        df = raw.copy()
        col_map = {"成交时间": "time", "成交价格": "price",
                    "成交量": "volume", "成交金额": "amount", "性质": "side"}
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        df["ts_code"] = code
        return df

    # ── convenience ───────────────────────────────────────────

    def fetch_all_flow(self) -> dict[str, pd.DataFrame]:
        """Fetch all flow data at once."""
        result = {}
        try:
            result["stock_flow"] = self.fetch_fund_flow_rank()
        except Exception as e:
            logger.error(f"stock_flow failed: {e}")
        try:
            result["sector_flow"] = self.fetch_sector_fund_flow()
        except Exception as e:
            logger.error(f"sector_flow failed: {e}")
        try:
            result["spot"] = self.fetch_spot()
        except Exception as e:
            logger.error(f"spot failed: {e}")
        return result
