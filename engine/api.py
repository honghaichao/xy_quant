"""聚宽 API 命名空间构建器 — 策略文件零 import，所有函数在加载时注入。

build_namespace(engine, ctx, g) 返回 dict，engine/loader.py 将其写入策略模块命名空间。
engine 鸭子类型要求：submit_order(code, kind, amount) / register_task(func, slot, freq, ...)
/ current_data_view() / set_benchmark_code(code) / account / logger。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.clock import ScheduledTask, parse_time
from engine.context import Context, G
from jq_adapter import data_provider as dp
from jq_adapter.utils import get_code_part
from backtest.execution import load_dividend_map


# ── 聚宽风格配置对象 ───────────────────────────────────────────

@dataclass
class OrderCost:
    """聚宽 OrderCost。"""

    open_tax: float = 0.0
    close_tax: float = 0.001
    open_commission: float = 0.0003
    close_commission: float = 0.0003
    min_commission: float = 5.0


@dataclass
class FixedSlippage:
    fixed: float = 0.0


@dataclass
class PriceRelatedSlippage:
    percent: float = 0.0


class _Log:
    """聚宽 log 对象。"""

    def __init__(self, logger):
        self._logger = logger

    def info(self, *args): self._logger.info(" ".join(str(a) for a in args))
    def warning(self, *args): self._logger.warning(" ".join(str(a) for a in args))
    def warn(self, *args): self.warning(*args)
    def error(self, *args): self._logger.error(" ".join(str(a) for a in args))
    def debug(self, *args): self._logger.debug(" ".join(str(a) for a in args))
    def set_level(self, *args, **kwargs): pass  # 聚宽兼容，全局 loguru 已配置


def build_namespace(engine: Any, ctx: Context, g: G) -> dict[str, Any]:
    """构建注入策略模块的命名空间。"""

    log = _Log(engine.logger)

    # ── 交易函数（带 security，聚宽签名）────────────────────

    def order(security: str, amount: int, style=None, side="long") -> None:
        del style, side
        engine.submit_order(get_code_part(security), "amount", int(amount))

    def order_target(security: str, amount: int, style=None, side="long") -> None:
        del style, side
        engine.submit_order(get_code_part(security), "target_amount", int(amount))

    def order_value(security: str, value: float, style=None, side="long") -> None:
        del style, side
        engine.submit_order(get_code_part(security), "value", float(value))

    def order_target_value(security: str, value: float, style=None, side="long") -> None:
        del style, side
        engine.submit_order(get_code_part(security), "target_value", float(value))

    # ── 设置函数 ─────────────────────────────────────────

    def set_benchmark(security: str) -> None:
        engine.set_benchmark_code(security)

    def set_order_cost(cost: OrderCost, type: str = "stock", ref: str | None = None) -> None:
        del type, ref
        engine.account.cost.open_commission = cost.open_commission
        engine.account.cost.close_commission = cost.close_commission
        engine.account.cost.close_tax = cost.close_tax
        engine.account.cost.min_commission = cost.min_commission

    def set_slippage(slippage, type: str = "stock", ref: str | None = None) -> None:
        del type, ref
        if isinstance(slippage, FixedSlippage):
            engine.slippage_fixed = slippage.fixed
            engine.slippage_pct = 0.0
        elif isinstance(slippage, PriceRelatedSlippage):
            engine.slippage_pct = slippage.percent
            engine.slippage_fixed = 0.0
        else:
            log.warning(f"set_slippage: 不支持的类型 {type(slippage).__name__}，忽略")

    def set_option(key: str, value=None) -> None:
        # use_real_price / order_volume_ratio 等聚宽选项：吞掉并提示
        log.info(f"set_option({key!r}, {value!r}) — 本引擎忽略该选项")

    def set_universe(securities) -> None:
        del securities
        log.info("set_universe — 本引擎不需要预设 universe，忽略")

    # ── 调度注册（聚宽函数调用式）────────────────────────

    def run_daily(func, time: str = "open", reference_security: str | None = None) -> None:
        del reference_security
        engine.register_task(ScheduledTask(func=func, slot=parse_time(time), freq="daily"))

    def run_weekly(func, weekday: int = 1, time: str = "open",
                   reference_security: str | None = None) -> None:
        del reference_security
        # 聚宽 weekday 1=周一 → Python 0=周一
        engine.register_task(ScheduledTask(
            func=func, slot=parse_time(time), freq="weekly", weekday=weekday - 1))

    def run_monthly(func, monthday: int = 1, time: str = "open",
                    reference_security: str | None = None) -> None:
        del reference_security
        engine.register_task(ScheduledTask(
            func=func, slot=parse_time(time), freq="monthly", monthday=monthday))

    # ── 数据与杂项 ───────────────────────────────────────

    def get_current_data():
        return engine.current_data_view()

    def get_dividend_map(ref_date=None):
        """过去一年每股现金分红 dict[code] → 元/股（xy_quant 扩展，替代 finance.run_query）。"""
        return load_dividend_map(ref_date or ctx.current_dt.date())

    def get_intraday_flow(code: str | None = None):
        """盘中资金流查询（xy_quant 扩展）。

        实盘/盘中返回 intraday_fund_flow 表最新数据；回测返回 None。
        不传 code 则返回全市场最新快照 DataFrame。
        """
        try:
            from pathlib import Path as _Path
            import duckdb as _duckdb
            from config.settings import settings as _settings
            conn = _duckdb.connect(str(_Path(_settings.duckdb_path)), read_only=True)
            try:
                if code:
                    row = conn.execute(
                        "SELECT * FROM intraday_fund_flow WHERE ts_code=? ORDER BY fetch_time DESC LIMIT 1",
                        [code],
                    ).fetchone()
                    if row is None:
                        return None
                    cols = [c[0] for c in conn.description]
                    return dict(zip(cols, row))
                else:
                    return conn.execute(
                        "SELECT * FROM intraday_fund_flow ORDER BY fetch_time DESC"
                    ).df()
            finally:
                conn.close()
        except Exception:
            return None

    ns: dict[str, Any] = {
        # 交易
        "order": order,
        "order_target": order_target,
        "order_value": order_value,
        "order_target_value": order_target_value,
        # 设置
        "set_benchmark": set_benchmark,
        "set_order_cost": set_order_cost,
        "set_slippage": set_slippage,
        "set_option": set_option,
        "set_universe": set_universe,
        "OrderCost": OrderCost,
        "FixedSlippage": FixedSlippage,
        "PriceRelatedSlippage": PriceRelatedSlippage,
        # 调度
        "run_daily": run_daily,
        "run_weekly": run_weekly,
        "run_monthly": run_monthly,
        # 行情与杂项
        "get_current_data": get_current_data,
        "get_dividend_map": get_dividend_map,
        "get_intraday_flow": get_intraday_flow,
        "log": log,
        "g": g,
    }

    # jq_adapter 数据函数全量挂入
    for fn_name in (
        "get_price", "get_bars", "attribute_history", "get_index_stocks",
        "get_industry_stocks", "get_concept_stocks", "get_trade_days",
        "get_all_securities", "get_fundamentals", "get_valuation",
        "get_money_flow", "get_billboard_list", "get_ticks", "get_security_info",
        "get_extras", "get_industry", "get_factor_values",
    ):
        if hasattr(dp, fn_name):
            ns[fn_name] = getattr(dp, fn_name)

    # 注入聚宽 query/valuation/indicator 全局对象
    if hasattr(dp, 'query'):
        ns['query'] = dp.query
    if hasattr(dp, 'valuation'):
        ns['valuation'] = dp.valuation
    if hasattr(dp, 'indicator'):
        ns['indicator'] = dp.indicator

    return ns
