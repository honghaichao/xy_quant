"""行情视图 — get_current_data() 的实现，结构性防未来函数。

规则：
  - high_limit / low_limit = pre_close × 涨跌停比率（主板 1.10；创业板 300xxx 1.20；ST 1.05）
  - 盘前槽：last_price = pre_close，当日 OHLC 不可见
  - 开盘/盘中槽：last_price = 当槽成交价源；当日 close/high/low 仍不可见
  - 收盘槽及之后：当日全字段可见
  - paused = 当日无 bar 或 vol==0；is_st / name 来自 stock_basic
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from engine.clock import FILL_CLOSE, FILL_QUEUE_TO_OPEN, Slot
from jq_adapter.utils import get_code_part


def limit_ratio(code: str, name: str = "") -> float:
    """涨跌停比率。688/920 已在数据层排除。"""
    if "ST" in (name or "").upper():
        return 0.05
    if code.startswith("30"):
        return 0.20
    return 0.10


@dataclass
class SecurityData:
    """单只股票的当前行情快照（聚宽 current_data[code] 兼容字段）。"""

    code: str
    name: str = ""
    last_price: float = 0.0
    high_limit: float = 0.0
    low_limit: float = 0.0
    paused: bool = True
    is_st: bool = False
    day_open: float = 0.0          # 当日开盘价（开盘后可见）
    pre_close: float = 0.0
    # xy_quant 扩展：T-1 数据（盘前决策可用，无未来函数）
    total_mv: float | None = None          # T-1 总市值（万元）
    prev_change_pct: float | None = None   # T-1 涨跌幅 %
    # xy_quant 扩展：T-1 资金流（回测可用，无未来函数）
    prev_main_inflow: float | None = None      # T-1 主力净流入（万元）
    prev_main_inflow_pct: float | None = None  # T-1 主力净流入占比 %


class CurrentDataView:
    """惰性 dict-like：current_data['000001.XSHE'].last_price / .high_limit / .paused。

    bars_today=None 表示盘前视图（实盘 decide 预演）——只暴露 T-1 信息。
    """

    def __init__(
        self,
        bars_today: pd.DataFrame | None,
        bars_prev: pd.DataFrame | None,
        meta: pd.DataFrame | None,
        slot: Slot,
        slot_prices: dict[str, float] | None = None,
        fund_flow_prev: pd.DataFrame | None = None,
    ):
        self._slot = slot
        self._slot_prices = slot_prices or {}
        self._meta = meta
        self._cache: dict[str, SecurityData] = {}

        # code → 当日/昨日行 dict（避免逐次 DataFrame 查找）
        self._today: dict[str, dict] = {}
        if bars_today is not None and not bars_today.empty:
            self._today = bars_today.set_index("code").to_dict("index")
        self._prev: dict[str, dict] = {}
        if bars_prev is not None and not bars_prev.empty:
            self._prev = bars_prev.set_index("code").to_dict("index")

        # code → T-1 fund flow dict
        self._fund_flow_prev: dict[str, dict] = {}
        if fund_flow_prev is not None and not fund_flow_prev.empty:
            self._fund_flow_prev = fund_flow_prev.set_index("ts_code").to_dict("index")

    def __getitem__(self, security: str) -> SecurityData:
        code = get_code_part(security)
        if code in self._cache:
            return self._cache[code]

        name, is_st = "", False
        if self._meta is not None and code in self._meta.index:
            row = self._meta.loc[code]
            name = str(row.get("name", ""))
            is_st = bool(row.get("is_st", False))

        today = self._today.get(code)
        prev = self._prev.get(code)

        # pre_close（涨跌停基准，除权口径）：优先当日 bar 的 pre_close 字段，其次昨日 close
        pre_close = 0.0
        if today is not None and pd.notna(today.get("pre_close")):
            pre_close = float(today["pre_close"])
        elif prev is not None and pd.notna(prev.get("close")):
            pre_close = float(prev["close"])
        # T-1 实际收盘价（pre_close 在除权跳空日 != prev close）
        # parity 意图：策略选股用 T-1 标准收盘价（除权不打乱 close<9 和涨跌幅）
        prev_close = float(prev["close"]) if prev is not None and pd.notna(prev.get("close")) else pre_close

        ratio = limit_ratio(code, name)
        high_limit = round(pre_close * (1 + ratio), 2) if pre_close else 0.0
        low_limit = round(pre_close * (1 - ratio), 2) if pre_close else 0.0

        # 停牌：有当日 bar 且 vol==0 → 停牌；盘前槽用当日 bar 的 vol 字段（若今日无 bar 则暂不以停牌论处，
        # 因为可能是首日 bootstrap 缺 prev 的场景，当日 bar 的 vol 可用来判断）
        has_today_bar = today is not None
        if has_today_bar:
            paused = not today.get("vol") or float(today.get("vol") or 0) <= 0
        else:
            # 无今日数据：预测性停牌（新股、数据缺失），盘前槽保守放过让策略层自己再判
            paused = prev is not None and (not prev.get("vol") or float(prev.get("vol") or 0) <= 0)
        pre_open_view = self._slot.fill_kind == FILL_QUEUE_TO_OPEN or self._today == {}
        if pre_open_view:
            # 盘前：当日 bar 一律不可见，停牌状态由当日 bar 的 vol 字段决定（有当日 bar 且 vol>0 → 未停牌，
            # 无当日 bar → 默认未停牌，让策略层自身再作判断）
            last_price = prev_close
            day_open = 0.0
        else:
            last_price = self._slot_prices.get(code, 0.0)
            day_open = float(today["open"]) if today is not None and pd.notna(today.get("open")) else 0.0
            if not last_price:
                if self._slot.fill_kind == FILL_CLOSE and today is not None:
                    last_price = float(today.get("close") or 0.0)
                else:
                    last_price = day_open or pre_close

        data = SecurityData(
            code=code, name=name, last_price=last_price,
            high_limit=high_limit, low_limit=low_limit,
            paused=bool(paused), is_st=is_st,
            day_open=day_open, pre_close=pre_close,
            total_mv=self._prev_field(prev, "total_mv"),
            prev_change_pct=self._prev_change_pct(prev),
            prev_main_inflow=self._prev_flow_field(code, "main_inflow"),
            prev_main_inflow_pct=self._prev_flow_field(code, "main_inflow_pct"),
        )
        self._cache[code] = data
        return data

    @staticmethod
    def _prev_field(prev: dict | None, field: str) -> float | None:
        if prev is None:
            return None
        val = prev.get(field)
        return float(val) if val is not None and pd.notna(val) else None

    @staticmethod
    def _prev_change_pct(prev: dict | None) -> float | None:
        """T-1 涨跌幅 %（close vs pre_close），任一缺失返回 None。"""
        if prev is None:
            return None
        close, pre = prev.get("close"), prev.get("pre_close")
        if close is None or pre is None or pd.isna(close) or pd.isna(pre) or not pre:
            return None
        return (float(close) - float(pre)) / float(pre) * 100

    def get(self, security: str) -> SecurityData:
        return self[security]

    def get_fund_flow(self, code: str) -> dict | None:
        """查询盘中资金流（intraday_fund_flow 表，仅实盘/盘中可用）。"""
        flow = self._fund_flow_prev.get(code)
        if flow:
            return {
                "main_inflow": float(flow.get("main_inflow") or 0),
                "main_inflow_pct": float(flow.get("main_inflow_pct") or 0),
                "super_inflow": float(flow.get("super_inflow") or 0),
                "big_inflow": float(flow.get("big_inflow") or 0),
                "mid_inflow": float(flow.get("mid_inflow") or 0),
                "small_inflow": float(flow.get("small_inflow") or 0),
            }
        return None

    def _prev_flow_field(self, code: str, field: str) -> float | None:
        flow = self._fund_flow_prev.get(code)
        if flow is None:
            return None
        val = flow.get(field)
        return float(val) if val is not None and pd.notna(val) else None
