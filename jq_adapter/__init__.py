# coding=utf-8
"""
jq_adapter — 聚宽数据 API 兼容层
=================================
提供 13 个聚宽风格数据函数（委托 data/api.py）+ 代码格式工具 + 策略迁移检查器。

回测/实盘引擎在 engine/ 包（engine/backtest_engine.py, engine/live_engine.py），
策略写法见 strategies/jq/caimadama.py（真聚宽格式，零 import，API 由引擎注入）。

历史说明：曾内置 Backtrader 架构的 JQStrategy/Backtester（多股下单存在结构性缺陷），
已于 2026-07 移除，由 engine/ 包取代。
"""

from jq_adapter.data_provider import (
    get_price,
    get_bars,
    attribute_history,
    get_index_stocks,
    get_industry_stocks,
    get_concept_stocks,
    get_trade_days,
    get_all_securities,
    get_fundamentals,
    get_valuation,
    get_money_flow,
    get_billboard_list,
    get_ticks,
    get_security_info,
)
from jq_adapter.utils import (
    normalize_code,
    to_jq_code,
    get_code_part,
)

__all__ = [
    "get_price", "get_bars", "attribute_history",
    "get_index_stocks", "get_industry_stocks", "get_concept_stocks",
    "get_trade_days", "get_all_securities", "get_fundamentals",
    "get_valuation", "get_money_flow", "get_billboard_list",
    "get_ticks", "get_security_info",
    "normalize_code", "to_jq_code", "get_code_part",
]
