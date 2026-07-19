"""AKShare 数据源适配器。"""

from __future__ import annotations

from datetime import date, datetime
from importlib import import_module
from typing import Any, Final

import pandas as pd

from config.settings import settings
from data.source.tushare_source import TushareSource
from interfaces.data_source import IDataSource
from utils.calendar import ensure_date
from utils.exception import ConfigError, DataSourceError
from utils.rate_limiter import TokenBucketRateLimiter
from utils.retry import retry_on

_AKSHARE_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        "daily_bar",
        "minute_bar",
        "adj_factor",
        "daily_basic",
        "index_daily",
        "limit_pool",
        "stock_basic",
        "trade_calendar",
        "stock_suspend",
        "income",
        "balancesheet",
        "cashflow",
        "fina_indicator",
        "dividend",
        "top_list",
        "margin_detail",
        "stk_holdertrade",
        "hk_hold",
        "concept_money_flow",
        "industry_money_flow",
        "stock_money_flow",
        "concept_list",
        "concept_member",
        "industry_list",
        "industry_member",
        "index_weight",
    }
)
_LIMIT_POOL_METHODS: Final[dict[str, str]] = {
    "U": "stock_zt_pool_em",
    "D": "stock_dt_pool_em",
}
_MINUTE_BAR_COLUMN_MAP: Final[dict[str, str]] = {
    "时间": "datetime",
    "日期": "datetime",
    "day": "datetime",
    "开盘": "open",
    "open": "open",
    "最高": "high",
    "high": "high",
    "最低": "low",
    "low": "low",
    "收盘": "close",
    "close": "close",
    "成交量": "vol",
    "volume": "vol",
    "成交额": "amount",
    "amount": "amount",
}
_MINUTE_FREQ_MAP: Final[dict[str, str]] = {
    "1min": "1",
    "5min": "5",
    "15min": "15",
    "30min": "30",
    "60min": "60",
}
_DAILY_BAR_COLUMN_MAP: Final[dict[str, str]] = {
    "日期": "trade_date",
    "股票代码": "ts_code",
    "代码": "ts_code",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "vol",
    "成交额": "amount",
    "涨跌额": "change",
    "涨跌幅": "pct_chg",
}
_LIMIT_POOL_COLUMN_MAP: Final[dict[str, str]] = {
    "代码": "ts_code",
    "名称": "name",
    "最新价": "close",
    "涨跌幅": "pct_chg",
    "成交额": "amount",
    "封板资金": "fd_amount",
    "流通市值": "float_mv",
    "总市值": "total_mv",
    "换手率": "turnover_ratio",
    "首次封板时间": "first_time",
    "最后封板时间": "last_time",
    "炸板次数": "open_times",
    "涨停统计": "up_stat",
    "连板数": "limit_times",
    "所属行业": "industry",
}
_CONCEPT_MONEY_FLOW_COLUMN_MAP: Final[dict[str, str]] = {
    "行业": "concept_name",
    "行业-涨跌幅": "pct_chg",
    "净额": "main_inflow",
}
_INDUSTRY_MONEY_FLOW_COLUMN_MAP: Final[dict[str, str]] = {
    "行业": "industry_name",
    "行业-涨跌幅": "pct_chg",
    "净额": "main_inflow",
}
_STOCK_MONEY_FLOW_COLUMN_MAP: Final[dict[str, str]] = {
    "日期": "trade_date",
    "收盘价": "close",
    "涨跌幅": "pct_chg",
    "主力净流入-净额": "main_inflow",
    "主力净流入-净占比": "main_inflow_pct",
    "超大单净流入-净额": "super_inflow",
    "大单净流入-净额": "big_inflow",
    "中单净流入-净额": "mid_inflow",
    "小单净流入-净额": "small_inflow",
}
_HK_HOLD_COLUMN_MAP: Final[dict[str, str]] = {
    "日期": "trade_date",
    "代码": "ts_code",
    "股票代码": "ts_code",
    "名称": "name",
    "持股数量": "vol",
    "持股数": "vol",
    "今日持股-股数": "vol",
    "持股占流通股比": "ratio",
    "持股占比": "ratio",
    "今日持股-占流通股比": "ratio",
    "交易所": "exchange",
    "市场": "exchange",
}


