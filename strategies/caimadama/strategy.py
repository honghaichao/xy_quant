"""
菜场大妈选股法 — 纯选股逻辑（不含回测）。

由 BacktestRunner 统一调用。策略自己决定：
  - 用哪天数据选股（T-1收盘防未来函数）
  - 用什么价格执行（分钟线 / 日线open）

使用方式：
    from strategies.caimadama import CaiMaDamaStrategy
    from backtest.runner import BacktestRunner

    strategy = CaiMaDamaStrategy(top_n=5)
    strategy.load_context_data(start, end)
    runner = BacktestRunner(strategy, start=date(2026,1,1), end=date(2026,7,14))
    result = runner.run()
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from backtest.execution import load_universe_meta, load_dividend_map


class CaiMaDamaStrategy:
    """菜场大妈选股法 — 纯选股逻辑"""

    strategy_name = "菜场大妈选股法"
    strategy_type = "portfolio"
    execution_time = "minute_0931"  # 策略自己指定执行价方式

    def __init__(self, top_n: int = 5):
        self.top_n = top_n
        self._meta: pd.DataFrame | None = None
        self._div_map: dict[str, float] = {}
        self._name_map: dict[str, str] = {}

    def load_context_data(self, start: date, end: date) -> None:
        """一次性加载全市场元数据和分红数据"""
        self._meta = load_universe_meta()
        self._div_map = load_dividend_map(end)
        for code, row in self._meta.iterrows():
            self._name_map[code] = str(row["name"]) if pd.notna(row["name"]) else code

    def name_map(self) -> dict[str, str]:
        return self._name_map

    def select_stocks(self, ctx: dict[str, Any]) -> list[str]:
        """每天调用一次，返回今天要持仓的股票代码列表。

        ctx 给出全部数据，策略自己决定取哪天选股。
        菜场大妈策略取 T-1 收盘数据选股（首日取 T）。

        新增: 按 list_date/delist_date 过滤，消除幸存者偏差。
        """
        idx = ctx["current_index"]
        dates = ctx["all_dates"]
        bars = ctx["bars_by_date"]

        # 策略自己决定选股数据日期：前一天收盘，首日当天
        select_td = dates[0] if idx == 0 else dates[idx - 1]
        day_df = bars.get(select_td)

        if day_df is None or day_df.empty:
            return []

        df = day_df.copy().set_index("code")

        # 1. 正股价
        df = df[(df["close"].notna()) & (df["close"] > 0)]

        # 2. 排除 ST
        if self._meta is not None:
            st_codes = self._meta[self._meta["is_st"]].index
            df = df[~df.index.isin(st_codes)]

            # 2b. 按上市日期过滤（消除新上市股票的幸存者偏差）
            # 注意：list_date 是 DATE 类型，select_td 是 Python date，需要统一为 pd.Timestamp
            if "list_date" in self._meta.columns:
                sel_ts = pd.Timestamp(select_td)
                allowed = self._meta[
                    self._meta["list_date"].isna() | (self._meta["list_date"] <= sel_ts)
                ]
                df = df[df.index.isin(allowed.index)]

        # 3. 排除涨跌停
        if "pre_close" in df.columns:
            df["change_pct"] = (df["close"] - df["pre_close"]) / df["pre_close"].replace(0, np.nan) * 100
            df = df[(df["change_pct"] > -9.5) & (df["change_pct"] < 9.5)]

        # 4. 股价 < 9 元
        df = df[df["close"] < 9]

        if df.empty:
            return []

        # 5. 高股息：取前 25%
        if self._div_map:
            df["dividend"] = df.index.map(self._div_map).fillna(0)
            df["div_yield"] = df["dividend"] / df["close"].replace(0, np.nan)
            df = df.dropna(subset=["div_yield"])
            if len(df) > 20:
                top_k = max(10, int(len(df) * 0.25))
                df = df.nlargest(top_k, "div_yield")

        # 6. 按市值最小排序，取 top_n
        if "total_mv" in df.columns:
            df = df.sort_values("total_mv")
        else:
            df = df.sort_values("close")

        return list(df.head(self.top_n).index)
