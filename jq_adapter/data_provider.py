# coding=utf-8
"""
data_provider.py — 聚宽数据 API → xy_quant 数据层适配
=======================================================
将聚宽风格的数据调用翻译为 xy_quant data.api 的调用。
上层策略代码无需感知底层数据源。

所有函数签名与聚宽 api 保持一致，内部桥接到 xy_quant 的：
  - data.api (DuckDB + PG)
  - data.adjust (复权处理)
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Union, List, Optional

import numpy as np
import pandas as pd

from data import api as xy_api
from jq_adapter.utils import normalize_code
from datetime import date as date_type


def get_price(
    security: str | list[str],
    start_date: str | date | None = None,
    end_date: str | date | None = None,
    frequency: str = "daily",
    fields: list[str] | None = None,
    fq: str = "pre",
    count: int | None = None,
    skip_paused: bool = False,
    panel: bool = True,
    fill_paused: bool = True,
) -> pd.DataFrame:
    """
    获取行情数据（聚宽兼容签名）。

    内部委托给 xy_quant data.api.get_price()。

    Args:
        security: 股票代码，如 "000001.SZ" 或 ["000001.SZ", "600000.SH"]
        start_date: 起始日期（YYYY-MM-DD 或 YYYYMMDD）
        end_date: 结束日期
        frequency: "daily" / "1d" / "1min" / "5min" 等
        fields: 字段列表，如 ["close", "open", "high", "low", "volume"]
        fq: 复权方式 "pre" / "post" / None
        count: 取最近 N 条（与 start_date/end_date 互斥时优先 count）
        skip_paused: 是否跳过停牌（暂未实现）

    Returns:
        DataFrame with columns: ts_code, date/trade_date, + requested fields
    """
    if isinstance(security, str):
        security = normalize_code(security)
    elif isinstance(security, list):
        security = [normalize_code(s) for s in security]

    # Map "price" field to all price columns
    if fields and "price" in fields:
        fields = [f for f in fields if f != "price"] + ["open", "high", "low", "close"]

    if count is not None and count > 0:
        if isinstance(security, str):
            # Use attribute_history for single-security count-based query
            return xy_api.attribute_history(
                security=security,
                count=count,
                unit=frequency,
                fields=fields,
                fq=fq,
            )
        else:
            # Fallback for multi-security: use a wide date range then take tail per code
            pass

    # Normal date-range query
    if start_date is not None:
        s = start_date.isoformat() if isinstance(start_date, date_type) else str(start_date)
    else:
        s = "2010-01-01"
    if end_date is not None:
        e = end_date.isoformat() if isinstance(end_date, date_type) else str(end_date)
    else:
        e = datetime.now().strftime("%Y-%m-%d")

    df = xy_api.get_price(
        security=security,
        start_date=s,
        end_date=e,
        frequency=frequency,
        fields=fields,
        fq=fq,
        skip_paused=skip_paused,
    )

    # Add 'code' column from 'ts_code' for compat with JoinQuant strategies that expect it
    if not df.empty and 'ts_code' in df.columns and 'code' not in df.columns:
        df['code'] = df['ts_code']

    # For multi-security count queries, group by code and take tail
    if count is not None and count > 0 and not isinstance(security, str):
        if not df.empty and 'code' in df.columns:
            df = df.sort_values('trade_date').groupby('code', group_keys=False).tail(count)

    return df


def get_bars(
    security: str,
    count: int,
    unit: str = "1d",
    fields: list[str] | None = None,
    include_now: bool = False,
    fq: str = "pre",
) -> pd.DataFrame:
    """
    获取最近 N 条 K 线数据（聚宽兼容）。

    等价于 get_price(security, count=count, frequency=unit, ...)
    """
    return get_price(
        security=security,
        count=count,
        frequency=unit,
        fields=fields,
        fq=fq,
    )


def attribute_history(
    security: str,
    count: int,
    unit: str = "1d",
    fields: list[str] | None = None,
    skip_paused: bool = True,
    fq: str = "pre",
) -> pd.DataFrame:
    """
    获取指定证券最近 N 条历史数据。

    直接委托给 xy_api.attribute_history()。
    """
    return xy_api.attribute_history(
        security=normalize_code(security),
        count=count,
        unit=unit,
        fields=fields,
        skip_paused=skip_paused,
        fq=fq,
    )


def get_index_stocks(index_code: str, date: date | None = None) -> list[str]:
    """
    获取指数成分股列表。

    支持聚宽 & xy_quant 两种指数代码格式：
      - 聚宽: "000300.XSHG" / "399005.XSHE"
      - xy_quant: "000300.SH" / "399005.SZ"
    """
    idx = normalize_code(index_code)
    return xy_api.get_index_stocks(index_code=idx, date=date)


def get_industry_stocks(industry: str, date: date | None = None) -> list[str]:
    """获取行业成分股列表。"""
    return xy_api.get_industry_stocks(industry=industry, date=date)


def get_concept_stocks(concept: str, date: date | None = None) -> list[str]:
    """获取概念成分股列表。"""
    return xy_api.get_concept_stocks(concept=concept, date=date)


def get_trade_days(
    start_date: date | None = None,
    end_date: date | None = None,
    count: int | None = None,
) -> list[date]:
    """获取交易日列表。支持 start_date/end_date 或 count 两种模式。"""
    days = xy_api.get_trade_days(start_date=start_date, end_date=end_date)
    if count is not None and count > 0 and len(days) > count:
        days = days[-int(count):]
    return days


def get_all_securities(
    types: list[str] | None = None,
    date: date | None = None,
) -> pd.DataFrame:
    """
    获取所有证券基本信息。

    从 PostgreSQL stock_basic 表读取。

    Returns:
        DataFrame indexed by ts_code, with columns: display_name, name,
        start_date, end_date, type
    """
    df = xy_api.get_all_securities(types=types, date=date)
    if df.empty:
        return df

    # Build a DataFrame matching 聚宽's get_all_securities format
    result = pd.DataFrame(index=df["ts_code"].values)
    result["display_name"] = df["name"].values
    result["name"] = df["symbol"].values
    result["start_date"] = pd.to_datetime(df["list_date"].values)
    result["end_date"] = pd.to_datetime(df.get("delist_date", pd.NaT).values)
    result["type"] = "stock"
    result.index.name = "code"

    return result


def get_valuation(
    security: str | list[str],
    date: date | None = None,
    fields: list[str] | None = None,
) -> pd.DataFrame:
    """
    获取估值数据（PE、PB 等）。

    从 daily_basic 表读取。
    """
    codes = [normalize_code(s) for s in ([security] if isinstance(security, str) else security)]
    return xy_api.get_fundamentals(
        table="daily_basic",
        ts_code=codes,
        start_date=date,
        end_date=date,
        fields=fields,
    )


def get_fundamentals(
    table: str,
    ts_code: str | list[str] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    fields: list[str] | None = None,
) -> pd.DataFrame:
    """
    获取基本面数据。

    table 支持: income / balance / cashflow / daily_basic / fina_indicator 等
    """
    codes = None
    if ts_code is not None:
        codes = [normalize_code(s) for s in ([ts_code] if isinstance(ts_code, str) else ts_code)]
    return xy_api.get_fundamentals(
        table=table,
        ts_code=codes or [],
        start_date=start_date,
        end_date=end_date,
        fields=fields,
    )


def get_money_flow(
    target_type: str = "stock",
    code: str | list[str] | None = None,
    trade_date: date | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> pd.DataFrame:
    """获取资金流数据。"""
    codes = None
    if code is not None:
        codes = [normalize_code(s) for s in ([code] if isinstance(code, str) else code)]
    return xy_api.get_money_flow(
        target_type=target_type,
        code=codes,
        trade_date=trade_date,
        start_date=start_date,
        end_date=end_date,
    )


def get_billboard_list(
    trade_date: date | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    ts_code: str | None = None,
) -> pd.DataFrame:
    """
    获取龙虎榜数据。

    从 PG top_list 表读取。
    """
    import pandas as pd
    from data.storage.factory import get_meta_store

    store = get_meta_store("postgres")
    try:
        df = store.query("SELECT * FROM top_list")
        if df.empty:
            return df

        if trade_date is not None:
            dt = pd.Timestamp(trade_date)
            df["trade_date"] = pd.to_datetime(df["trade_date"])
            df = df[df["trade_date"].dt.date == dt.date()]
        else:
            if start_date is not None:
                df["trade_date"] = pd.to_datetime(df["trade_date"])
                df = df[df["trade_date"].dt.date >= pd.Timestamp(start_date).date()]
            if end_date is not None:
                df["trade_date"] = pd.to_datetime(df.get("trade_date", pd.NaT))
                df = df[df["trade_date"].dt.date <= pd.Timestamp(end_date).date()]

        if ts_code is not None:
            codes = [normalize_code(s) for s in ([ts_code] if isinstance(ts_code, str) else ts_code)]
            df = df[df["ts_code"].isin(codes)] if "ts_code" in df.columns else df

        return df.sort_values("trade_date", ascending=False).reset_index(drop=True) if not df.empty else df
    finally:
        store.close()


def get_ticks(
    security: str,
    start_date: str | date,
    end_date: str | date,
    fields: list[str] | None = None,
) -> pd.DataFrame:
    """获取分钟线/tick 数据。"""
    return xy_api.get_ticks(
        security=normalize_code(security),
        start_date=start_date,
        end_date=end_date,
        fields=fields,
    )


def get_security_info(ts_code: str) -> dict:
    """获取单只证券的基本信息。"""
    return xy_api.get_security_info(normalize_code(ts_code))


# ── 聚宽扩展 API（xy_quant 适配补充）───────────────────────────────


def get_extras(
    info: str,
    security_list: list[str],
    end_date=None,
    count: int = 1,
):
    """获取额外信息（如 is_st）。

    从 PostgreSQL stock_basic 表的 name 字段判断 ST 状态。
    聚宽 get_extras('is_st') 返回 DataFrame，index=日期, columns=股票代码, values=bool。

    当前仅支持 info='is_st'。
    """
    if info != "is_st":
        raise ValueError(f"get_extras: 不支持的 info 类型 '{info}'，仅支持 'is_st'")

    from data.storage.factory import get_meta_store

    codes = [normalize_code(c) for c in security_list]
    store = get_meta_store("postgres")
    try:
        df = store.query("SELECT ts_code, name FROM stock_basic")
        if df.empty:
            return pd.DataFrame()

        df = df[df["ts_code"].isin(codes)]
        # ST 判定：名称包含 ST 或 *ST
        df["is_st"] = df["name"].str.contains("ST", na=False)
        result = df.set_index("ts_code")["is_st"]

        # 构建聚宽格式：单行 DataFrame，index=日期, columns=代码
        if end_date is not None:
            dt = pd.Timestamp(end_date)
        else:
            dt = pd.Timestamp.now()
        out = pd.DataFrame(index=[dt.date()], columns=codes)
        for c in codes:
            if c in result.index:
                out.loc[dt.date(), c] = bool(result[c])
            else:
                out.loc[dt.date(), c] = False
        out.index.name = "date"
        return out
    finally:
        store.close()


def get_industry(
    securities: list[str],
    date=None,
):
    """获取股票行业分类。

    从 PostgreSQL industry_member 表查询，返回聚宽兼容的嵌套字典格式：
    {code: {'sw_l1': {'industry_code': '801010.SI', 'industry_name': '农林牧渔'}, ...}}

    如果某只股票有多个行业（如同时属于 SW L1 和 L2），按层级归类。
    """
    from data.storage.factory import get_meta_store

    codes = [normalize_code(c) for c in securities]
    store = get_meta_store("postgres")
    try:
        df = store.query("SELECT * FROM industry_member")
        if df.empty:
            return {}

        # 过滤代码
        df = df[df["ts_code"].isin(codes)]

        # 日期过滤：in_date <= date AND (out_date IS NULL OR out_date > date)
        if date is not None:
            dt = pd.Timestamp(date)
            df["in_date_dt"] = pd.to_datetime(df["in_date"])
            df["out_date_dt"] = pd.to_datetime(df["out_date"])
            df = df[
                (df["in_date_dt"].dt.date <= dt.date())
                & (df["out_date_dt"].isna() | (df["out_date_dt"].dt.date > dt.date()))
            ]

        # 判断层级：industry_name 含 "Ⅱ" 的为 L2，否则 L1
        def _industry_level(name: str) -> str:
            if name and ("Ⅱ" in name or "Ⅲ" in name):
                return "sw_l2"
            return "sw_l1"

        result: dict[str, dict] = {}
        for _, row in df.iterrows():
            code = row["ts_code"]
            level = _industry_level(row.get("industry_name", ""))
            if code not in result:
                result[code] = {}
            result[code][level] = {
                "industry_code": row["industry_code"],
                "industry_name": row["industry_name"],
            }

        return result
    finally:
        store.close()


def get_factor_values(
    securities: list[str],
    factors: list[str],
    count: int = 1,
    end_date=None,
):
    """获取聚宽因子值。

    支持的因子：
      - VOL240: 从 daily_bar 计算 240 日年化波动率
      - financial_liability / administration_expense_ttm / liquidity: 本地无数据源，返回 NaN

    Returns:
        dict[str, DataFrame]: {factor_name: DataFrame(index=dates, columns=codes)}
    """
    codes = [normalize_code(c) for c in securities]
    if end_date is None:
        end_date = pd.Timestamp.now().date()
    dt = pd.Timestamp(end_date)

    result: dict[str, pd.DataFrame] = {}
    idx_dates = [dt.date()]

    for factor in factors:
        if factor == "VOL240":
            from data.storage.factory import get_market_store

            store = get_market_store("duckdb", read_only=True)
            try:
                lookback_start = dt - pd.Timedelta(days=400)
                code_filter = ", ".join(f"'{c}'" for c in codes)
                raw = store.query(f"""
                    SELECT ts_code, trade_date, close FROM daily_bar
                    WHERE ts_code IN ({code_filter})
                      AND trade_date >= '{lookback_start.date()}'
                      AND trade_date <= '{dt.date()}'
                """)
                if not raw.empty:
                    raw["trade_date"] = pd.to_datetime(raw["trade_date"])
                    groups = raw.groupby("ts_code")
                    closes_arrays = {}
                    for code in codes:
                        grp = groups.get_group(code) if code in groups.groups else None
                        if grp is not None:
                            grp_sorted = grp.sort_values("trade_date")
                            closes = grp_sorted["close"].values
                            n = min(len(closes), 240)
                            if n >= 60:
                                c = closes[-n:]
                                daily_rets = np.diff(c) / c[:-1]
                                closes_arrays[code] = np.std(daily_rets) * np.sqrt(252)
                    # Build one dict → one DataFrame (no per-stock .loc)
                    if closes_arrays:
                        row_dict = {dt.date(): closes_arrays}
                        df = pd.DataFrame(row_dict).T
                        df.index.name = "date"
                        df = df.reindex(columns=codes)  # pad missing with NaN
                    else:
                        df = pd.DataFrame(index=idx_dates, columns=codes, dtype=float)
                        df.index.name = "date"
                else:
                    df = pd.DataFrame(index=idx_dates, columns=codes, dtype=float)
                    df.index.name = "date"
            finally:
                store.close()
        else:
            df = pd.DataFrame(index=idx_dates, columns=codes, dtype=float)
            df.index.name = "date"

        result[factor] = df

    return result
