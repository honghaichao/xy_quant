"""统一数据 API，聚宽风格。所有上层模块只通过此 API 取数。"""

from __future__ import annotations

from datetime import date
from typing import Any, cast

import pandas as pd

from data.storage.duckdb_store import DUCKDB_MARKET_TABLES
from data.storage.factory import get_market_store, get_meta_store
from data.storage.pg_store import POSTGRES_META_TABLES
from utils.calendar import ensure_date

MARKET_STORE_NAME = "duckdb"
META_STORE_NAME = "postgres"
_DAILY_PRICE_FREQUENCIES = {"daily", "1d", "d"}
_MINUTE_PRICE_FREQUENCIES = {"1min", "1m", "5min", "5m", "15min", "15m", "30min", "30m", "60min", "60m", "120min", "120m"}
_MONEY_FLOW_TABLES = {
    "stock": "stock_money_flow",
    "concept": "concept_money_flow",
    "industry": "industry_money_flow",
}


def get_price(
    security: str | list[str],
    start_date: str | date,
    end_date: str | date,
    frequency: str = "daily",
    fields: list[str] | None = None,
    fq: str = "pre",
    skip_paused: bool = False,
) -> pd.DataFrame:
    """获取行情数据。"""
    del skip_paused
    _validate_fq(fq)

    start = ensure_date(start_date)
    end = ensure_date(end_date)
    frame = _load_price_frame(security, frequency)
    codes = _ensure_code_list(security)
    date_column = _price_date_column(frequency)

    filtered = frame.copy()
    if codes:
        filtered = filtered[filtered["ts_code"].isin(codes)]

    if date_column == "trade_date":
        filtered[date_column] = pd.to_datetime(filtered[date_column])
        filtered = filtered[
            (filtered[date_column].dt.date >= start) & (filtered[date_column].dt.date <= end)
        ]
    else:
        filtered[date_column] = pd.to_datetime(filtered[date_column])
        filtered = filtered[
            (filtered[date_column].dt.date >= start) & (filtered[date_column].dt.date <= end)
        ]
        frequency_alias = _normalize_frequency(frequency)
        if "freq" in filtered.columns:
            filtered = filtered[filtered["freq"] == frequency_alias]

    sort_columns = ["ts_code", date_column]
    filtered = filtered.sort_values(sort_columns).reset_index(drop=True)
    return _select_fields(filtered, fields)


def get_fundamentals(
    table: str,
    ts_code: str | list[str],
    start_date: date | None = None,
    end_date: date | None = None,
    fields: list[str] | None = None,
) -> pd.DataFrame:
    """获取基本面数据。"""
    frame = _query_meta_table(table)
    codes = _ensure_code_list(ts_code)
    filtered = frame.copy()

    if codes and "ts_code" in filtered.columns:
        filtered = filtered[filtered["ts_code"].isin(codes)]

    date_column = _infer_date_column(filtered, preferred=("end_date", "trade_date", "ann_date"))
    if date_column is not None:
        filtered = _filter_by_date_range(filtered, date_column, start_date, end_date)
        filtered = filtered.sort_values(["ts_code", date_column]).reset_index(drop=True)
    elif "ts_code" in filtered.columns:
        filtered = filtered.sort_values(["ts_code"]).reset_index(drop=True)

    return _select_fields(filtered, fields)


def get_index_stocks(index_code: str, date: date | None = None) -> list[str]:
    """Get index constituents for the latest available snapshot on or before a date."""
    frame = _query_meta_table("index_weight")
    filtered = frame[frame["index_code"] == index_code].copy()
    if filtered.empty:
        return []

    filtered["trade_date"] = pd.to_datetime(filtered["trade_date"])
    if date is not None:
        as_of = ensure_date(date)
        filtered = filtered[filtered["trade_date"].dt.date <= as_of]
    if filtered.empty:
        return []

    latest = filtered["trade_date"].max()
    result = filtered[filtered["trade_date"] == latest].sort_values(["trade_date", "ts_code"])
    return cast(list[str], result["ts_code"].tolist())


