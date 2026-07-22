"""Tushare 数据源适配器。"""

from __future__ import annotations

import logging
from datetime import date
from re import search
from time import sleep
from typing import Any, Final

import pandas as pd
import tushare as ts

from config.settings import settings
from interfaces.data_source import IDataSource
from utils.calendar import ensure_date
from utils.exception import ConfigError, DataSourceError
from utils.rate_limiter import TokenBucketRateLimiter
from utils.retry import retry_on

_TUSHARE_CAPABILITIES: Final[frozenset[str]] = frozenset(
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
MINUTE_BAR_CHUNK_DAYS: Final[int] = 30

_LIMIT_LIST_COLUMNS: Final[tuple[str, ...]] = (
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
)


logger = logging.getLogger(__name__)


__all__ = ["TushareSource", "settings"]


class TushareSource(IDataSource):
    """Tushare-backed implementation of the market data source interface."""

    name = "tushare"

    def __init__(self, client: Any | None = None) -> None:
        self._client = client or _create_default_client()
        self._limit_list_d_restricted = False
        per_second = max(settings.tushare_rate_limit_per_min / 60, 1 / 60)
        self._rate_limiter = TokenBucketRateLimiter(
            capacity=settings.tushare_rate_limit_per_min,
            refill_rate=per_second,
        )
        minute_bar_per_second = max(settings.minute_bar_rate_limit_per_min / 60, 1 / 60)
        self._minute_bar_rate_limiter = TokenBucketRateLimiter(
            capacity=settings.minute_bar_rate_limit_per_min,
            refill_rate=minute_bar_per_second,
        )
        self._limit_pool_rate_limiter = TokenBucketRateLimiter(
            capacity=1,
            refill_rate=1 / 60,
        )

    def fetch_daily_bar(
        self,
        ts_code: str | list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        return self._call(
            "daily",
            ts_code=_join_codes(ts_code),
            start_date=_format_ymd(start_date),
            end_date=_format_ymd(end_date),
        )

    def fetch_minute_bar(
        self,
        ts_code: str,
        start_date: date,
        end_date: date,
        freq: str = "1min",
    ) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for chunk_start, chunk_end in _chunk_date_range(start_date, end_date, days=MINUTE_BAR_CHUNK_DAYS):
            frame = self._call_with_remote_rate_limit_retry(
                "pro_bar",
                rate_limiter=self._minute_bar_rate_limiter,
                ts_code=ts_code,
                asset="E",
                start_date=f"{chunk_start.isoformat()} 09:30:00",
                end_date=f"{chunk_end.isoformat()} 15:00:00",
                freq=freq,
            )
            if not frame.empty:
                frame = frame.copy()
                if "trade_time" in frame.columns and "datetime" not in frame.columns:
                    frame["datetime"] = pd.to_datetime(frame["trade_time"], errors="coerce")
                if "freq" not in frame.columns:
                    frame["freq"] = freq
                frame = frame.reindex(columns=["ts_code", "datetime", "open", "high", "low", "close", "vol", "amount", "freq"])
                frame = frame.dropna(subset=["datetime"])
                if not frame.empty:
                    frame = frame.sort_values(["ts_code", "datetime"]).reset_index(drop=True)
                    frames.append(frame)
        if not frames:
            return pd.DataFrame(columns=["ts_code", "datetime", "open", "high", "low", "close", "vol", "amount", "freq"])
        if len(frames) == 1:
            return frames[0]
        return pd.concat(frames, ignore_index=True)

    def fetch_adj_factor(
        self,
        ts_code: str | list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        return self._call(
            "adj_factor",
            ts_code=_join_codes(ts_code),
            start_date=_format_ymd(start_date),
            end_date=_format_ymd(end_date),
        )

    def fetch_daily_basic(
        self,
        ts_code: str | list[str] | None = None,
        trade_date: date | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        return self._call(
            "daily_basic",
            ts_code=_join_codes(ts_code),
            trade_date=_format_ymd(trade_date),
            start_date=_format_ymd(start_date),
            end_date=_format_ymd(end_date),
        )

    def fetch_index_daily(
        self,
        ts_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        return self._call(
            "index_daily",
            ts_code=ts_code,
            start_date=_format_ymd(start_date),
            end_date=_format_ymd(end_date),
        )

    def fetch_limit_pool(self, trade_date: date, kind: str = "U") -> pd.DataFrame:
        if self._limit_list_d_restricted:
            return self._fetch_limit_pool_from_stk_limit(trade_date, kind=kind)

        request_trade_date = _format_ymd(trade_date)
        try:
            frame = self._call(
                "limit_list_d",
                trade_date=request_trade_date,
                limit_type=kind,
            )
        except DataSourceError as exc:
            wait_seconds = _parse_remote_rate_limit_wait_seconds(str(exc))
            if wait_seconds is None or kind not in {"U", "D"}:
                raise
            self._limit_list_d_restricted = True
            return self._fetch_limit_pool_from_stk_limit(trade_date, kind=kind)

        if frame.empty and kind in {"U", "D"}:
            return self._fetch_limit_pool_from_stk_limit(trade_date, kind=kind)
        return frame

    def _fetch_limit_pool_from_stk_limit(self, trade_date: date, *, kind: str) -> pd.DataFrame:
        request_trade_date = _format_ymd(trade_date)
        limit_frame = _normalize_tushare_frame(
            self._call("stk_limit", trade_date=request_trade_date),
            request_kwargs={"trade_date": request_trade_date},
        )
        daily_frame = _normalize_tushare_frame(
            self._call("daily", start_date=request_trade_date, end_date=request_trade_date),
            request_kwargs={"start_date": request_trade_date, "end_date": request_trade_date},
        )
        daily_basic_frame = _normalize_tushare_frame(
            self._call("daily_basic", trade_date=request_trade_date),
            request_kwargs={"trade_date": request_trade_date},
        )
        if limit_frame.empty or daily_frame.empty:
            return pd.DataFrame(columns=_LIMIT_LIST_COLUMNS)

        merged = limit_frame.merge(
            daily_frame[["ts_code", "trade_date", "close", "pct_chg", "amount"]],
            on=["ts_code", "trade_date"],
            how="inner",
        )
        if merged.empty:
            return pd.DataFrame(columns=_LIMIT_LIST_COLUMNS)

        daily_basic_subset = daily_basic_frame.reindex(
            columns=["ts_code", "trade_date", "turnover_rate", "float_mv", "circ_mv", "total_mv"]
        ).copy()
        if daily_basic_subset["float_mv"].isna().all() and "circ_mv" in daily_basic_subset.columns:
            daily_basic_subset["float_mv"] = daily_basic_subset["circ_mv"]
        daily_basic_subset = daily_basic_subset.drop(columns=["circ_mv"], errors="ignore")
        merged = merged.merge(
            daily_basic_subset,
            on=["ts_code", "trade_date"],
            how="left",
        )
        threshold_column = "up_limit" if kind == "U" else "down_limit"
        tolerance = 1e-6
        if kind == "U":
            mask = (merged["close"] >= merged[threshold_column] - tolerance) & merged[threshold_column].notna()
        else:
            mask = (merged["close"] <= merged[threshold_column] + tolerance) & merged[threshold_column].notna()
        filtered = merged.loc[mask].copy()
        if filtered.empty:
            return pd.DataFrame(columns=_LIMIT_LIST_COLUMNS)

        filtered["name"] = None
        filtered["limit_amount"] = None
        filtered["fd_amount"] = None
        filtered["first_time"] = None
        filtered["last_time"] = None
        filtered["open_times"] = None
        filtered["up_stat"] = None
        filtered["limit_times"] = None
        filtered["limit"] = kind
        filtered = filtered.rename(columns={"turnover_rate": "turnover_ratio"})
        return filtered[list(_LIMIT_LIST_COLUMNS)]

    def fetch_stock_basic(self) -> pd.DataFrame:
        return self._call("stock_basic", exchange="", list_status="L")

    def fetch_trade_calendar(self, start_date: date, end_date: date) -> pd.DataFrame:
        return self._call(
            "trade_cal",
            exchange="SSE",
            start_date=_format_ymd(start_date),
            end_date=_format_ymd(end_date),
        )

    def fetch_stock_suspend(
        self, trade_date: date | None = None, ts_code: str | None = None
    ) -> pd.DataFrame:
        return self._call(
            "suspend_d",
            trade_date=_format_ymd(trade_date),
            ts_code=ts_code,
        )

    def fetch_income(
        self, ts_code: str, start_date: date | None = None, end_date: date | None = None
    ) -> pd.DataFrame:
        return self._call(
            "income",
            ts_code=ts_code,
            start_date=_format_ymd(start_date),
            end_date=_format_ymd(end_date),
        )

    def fetch_balancesheet(
        self, ts_code: str, start_date: date | None = None, end_date: date | None = None
    ) -> pd.DataFrame:
        return self._call(
            "balancesheet",
            ts_code=ts_code,
            start_date=_format_ymd(start_date),
            end_date=_format_ymd(end_date),
        )

    def fetch_cashflow(
        self, ts_code: str, start_date: date | None = None, end_date: date | None = None
    ) -> pd.DataFrame:
        return self._call(
            "cashflow",
            ts_code=ts_code,
            start_date=_format_ymd(start_date),
            end_date=_format_ymd(end_date),
        )

    def fetch_fina_indicator(
        self, ts_code: str, start_date: date | None = None, end_date: date | None = None
    ) -> pd.DataFrame:
        return self._call(
            "fina_indicator",
            ts_code=ts_code,
            start_date=_format_ymd(start_date),
            end_date=_format_ymd(end_date),
        )

    def fetch_dividend(self, ts_code: str) -> pd.DataFrame:
        return self._call("dividend", ts_code=ts_code)

    def fetch_top_list(self, trade_date: date) -> pd.DataFrame:
        return self._call("top_list", trade_date=_format_ymd(trade_date))

    def fetch_margin_detail(self, trade_date: date) -> pd.DataFrame:
        return self._call("margin_detail", trade_date=_format_ymd(trade_date))

    def fetch_stk_holdertrade(
        self, ts_code: str | None = None, ann_date: date | None = None
    ) -> pd.DataFrame:
        return self._call(
            "stk_holdertrade",
            ts_code=ts_code,
            ann_date=_format_ymd(ann_date),
        )

    def fetch_hk_hold(
        self, trade_date: date | None = None, ts_code: str | None = None
    ) -> pd.DataFrame:
        frame = self._call(
            "hk_hold",
            trade_date=_format_ymd(trade_date),
            ts_code=ts_code,
        )
        if "name" in frame.columns:
            frame = frame.copy()
            frame["name"] = frame["name"].astype("string").str.slice(0, 50)
        return frame

    def fetch_concept_money_flow(self, trade_date: date) -> pd.DataFrame:
        request_trade_date = _format_ymd(trade_date)
        frame = self._call_supported_moneyflow_with_remote_rate_limit_retry(
            "moneyflow_ths",
            trade_date=request_trade_date,
        )
        return _normalize_concept_money_flow_frame(frame)

    def fetch_industry_money_flow(self, trade_date: date) -> pd.DataFrame:
        request_trade_date = _format_ymd(trade_date)
        frame = self._call_supported_moneyflow_with_remote_rate_limit_retry(
            "moneyflow_ind_ths",
            trade_date=request_trade_date,
        )
        return _normalize_industry_money_flow_frame(frame)

    def fetch_stock_money_flow(self, trade_date: date) -> pd.DataFrame:
        request_trade_date = _format_ymd(trade_date)
        frame = self._call_with_remote_rate_limit_retry(
            "moneyflow",
            rate_limiter=self._rate_limiter,
            trade_date=request_trade_date,
        )
        return _normalize_stock_money_flow_frame(frame)

    def fetch_concept_list(self) -> pd.DataFrame:
        return self._call("concept")

    def fetch_concept_member(self, concept_code: str) -> pd.DataFrame:
        return self._call("concept_detail", id=concept_code)

    def fetch_industry_list(self) -> pd.DataFrame:
        return self._call("index_classify", src="SW2021")

    def fetch_industry_member(self, industry_code: str) -> pd.DataFrame:
        return self._call("index_member", index_code=industry_code)

    def fetch_index_weight(
        self, index_code: str, trade_date: date | None = None
    ) -> pd.DataFrame:
        return self._call(
            "index_weight",
            index_code=index_code,
            trade_date=_format_ymd(trade_date),
        )

    def supports(self, capability: str) -> bool:
        """Return whether this source advertises the requested capability."""
        return capability in _TUSHARE_CAPABILITIES

    @retry_on(DataSourceError)
    def _call(self, method_name: str, *, acquire_rate_limit: bool = True, **kwargs: Any) -> pd.DataFrame:
        if acquire_rate_limit:
            self._rate_limiter.acquire()
        method = getattr(self._client, method_name)
        request_kwargs = _drop_none(kwargs)
        try:
            frame = method(**request_kwargs)
        except Exception as exc:  # noqa: BLE001
            raise DataSourceError(str(exc)) from exc
        return _normalize_tushare_frame(frame, request_kwargs=request_kwargs)

    def _call_with_remote_rate_limit_retry(
        self,
        method_name: str,
        *,
        rate_limiter: TokenBucketRateLimiter,
        **kwargs: Any,
    ) -> pd.DataFrame:
        request_kwargs = _drop_none(kwargs)
        while True:
            rate_limiter.acquire()
            try:
                return self._call(method_name, acquire_rate_limit=False, **request_kwargs)
            except DataSourceError as exc:
                wait_seconds = _parse_remote_rate_limit_wait_seconds(str(exc))
                if wait_seconds is None:
                    raise
                logger.warning(
                    "Tushare remote rate limit hit for %s; sleeping %.1fs before retry. error=%s",
                    method_name,
                    wait_seconds,
                    exc,
                )
                sleep(wait_seconds)

    def _call_supported_moneyflow_with_remote_rate_limit_retry(
        self,
        method_name: str,
        **kwargs: Any,
    ) -> pd.DataFrame:
        request_kwargs = _drop_none(kwargs)
        max_attempts = 3
        total_wait_seconds = 0.0
        for attempt in range(1, max_attempts + 1):
            try:
                return self._call(method_name, **request_kwargs)
            except DataSourceError as exc:
                wait_seconds = _parse_remote_rate_limit_wait_seconds(str(exc))
                if wait_seconds is None:
                    raise
                if attempt >= max_attempts:
                    raise DataSourceError(
                        f"{method_name} exceeded remote rate-limit retry budget after {attempt} attempts; "
                        f"total_wait={total_wait_seconds:.1f}s; last_error={exc}"
                    ) from exc
                total_wait_seconds += wait_seconds
                logger.warning(
                    "Tushare remote rate limit hit for %s; sleeping %.1fs before retry (%s/%s). error=%s",
                    method_name,
                    wait_seconds,
                    attempt,
                    max_attempts,
                    exc,
                )
                sleep(wait_seconds)
        raise AssertionError(f"unreachable retry loop exit for {method_name}")


def _create_default_client() -> Any:
    if not settings.tushare_token:
        raise ConfigError("Tushare token is required to initialize TushareSource")
    token = settings.tushare_token
    ts.set_token(token)
    try:
        pro_client = ts.pro_api(token)
    except TypeError:
        try:
            pro_client = ts.pro_api()
        except pd.errors.EmptyDataError as exc:
            raise ConfigError(
                "Tushare token cache file is empty or corrupted; set TUSHARE_TOKEN explicitly and remove the stale local cache file"
            ) from exc

    class _TushareClientProxy:
        def __init__(self, pro: Any) -> None:
            self._pro = pro

        def __getattr__(self, name: str) -> Any:
            if name == "pro_bar":
                return ts.pro_bar
            return getattr(self._pro, name)

    return _TushareClientProxy(pro_client)


def _should_fallback_to_supported_moneyflow_endpoint(exc: DataSourceError) -> bool:
    message = str(exc)
    return (
        "请指定正确的接口名" in message
        or "unsupported" in message.lower()
        or "not found" in message.lower()
    )


def _parse_remote_rate_limit_wait_seconds(message: str) -> float | None:
    if '频率超限' not in message:
        return None

    matched = search(r'\((\d+)次/(分钟|小时)\)', message)
    if matched is None:
        return 30.0

    limit = max(int(matched.group(1)), 1)
    unit = matched.group(2)
    window_seconds = 60.0 if unit == '分钟' else 3600.0
    return window_seconds / limit


def _join_codes(ts_code: str | list[str] | None) -> str | None:
    if ts_code is None:
        return None
    if isinstance(ts_code, list):
        return ",".join(ts_code)
    return ts_code


def _format_ymd(value: date | None) -> str | None:
    if value is None:
        return None
    normalized = ensure_date(value)
    return normalized.strftime("%Y%m%d")


def _drop_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _chunk_date_range(start_date: date, end_date: date, *, days: int) -> list[tuple[date, date]]:
    start = ensure_date(start_date)
    end = ensure_date(end_date)
    if start > end:
        return []

    chunks: list[tuple[date, date]] = []
    current_start = start
    while current_start <= end:
        current_end = min(current_start + pd.Timedelta(days=days - 1), end)
        chunks.append((current_start, current_end))
        current_start = current_end + pd.Timedelta(days=1)
    return chunks


def _normalize_tushare_frame(
    frame: pd.DataFrame,
    *,
    request_kwargs: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Normalize Tushare payloads into Python-friendly date/time types."""
    if frame.empty:
        return frame

    normalized = frame.copy()
    if 'trade_time' in normalized.columns and 'datetime' not in normalized.columns:
        normalized = normalized.rename(columns={'trade_time': 'datetime'})

    for column in normalized.columns:
        series = normalized[column]
        lower_name = column.lower()
        if lower_name.endswith('_date'):
            normalized[column] = _normalize_date_series(series)
        elif lower_name == 'datetime':
            normalized[column] = _normalize_datetime_series(series)

    if request_kwargs is not None and 'freq' in request_kwargs and 'freq' not in normalized.columns:
        normalized['freq'] = request_kwargs['freq']
    return normalized


def _normalize_date_series(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, format='%Y%m%d', errors='coerce')
    if parsed.notna().sum() == 0:
        parsed = pd.to_datetime(series, errors='coerce')
    if parsed.notna().sum() == 0:
        return series

    normalized = series.astype('object').copy()
    normalized.loc[parsed.notna()] = parsed.loc[parsed.notna()].dt.date.to_list()
    return normalized


def _normalize_datetime_series(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, errors='coerce')
    if parsed.notna().sum() == 0:
        return series

    normalized = series.astype('object').copy()
    normalized.loc[parsed.notna()] = parsed.loc[parsed.notna()].to_list()
    return normalized


def _normalize_concept_money_flow_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=[
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
        )

    normalized = frame.copy()
    if "concept_code" in normalized.columns:
        return normalized
    return pd.DataFrame(
        {
            "trade_date": normalized.get("trade_date"),
            "concept_code": normalized.get("ts_code"),
            "concept_name": normalized.get("name"),
            "pct_chg": normalized.get("pct_change"),
            "main_inflow": normalized.get("net_amount"),
            "main_inflow_pct": normalized.get("buy_lg_amount_rate"),
            "super_inflow": pd.Series([None] * len(normalized), index=normalized.index, dtype="object"),
            "big_inflow": normalized.get("buy_lg_amount"),
            "mid_inflow": normalized.get("buy_md_amount"),
            "small_inflow": normalized.get("buy_sm_amount"),
        }
    )


def _normalize_industry_money_flow_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=[
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
        )

    normalized = frame.copy()
    if "industry_code" in normalized.columns:
        return normalized
    net_amount = normalized.get("net_amount")
    return pd.DataFrame(
        {
            "trade_date": normalized.get("trade_date"),
            "industry_code": normalized.get("ts_code"),
            "industry_name": normalized.get("name", normalized.get("industry")),
            "pct_chg": normalized.get("pct_change"),
            # Tushare moneyflow_ind_ths returns net_amount in 亿元; convert to 万元
            # so all money_flow tables use a consistent unit (万元).
            "main_inflow": net_amount * 10000 if net_amount is not None else None,
            "main_inflow_pct": normalized.get("net_amount_rate"),
            "super_inflow": normalized.get("buy_elg_amount"),
            "big_inflow": normalized.get("buy_lg_amount"),
            "mid_inflow": normalized.get("buy_md_amount"),
            "small_inflow": normalized.get("buy_sm_amount"),
        }
    )


def _normalize_stock_money_flow_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=[
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
        )

    normalized = frame.copy()
    if "main_inflow" in normalized.columns:
        return normalized

    zero_series = pd.Series(0.0, index=normalized.index)
    super_inflow = normalized.get("buy_elg_amount", zero_series) - normalized.get("sell_elg_amount", zero_series)
    big_inflow = normalized.get("buy_lg_amount", zero_series) - normalized.get("sell_lg_amount", zero_series)
    mid_inflow = normalized.get("buy_md_amount", zero_series) - normalized.get("sell_md_amount", zero_series)
    small_inflow = normalized.get("buy_sm_amount", zero_series) - normalized.get("sell_sm_amount", zero_series)
    main_inflow = super_inflow + big_inflow
    amount_total = (
        normalized.get("buy_sm_amount", zero_series)
        + normalized.get("buy_md_amount", zero_series)
        + normalized.get("buy_lg_amount", zero_series)
        + normalized.get("buy_elg_amount", zero_series)
    )
    main_inflow_pct = (main_inflow / amount_total.replace({0: pd.NA})) * 100

    return pd.DataFrame(
        {
            "trade_date": normalized.get("trade_date"),
            "ts_code": normalized.get("ts_code"),
            "name": normalized.get("name"),
            "pct_chg": normalized.get("pct_change"),
            "main_inflow": main_inflow,
            "main_inflow_pct": main_inflow_pct,
            "super_inflow": super_inflow,
            "big_inflow": big_inflow,
            "mid_inflow": mid_inflow,
            "small_inflow": small_inflow,
        }
    )