class AKShareSource(IDataSource):
    """AKShare-backed implementation of the market data source interface."""

    name = "akshare"

    def __init__(self, client: Any | None = None, tushare_fallback: Any | None = None) -> None:
        self._client = client or _create_default_client()
        self._owns_client = client is None
        self._tushare_fallback = tushare_fallback
        per_second = max(settings.akshare_rate_limit_per_min / 60, 1 / 60)
        self._rate_limiter = TokenBucketRateLimiter(
            capacity=settings.akshare_rate_limit_per_min,
            refill_rate=per_second,
        )

    def fetch_daily_bar(
        self,
        ts_code: str | list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        return self._call(
            "stock_zh_a_hist",
            symbol=_join_symbols(ts_code),
            period="daily",
            start_date=_format_ymd(start_date),
            end_date=_format_ymd(end_date),
            adjust="",
        )

    def fetch_minute_bar(
        self,
        ts_code: str,
        start_date: date,
        end_date: date,
        freq: str = "1min",
    ) -> pd.DataFrame:
        hist_kwargs = {
            "symbol": _normalize_symbol(ts_code),
            "period": _normalize_minute_period(freq),
            "start_date": _format_minute_start(start_date),
            "end_date": _format_minute_end(end_date),
            "adjust": "",
        }
        try:
            return self._call("stock_zh_a_hist_min_em", **hist_kwargs)
        except DataSourceError as hist_error:
            if "stock_zh_a_minute" not in vars(self._client):
                if self._tushare_fallback is None and not self._owns_client:
                    raise hist_error
                return self._fetch_minute_bar_from_tushare(ts_code, start_date, end_date, freq)
            fallback_frame = self._call(
                "stock_zh_a_minute",
                symbol=_normalize_sina_symbol(ts_code),
                period=_normalize_minute_period(freq),
                adjust="",
            )
            if fallback_frame.empty:
                return self._fetch_minute_bar_from_tushare(ts_code, start_date, end_date, freq)
            if "datetime" not in fallback_frame.columns:
                return self._fetch_minute_bar_from_tushare(ts_code, start_date, end_date, freq)
            start_bound = pd.to_datetime(hist_kwargs["start_date"])
            end_bound = pd.to_datetime(hist_kwargs["end_date"])
            mask = (fallback_frame["datetime"] >= start_bound) & (fallback_frame["datetime"] <= end_bound)
            filtered = fallback_frame.loc[mask].copy()
            if filtered.empty:
                return self._fetch_minute_bar_from_tushare(ts_code, start_date, end_date, freq)
            return filtered

    def fetch_adj_factor(
        self,
        ts_code: str | list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        symbol = _normalize_symbol(_first_symbol(ts_code) or "")
        return self._call(
            "stock_zh_a_daily",
            symbol=symbol,
            start_date=_format_ymd(start_date),
            end_date=_format_ymd(end_date),
            adjust="qfq-factor",
        )

    def fetch_daily_basic(
        self,
        ts_code: str | list[str] | None = None,
        trade_date: date | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        _ = start_date, end_date
        symbol = _normalize_symbol(_first_symbol(ts_code) or "")
        return self._call(
            "stock_a_indicator_lg",
            symbol=symbol,
            trade_date=_format_ymd(trade_date),
        )

    def fetch_index_daily(
        self,
        ts_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        return self._call(
            "index_zh_a_hist",
            symbol=_normalize_symbol(ts_code),
            period="daily",
            start_date=_format_ymd(start_date),
            end_date=_format_ymd(end_date),
        )

    def fetch_limit_pool(self, trade_date: date, kind: str = "U") -> pd.DataFrame:
        method_name = _LIMIT_POOL_METHODS.get(kind.upper())
        if method_name is None:
            raise DataSourceError(f"Unsupported limit pool kind: {kind}")
        return self._call(method_name, date=_format_ymd(trade_date))

    def fetch_stock_basic(self) -> pd.DataFrame:
        return self._call("stock_info_a_code_name")

    def fetch_trade_calendar(self, start_date: date, end_date: date) -> pd.DataFrame:
        _ = start_date, end_date
        return self._call("tool_trade_date_hist_sina")

    def fetch_stock_suspend(
        self, trade_date: date | None = None, ts_code: str | None = None
    ) -> pd.DataFrame:
        _ = ts_code
        return self._call("stock_tfp_em", date=_format_ymd(trade_date))

    def fetch_income(
        self, ts_code: str, start_date: date | None = None, end_date: date | None = None
    ) -> pd.DataFrame:
        _ = start_date, end_date
        return self._call(
            "stock_financial_report_sina",
            stock=_normalize_symbol(ts_code),
            symbol="利润表",
        )

    def fetch_balancesheet(
        self, ts_code: str, start_date: date | None = None, end_date: date | None = None
    ) -> pd.DataFrame:
        _ = start_date, end_date
        return self._call(
            "stock_financial_report_sina",
            stock=_normalize_symbol(ts_code),
            symbol="资产负债表",
        )

    def fetch_cashflow(
        self, ts_code: str, start_date: date | None = None, end_date: date | None = None
    ) -> pd.DataFrame:
        _ = start_date, end_date
        return self._call(
            "stock_financial_report_sina",
            stock=_normalize_symbol(ts_code),
            symbol="现金流量表",
        )

    def fetch_fina_indicator(
        self, ts_code: str, start_date: date | None = None, end_date: date | None = None
    ) -> pd.DataFrame:
        _ = start_date, end_date
        return self._call(
            "stock_financial_analysis_indicator",
            symbol=_normalize_symbol(ts_code),
        )

    def fetch_dividend(self, ts_code: str) -> pd.DataFrame:
        return self._call("stock_dividents_cninfo", symbol=_normalize_symbol(ts_code))

    def fetch_top_list(self, trade_date: date) -> pd.DataFrame:
        trade_day = _format_ymd(trade_date)
        return self._call("stock_lhb_detail_em", start_date=trade_day, end_date=trade_day)

    def fetch_margin_detail(self, trade_date: date) -> pd.DataFrame:
        return self._call("stock_margin_detail_sse", date=_format_ymd(trade_date))

    def fetch_stk_holdertrade(
        self, ts_code: str | None = None, ann_date: date | None = None
    ) -> pd.DataFrame:
        _ = ts_code
        return self._call("stock_ggcg_em", symbol="全部", date=_format_ymd(ann_date))

    def fetch_hk_hold(
        self, trade_date: date | None = None, ts_code: str | None = None
    ) -> pd.DataFrame:
        _ = ts_code
        frame = self._call("stock_hsgt_hold_stock_em", market="北向")
        return _normalize_hk_hold_frame(frame, {"date": _format_ymd(trade_date)})

    def fetch_concept_money_flow(self, trade_date: date) -> pd.DataFrame:
        frame = self._call("stock_fund_flow_concept", symbol="即时")
        return _normalize_concept_money_flow_frame(frame, {"trade_date": trade_date})

    def fetch_industry_money_flow(self, trade_date: date) -> pd.DataFrame:
        frame = self._call("stock_fund_flow_industry", symbol="即时")
        return _normalize_industry_money_flow_frame(frame, {"trade_date": trade_date})

    def fetch_stock_money_flow(self, trade_date: date) -> pd.DataFrame:
        frame = self._call(
            "stock_individual_fund_flow",
            stock=_fallback_stock_for_money_flow(trade_date),
        )
        return _normalize_stock_money_flow_frame(frame, {"trade_date": trade_date})

    def fetch_concept_list(self) -> pd.DataFrame:
        return self._call("stock_board_concept_name_em")

    def fetch_concept_member(self, concept_code: str) -> pd.DataFrame:
        return self._call("stock_board_concept_cons_em", symbol=concept_code)

    def fetch_industry_list(self) -> pd.DataFrame:
        return self._call("stock_board_industry_name_em")

    def fetch_industry_member(self, industry_code: str) -> pd.DataFrame:
        return self._call("stock_board_industry_cons_em", symbol=industry_code)

    def fetch_index_weight(
        self, index_code: str, trade_date: date | None = None
    ) -> pd.DataFrame:
        _ = trade_date
        return self._call("index_stock_cons_weight_csindex", symbol=_normalize_symbol(index_code))

    def supports(self, capability: str) -> bool:
        """Return whether this source advertises the requested capability."""
        return capability in _AKSHARE_CAPABILITIES

    @retry_on(DataSourceError)
    def _call(self, method_name: str, **kwargs: Any) -> pd.DataFrame:
        if not self._rate_limiter.consume():
            raise DataSourceError(f"AKShare rate limit exceeded before calling {method_name}")
        method = getattr(self._client, method_name)
        try:
            frame = method(**_drop_none(kwargs))
            return _normalize_frame(method_name, frame, kwargs)
        except Exception as exc:
            raise DataSourceError(str(exc)) from exc

    def _fetch_minute_bar_from_tushare(
        self,
        ts_code: str,
        start_date: date,
        end_date: date,
        freq: str,
    ) -> pd.DataFrame:
        if self._tushare_fallback is None:
            self._tushare_fallback = TushareSource()
        return self._tushare_fallback.fetch_minute_bar(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            freq=freq,
        )


def _create_default_client() -> Any:
    try:
        ak = import_module("akshare")
    except ImportError as exc:  # pragma: no cover
        raise ConfigError("akshare package is not installed") from exc
    return ak


def _normalize_symbol(ts_code: str) -> str:
    return ts_code.split(".", maxsplit=1)[0]


def _join_symbols(ts_code: str | list[str] | None) -> str | None:
    if ts_code is None:
        return None
    if isinstance(ts_code, list):
        return ",".join(_normalize_symbol(code) for code in ts_code)
    return _normalize_symbol(ts_code)


def _first_symbol(ts_code: str | list[str] | None) -> str | None:
    if ts_code is None:
        return None
    if isinstance(ts_code, list):
        return ts_code[0] if ts_code else None
    return ts_code


def _normalize_minute_period(freq: str) -> str:
    period = _MINUTE_FREQ_MAP.get(freq)
    if period is None:
        raise DataSourceError(f"Unsupported minute frequency: {freq}")
    return period


def _format_ymd(value: date | None) -> str | None:
    if value is None:
        return None
    normalized = ensure_date(value)
    return normalized.strftime("%Y%m%d")


def _format_minute_start(value: date) -> str:
    return datetime.combine(ensure_date(value), datetime.min.time()).replace(hour=9, minute=30).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def _format_minute_end(value: date) -> str:
    return datetime.combine(ensure_date(value), datetime.min.time()).replace(hour=15).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def _fallback_stock_for_money_flow(trade_date: date) -> str:
    _ = trade_date
    return "000001"


def _drop_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _normalize_frame(method_name: str, frame: pd.DataFrame, kwargs: dict[str, Any]) -> pd.DataFrame:
    if frame.empty:
        return frame

    normalizer: Any | None = None
    if method_name == "stock_zh_a_hist":
        normalizer = _normalize_daily_bar_frame
    elif method_name in {"stock_zh_a_hist_min_em", "stock_zh_a_minute"}:
        normalizer = _normalize_minute_bar_frame
    elif method_name in _LIMIT_POOL_METHODS.values():
        normalizer = _normalize_limit_pool_frame
    elif method_name == "stock_hsgt_hold_stock_em":
        normalizer = _normalize_hk_hold_frame
    elif method_name == "stock_fund_flow_concept":
        normalizer = _normalize_concept_money_flow_frame
    elif method_name == "stock_fund_flow_industry":
        normalizer = _normalize_industry_money_flow_frame
    elif method_name == "stock_individual_fund_flow":
        normalizer = _normalize_stock_money_flow_frame

    return frame if normalizer is None else normalizer(frame, kwargs)


def _normalize_daily_bar_frame(frame: pd.DataFrame, kwargs: dict[str, Any]) -> pd.DataFrame:
    normalized = frame.rename(columns=_DAILY_BAR_COLUMN_MAP).copy()
    if "trade_date" in normalized.columns:
        normalized["trade_date"] = pd.to_datetime(normalized["trade_date"]).dt.date
    if "ts_code" in normalized.columns:
        normalized["ts_code"] = normalized["ts_code"].map(_normalize_ts_code)
    elif symbol := kwargs.get("symbol"):
        normalized["ts_code"] = _with_exchange_suffix(str(symbol))
    columns = [
        "ts_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "change",
        "pct_chg",
        "vol",
        "amount",
    ]
    return _select_present_columns(normalized, columns)



def _normalize_minute_bar_frame(frame: pd.DataFrame, kwargs: dict[str, Any]) -> pd.DataFrame:
    normalized = frame.rename(columns=_MINUTE_BAR_COLUMN_MAP).copy()
    if "datetime" in normalized.columns:
        normalized["datetime"] = pd.to_datetime(normalized["datetime"])
    symbol = kwargs.get("symbol")
    if symbol is not None:
        symbol_text = str(symbol)
        normalized["ts_code"] = (
            _normalize_ts_code(symbol_text)
            if not symbol_text.startswith(("sh", "sz", "bj"))
            else _with_exchange_suffix(symbol_text[2:])
        )
    elif "ts_code" not in normalized.columns:
        normalized["ts_code"] = None
    if "freq" not in normalized.columns:
        normalized["freq"] = _minute_freq_from_period(kwargs.get("period"))
    start_value = kwargs.get("start_date")
    end_value = kwargs.get("end_date")
    if "datetime" in normalized.columns and (start_value is not None or end_value is not None):
        mask = pd.Series(True, index=normalized.index)
        if start_value is not None:
            mask &= normalized["datetime"] >= pd.to_datetime(start_value)
        if end_value is not None:
            mask &= normalized["datetime"] <= pd.to_datetime(end_value)
        normalized = normalized.loc[mask].copy()
    columns = ["ts_code", "datetime", "freq", "open", "high", "low", "close", "vol", "amount"]
    return _select_present_columns(normalized, columns)


def _normalize_limit_pool_frame(frame: pd.DataFrame, kwargs: dict[str, Any]) -> pd.DataFrame:
    normalized = frame.rename(columns=_LIMIT_POOL_COLUMN_MAP).copy()
    if "ts_code" in normalized.columns:
        normalized["ts_code"] = normalized["ts_code"].map(_normalize_ts_code)
    trade_date = kwargs.get("date")
    if trade_date:
        normalized.insert(0, "trade_date", pd.to_datetime(str(trade_date), format="%Y%m%d").date())
    columns = [
        "trade_date",
        "ts_code",
        "name",
        "close",
        "pct_chg",
        "amount",
        "limit_amount",
        "float_mv",
        "total_mv",
        "turnover_ratio",
        "fd_amount",
        "first_time",
        "last_time",
        "open_times",
        "up_stat",
        "limit_times",
        "limit",
        "industry",
    ]
    return _select_present_columns(normalized, columns)


def _normalize_hk_hold_frame(frame: pd.DataFrame, kwargs: dict[str, Any]) -> pd.DataFrame:
    normalized = frame.rename(columns=_HK_HOLD_COLUMN_MAP).copy()
    if "ts_code" in normalized.columns:
        normalized["ts_code"] = normalized["ts_code"].map(_normalize_ts_code)
    if "exchange" not in normalized.columns and "ts_code" in normalized.columns:
        normalized["exchange"] = normalized["ts_code"].map(_exchange_from_ts_code)
    elif "exchange" in normalized.columns and "ts_code" in normalized.columns:
        normalized["exchange"] = normalized["exchange"].fillna(normalized["ts_code"].map(_exchange_from_ts_code))
    if "name" in normalized.columns:
        normalized["name"] = normalized["name"].astype("string").str.slice(0, 50)
    trade_date = kwargs.get("date")
    if trade_date and "trade_date" not in normalized.columns:
        normalized.insert(0, "trade_date", pd.to_datetime(str(trade_date), format="%Y%m%d").date())
    columns = ["trade_date", "ts_code", "name", "vol", "ratio", "exchange"]
    return _select_present_columns(normalized, columns)


def _exchange_from_ts_code(ts_code: Any) -> str | None:
    if ts_code is None:
        return None
    text = str(ts_code).strip().upper()
    if not text:
        return None
    if "." in text:
        return text.rsplit(".", maxsplit=1)[-1]
    if text.startswith(("6", "9")):
        return "SH"
    return "SZ"


def _normalize_concept_money_flow_frame(frame: pd.DataFrame, kwargs: dict[str, Any]) -> pd.DataFrame:
    normalized = frame.rename(columns=_CONCEPT_MONEY_FLOW_COLUMN_MAP).copy()
    trade_date = kwargs.get("trade_date")
    if trade_date is not None:
        normalized.insert(0, "trade_date", ensure_date(trade_date))
    normalized["concept_code"] = normalized["concept_name"]
    for column in ("main_inflow_pct", "super_inflow", "big_inflow", "mid_inflow", "small_inflow"):
        normalized[column] = None
    columns = [
        "trade_date",
        "concept_code",
        "concept_name",
        "pct_chg",
        "main_inflow",
        "main_inflow_pct",
        "super_inflow",
        "big_inflow",
        "mid_inflow",
        "small_inflow",
    ]
    return _select_present_columns(normalized, columns)


def _normalize_industry_money_flow_frame(frame: pd.DataFrame, kwargs: dict[str, Any]) -> pd.DataFrame:
    normalized = frame.rename(columns=_INDUSTRY_MONEY_FLOW_COLUMN_MAP).copy()
    trade_date = kwargs.get("trade_date")
    if trade_date is not None:
        normalized.insert(0, "trade_date", ensure_date(trade_date))
    normalized["industry_code"] = normalized["industry_name"]
    for column in ("main_inflow_pct", "super_inflow", "big_inflow", "mid_inflow", "small_inflow"):
        normalized[column] = None
    columns = [
        "trade_date",
        "industry_code",
        "industry_name",
        "pct_chg",
        "main_inflow",
        "main_inflow_pct",
        "super_inflow",
        "big_inflow",
        "mid_inflow",
        "small_inflow",
    ]
    return _select_present_columns(normalized, columns)


def _normalize_stock_money_flow_frame(frame: pd.DataFrame, kwargs: dict[str, Any]) -> pd.DataFrame:
    normalized = frame.rename(columns=_STOCK_MONEY_FLOW_COLUMN_MAP).copy()
    if "trade_date" in normalized.columns:
        normalized["trade_date"] = pd.to_datetime(normalized["trade_date"]).dt.date
    stock = kwargs.get("stock")
    if stock is not None:
        normalized["ts_code"] = _with_exchange_suffix(str(stock))
    if "name" not in normalized.columns:
        normalized["name"] = None
    columns = [
        "trade_date",
        "ts_code",
        "name",
        "pct_chg",
        "main_inflow",
        "main_inflow_pct",
        "super_inflow",
        "big_inflow",
        "mid_inflow",
        "small_inflow",
    ]
    return _select_present_columns(normalized, columns)


def _normalize_ts_code(value: Any) -> Any:
    if not isinstance(value, str) or "." in value:
        return value
    return _with_exchange_suffix(value)


def _normalize_sina_symbol(value: str) -> str:
    text = value.strip().lower()
    if "." in text:
        code, exchange = text.split(".", maxsplit=1)
        return f"{exchange}{code}"
    if text.startswith(("sh", "sz", "bj")):
        return text
    if text[:1] in {"6", "9"}:
        return f"sh{text}"
    return f"sz{text}"


def _minute_freq_from_period(period: Any) -> str | None:
    for freq, mapped in _MINUTE_FREQ_MAP.items():
        if mapped == period:
            return freq
    return None


def _with_exchange_suffix(symbol: str) -> str:
    if symbol.startswith(("600", "601", "603", "605", "688", "689", "900", "730")):
        return f"{symbol}.SH"
    if symbol.startswith(("000", "001", "002", "003", "300", "301", "200")):
        return f"{symbol}.SZ"
    if symbol.startswith(("430", "440", "830", "831", "832", "833", "835", "836", "837", "838", "839", "870", "871", "872", "873", "874", "875", "876", "877", "878", "879", "880", "881", "882", "883", "884", "885", "886", "887", "888", "889")):
        return f"{symbol}.BJ"
    return f"{symbol}.SZ"


def _select_present_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    return frame[[column for column in columns if column in frame.columns]].copy()