def get_industry_stocks(industry: str, date: date | None = None) -> list[str]:
    """Get active industry constituents on the requested date."""
    frame = _query_meta_table("industry_member")
    filtered = frame.copy()
    if "industry_code" in filtered.columns:
        mask = filtered["industry_code"] == industry
        if "industry_name" in filtered.columns:
            mask = mask | (filtered["industry_name"] == industry)
        filtered = filtered[mask]
    return _active_member_codes(filtered, date)


def get_concept_stocks(concept: str, date: date | None = None) -> list[str]:
    """Get active concept constituents on the requested date."""
    frame = _query_meta_table("concept_member")
    filtered = frame.copy()
    if "concept_code" in filtered.columns:
        mask = filtered["concept_code"] == concept
        if "concept_name" in filtered.columns:
            mask = mask | (filtered["concept_name"] == concept)
        filtered = filtered[mask]
    return _active_member_codes(filtered, date)


def get_trade_days(start_date: date | None = None, end_date: date | None = None) -> list[date]:
    """Get open trade days within the requested range."""
    frame = _query_meta_table("trade_calendar")
    if frame.empty:
        return []

    filtered = frame.copy()
    if "is_open" in filtered.columns:
        filtered = filtered[filtered["is_open"] == 1]
    filtered = _filter_by_date_range(filtered, "cal_date", start_date, end_date)
    filtered = filtered.sort_values(["cal_date"]).reset_index(drop=True)
    return [timestamp.date() for timestamp in pd.to_datetime(filtered["cal_date"]).tolist()]


def get_security_info(ts_code: str) -> dict[str, Any]:
    """Get security info from stock_basic metadata."""
    frame = _query_meta_table("stock_basic")
    filtered = frame[frame["ts_code"] == ts_code].copy() if "ts_code" in frame.columns else pd.DataFrame()
    if filtered.empty:
        return {}
    return cast(dict[str, Any], filtered.iloc[0].to_dict())


def attribute_history(
    security: str,
    count: int,
    unit: str = "1d",
    fields: list[str] | None = None,
    skip_paused: bool = True,
    fq: str = "pre",
) -> pd.DataFrame:
    """Get the latest N bars for a security."""
    del skip_paused
    _validate_fq(fq)
    if count <= 0:
        return pd.DataFrame(columns=fields or [])

    frame = _load_price_frame(security, unit)
    date_column = _price_date_column(unit)
    filtered = frame[frame["ts_code"] == security].copy()
    if date_column == "datetime" and "freq" in filtered.columns:
        filtered = filtered[filtered["freq"] == _normalize_frequency(unit)]

    filtered[date_column] = pd.to_datetime(filtered[date_column])
    filtered = filtered.sort_values([date_column]).tail(count).reset_index(drop=True)
    return _select_fields(filtered, fields)


def get_money_flow(
    target_type: str,
    code: str | list[str] | None = None,
    trade_date: date | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> pd.DataFrame:
    """获取资金流数据(P1 复盘需要)。"""
    table = _MONEY_FLOW_TABLES.get(target_type)
    if table is None:
        raise ValueError(f"Unsupported money flow target_type: {target_type}")

    frame = _query_meta_table(table)
    filtered = frame.copy()
    codes = _ensure_code_list(code)
    code_column = _resolve_code_column(filtered, target_type)
    if codes and code_column in filtered.columns:
        filtered = filtered[filtered[code_column].isin(codes)]

    if trade_date is not None:
        filtered = _filter_by_date_range(filtered, "trade_date", trade_date, trade_date)
    else:
        filtered = _filter_by_date_range(filtered, "trade_date", start_date, end_date)
    return filtered.sort_values([column for column in ("trade_date", code_column) if column in filtered.columns]).reset_index(drop=True)


def get_limit_pool(
    trade_date: date | None = None,
    kind: str = "U",
    start_date: date | None = None,
    end_date: date | None = None,
) -> pd.DataFrame:
    """获取涨跌停池(P1 复盘需要)。"""
    frame = _query_market_table("limit_list")
    filtered = _filter_by_date_range(frame.copy(), "trade_date", trade_date or start_date, trade_date or end_date)
    if "limit" in filtered.columns:
        filtered = filtered[filtered["limit"] == kind]
    return filtered.sort_values([column for column in ("trade_date", "ts_code") if column in filtered.columns]).reset_index(drop=True)


def _load_price_frame(security: str | list[str], frequency: str) -> pd.DataFrame:
    table = _price_table(security, frequency)
    if table == "index_daily":
        frame = _query_market_table("index_daily")
        codes = _ensure_code_list(security)
        if codes:
            filtered = frame[frame["ts_code"].isin(codes)].copy()
            if not filtered.empty:
                return filtered
        return _query_market_table("daily_bar")
    return _query_market_table(table)


def _query_market_table(table: str) -> pd.DataFrame:
    _validate_table(table, DUCKDB_MARKET_TABLES)
    store = get_market_store(MARKET_STORE_NAME)
    return store.query(f"SELECT * FROM {table}")


def _query_meta_table(table: str) -> pd.DataFrame:
    _validate_table(table, POSTGRES_META_TABLES)
    store = get_meta_store(META_STORE_NAME)
    return store.query(f"SELECT * FROM {table}")


def _validate_table(table: str, allowed_tables: tuple[str, ...]) -> None:
    if table not in allowed_tables:
        raise ValueError(f"Unsupported table: {table}")


def _validate_fq(fq: str) -> None:
    if fq not in {"pre", "post", "none"}:
        raise ValueError(f"Unsupported fq mode: {fq}")


def _ensure_code_list(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def _price_table(security: str | list[str], frequency: str) -> str:
    normalized = _normalize_frequency(frequency)
    if normalized in _MINUTE_PRICE_FREQUENCIES:
        return "minute_bar"
    if normalized not in _DAILY_PRICE_FREQUENCIES:
        raise ValueError(f"Unsupported price frequency: {frequency}")

    codes = _ensure_code_list(security)
    if codes and all(code.endswith((".SH", ".SZ")) and code[:1] in {"0", "3", "6", "8", "4", "9"} for code in codes):
        return "daily_bar"
    return "daily_bar"


def _price_date_column(frequency: str) -> str:
    normalized = _normalize_frequency(frequency)
    if normalized in _MINUTE_PRICE_FREQUENCIES:
        return "datetime"
    return "trade_date"


def _normalize_frequency(frequency: str) -> str:
    return frequency.lower()


def _filter_by_date_range(
    frame: pd.DataFrame,
    column: str,
    start_date: date | None,
    end_date: date | None,
) -> pd.DataFrame:
    if frame.empty or column not in frame.columns:
        return frame

    filtered = frame.copy()
    filtered[column] = pd.to_datetime(filtered[column])
    if start_date is not None:
        start = ensure_date(start_date)
        filtered = filtered[filtered[column].dt.date >= start]
    if end_date is not None:
        end = ensure_date(end_date)
        filtered = filtered[filtered[column].dt.date <= end]
    return filtered


def _infer_date_column(frame: pd.DataFrame, preferred: tuple[str, ...]) -> str | None:
    for column in preferred:
        if column in frame.columns:
            return column
    return None


def _active_member_codes(frame: pd.DataFrame, as_of_date: date | None) -> list[str]:
    if frame.empty:
        return []

    filtered = frame.copy()
    if as_of_date is not None and "in_date" in filtered.columns:
        filtered = _filter_by_date_range(filtered, "in_date", None, as_of_date)
    if as_of_date is not None and "out_date" in filtered.columns:
        cutoff = pd.Timestamp(ensure_date(as_of_date))
        filtered["out_date"] = pd.to_datetime(filtered["out_date"])
        filtered = filtered[
            filtered["out_date"].isna() | (filtered["out_date"] > cutoff)
        ]
    if "is_active" in filtered.columns:
        filtered = filtered[filtered["is_active"] == 1]
    if filtered.empty:
        return []
    return cast(list[str], filtered.sort_values(["ts_code"])["ts_code"].tolist())


def _select_fields(frame: pd.DataFrame, fields: list[str] | None) -> pd.DataFrame:
    if fields is None:
        return frame.reset_index(drop=True)
    available_fields = [field for field in fields if field in frame.columns]
    return frame.loc[:, available_fields].reset_index(drop=True)


def _resolve_code_column(frame: pd.DataFrame, target_type: str) -> str:
    if target_type == "stock":
        return "ts_code"
    if target_type == "concept":
        return "concept_code"
    return "industry_code"
