"""Unit tests for the AKShare data source adapter."""

from __future__ import annotations

import inspect
from datetime import date
from typing import Any

import pandas as pd
import pytest
import requests

import data.source.akshare_source as akshare_source_module
from data.source.akshare_source import AKShareSource
from interfaces.data_source import IDataSource
from utils.exception import DataSourceError


class RecordingClient:
    """Simple AKShare-style client stub that records method calls."""

    stock_zh_a_hist: Any
    stock_zh_a_hist_min_em: Any
    stock_zh_a_minute: Any
    stock_zt_pool_em: Any
    stock_hsgt_hold_stock_em: Any
    stock_fund_flow_concept: Any
    stock_fund_flow_industry: Any
    stock_individual_fund_flow: Any

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Any:
        def _method(**kwargs: Any) -> pd.DataFrame:
            self.calls.append((name, kwargs))
            return pd.DataFrame([{"method": name, **kwargs}])

        return _method


@pytest.fixture
def client() -> RecordingClient:
    """Provide a recording client instance."""
    return RecordingClient()


@pytest.fixture
def source(client: RecordingClient) -> AKShareSource:
    """Create the adapter with an injected test client."""
    return AKShareSource(client=client)


@pytest.mark.parametrize(
    ("method_name", "kwargs", "client_method", "expected_kwargs"),
    [
        (
            "fetch_daily_bar",
            {"ts_code": ["000001.SZ", "000002.SZ"], "start_date": date(2024, 1, 1), "end_date": date(2024, 1, 31)},
            "stock_zh_a_hist",
            {"symbol": "000001,000002", "period": "daily", "start_date": "20240101", "end_date": "20240131", "adjust": ""},
        ),
        (
            "fetch_minute_bar",
            {"ts_code": "000001.SZ", "start_date": date(2024, 1, 1), "end_date": date(2024, 1, 2), "freq": "15min"},
            "stock_zh_a_hist_min_em",
            {"symbol": "000001", "period": "15", "start_date": "2024-01-01 09:30:00", "end_date": "2024-01-02 15:00:00", "adjust": ""},
        ),
        (
            "fetch_adj_factor",
            {"ts_code": "000001.SZ", "start_date": date(2024, 1, 1), "end_date": date(2024, 1, 31)},
            "stock_zh_a_daily",
            {"symbol": "000001", "start_date": "20240101", "end_date": "20240131", "adjust": "qfq-factor"},
        ),
        (
            "fetch_daily_basic",
            {"ts_code": "000001.SZ", "trade_date": date(2024, 1, 2), "start_date": None, "end_date": None},
            "stock_a_indicator_lg",
            {"symbol": "000001", "trade_date": "20240102"},
        ),
        (
            "fetch_index_daily",
            {"ts_code": "000300.SH", "start_date": date(2024, 1, 1), "end_date": date(2024, 1, 31)},
            "index_zh_a_hist",
            {"symbol": "000300", "period": "daily", "start_date": "20240101", "end_date": "20240131"},
        ),
        (
            "fetch_limit_pool",
            {"trade_date": date(2024, 1, 2), "kind": "U"},
            "stock_zt_pool_em",
            {"date": "20240102"},
        ),
        ("fetch_stock_basic", {}, "stock_info_a_code_name", {}),
        (
            "fetch_trade_calendar",
            {"start_date": date(2024, 1, 1), "end_date": date(2024, 1, 5)},
            "tool_trade_date_hist_sina",
            {},
        ),
        (
            "fetch_stock_suspend",
            {"trade_date": date(2024, 1, 2), "ts_code": "000001.SZ"},
            "stock_tfp_em",
            {"date": "20240102"},
        ),
        (
            "fetch_income",
            {"ts_code": "000001.SZ", "start_date": date(2023, 1, 1), "end_date": date(2023, 12, 31)},
            "stock_financial_report_sina",
            {"stock": "000001", "symbol": "利润表"},
        ),
        (
            "fetch_balancesheet",
            {"ts_code": "000001.SZ", "start_date": date(2023, 1, 1), "end_date": date(2023, 12, 31)},
            "stock_financial_report_sina",
            {"stock": "000001", "symbol": "资产负债表"},
        ),
        (
            "fetch_cashflow",
            {"ts_code": "000001.SZ", "start_date": date(2023, 1, 1), "end_date": date(2023, 12, 31)},
            "stock_financial_report_sina",
            {"stock": "000001", "symbol": "现金流量表"},
        ),
        (
            "fetch_fina_indicator",
            {"ts_code": "000001.SZ", "start_date": date(2023, 1, 1), "end_date": date(2023, 12, 31)},
            "stock_financial_analysis_indicator",
            {"symbol": "000001"},
        ),
        ("fetch_dividend", {"ts_code": "000001.SZ"}, "stock_dividents_cninfo", {"symbol": "000001"}),
        (
            "fetch_top_list",
            {"trade_date": date(2024, 1, 2)},
            "stock_lhb_detail_em",
            {"start_date": "20240102", "end_date": "20240102"},
        ),
        (
            "fetch_margin_detail",
            {"trade_date": date(2024, 1, 2)},
            "stock_margin_detail_sse",
            {"date": "20240102"},
        ),
        (
            "fetch_stk_holdertrade",
            {"ts_code": "000001.SZ", "ann_date": date(2024, 1, 2)},
            "stock_ggcg_em",
            {"symbol": "全部", "date": "20240102"},
        ),
        (
            "fetch_hk_hold",
            {"trade_date": date(2024, 1, 2), "ts_code": "000001.SZ"},
            "stock_hsgt_hold_stock_em",
            {"market": "北向"},
        ),
        (
            "fetch_concept_money_flow",
            {"trade_date": date(2024, 1, 2)},
            "stock_fund_flow_concept",
            {"symbol": "即时"},
        ),
        (
            "fetch_industry_money_flow",
            {"trade_date": date(2024, 1, 2)},
            "stock_fund_flow_industry",
            {"symbol": "即时"},
        ),
        (
            "fetch_stock_money_flow",
            {"trade_date": date(2024, 1, 2)},
            "stock_individual_fund_flow",
            {"stock": "000001"},
        ),
        ("fetch_concept_list", {}, "stock_board_concept_name_em", {}),
        (
            "fetch_concept_member",
            {"concept_code": "人形机器人"},
            "stock_board_concept_cons_em",
            {"symbol": "人形机器人"},
        ),
        ("fetch_industry_list", {}, "stock_board_industry_name_em", {}),
        (
            "fetch_industry_member",
            {"industry_code": "小金属"},
            "stock_board_industry_cons_em",
            {"symbol": "小金属"},
        ),
        (
            "fetch_index_weight",
            {"index_code": "000300.SH", "trade_date": date(2024, 1, 2)},
            "index_stock_cons_weight_csindex",
            {"symbol": "000300"},
        ),
    ],
)
def test_akshare_methods_delegate_to_expected_client_calls(
    source: AKShareSource,
    client: RecordingClient,
    method_name: str,
    kwargs: dict[str, Any],
    client_method: str,
    expected_kwargs: dict[str, Any],
) -> None:
    """Every interface method should delegate to the mapped AKShare client method."""
    if client_method == "stock_fund_flow_concept":
        def _concept_stub(**call_kwargs: Any) -> pd.DataFrame:
            client.calls.append((client_method, call_kwargs))
            return pd.DataFrame([{"行业": "测试概念", "行业-涨跌幅": 1.0, "净额": 2.0}])
        client.stock_fund_flow_concept = _concept_stub
    elif client_method == "stock_fund_flow_industry":
        def _industry_stub(**call_kwargs: Any) -> pd.DataFrame:
            client.calls.append((client_method, call_kwargs))
            return pd.DataFrame([{"行业": "测试行业", "行业-涨跌幅": 1.0, "净额": 2.0}])
        client.stock_fund_flow_industry = _industry_stub

    result = getattr(source, method_name)(**kwargs)

    assert isinstance(result, pd.DataFrame)
    assert client.calls[-1] == (client_method, expected_kwargs)


def test_akshare_source_is_concrete_and_reports_supported_capabilities() -> None:
    """The adapter implements the full interface and exposes capabilities."""
    assert issubclass(AKShareSource, IDataSource)
    assert inspect.isabstract(AKShareSource) is False

    source = AKShareSource(client=RecordingClient())
    assert source.name == "akshare"
    assert source.supports("daily_bar") is True
    assert source.supports("industry_member") is True
    assert source.supports("missing_capability") is False


def test_akshare_source_wraps_client_errors(client: RecordingClient) -> None:
    """Upstream client exceptions are normalized into DataSourceError."""

    def broken_hist(**kwargs: Any) -> pd.DataFrame:
        raise RuntimeError(f"boom: {kwargs['symbol']}")

    client.stock_zh_a_hist = broken_hist
    source = AKShareSource(client=client)

    with pytest.raises(DataSourceError, match="boom: 000001"):
        source.fetch_daily_bar("000001.SZ")


def test_akshare_source_wraps_requests_connection_errors(client: RecordingClient) -> None:
    """Network-layer requests exceptions are normalized into DataSourceError."""

    def broken_minute(**kwargs: Any) -> pd.DataFrame:
        raise requests.exceptions.ConnectionError("remote disconnected")

    client.stock_zh_a_hist_min_em = broken_minute
    source = AKShareSource(client=client)

    with pytest.raises(DataSourceError, match="remote disconnected"):
        source.fetch_minute_bar("000001.SZ", date(2024, 1, 1), date(2024, 1, 2))


def test_akshare_minute_bar_falls_back_to_sina_when_hist_is_unavailable(client: RecordingClient) -> None:
    """The adapter should degrade to Sina minute bars when Eastmoney minute data is down."""

    def broken_hist(**kwargs: Any) -> pd.DataFrame:
        raise requests.exceptions.ConnectionError("remote disconnected")

    def sina_minute(**kwargs: Any) -> pd.DataFrame:
        client.calls.append(("stock_zh_a_minute", kwargs))
        return pd.DataFrame(
            [
                {
                    "day": "2024-01-04 09:35:00",
                    "open": 10.0,
                    "high": 10.2,
                    "low": 9.9,
                    "close": 10.1,
                    "volume": 1234,
                    "amount": 5678.9,
                }
            ]
        )

    client.stock_zh_a_hist_min_em = broken_hist
    client.stock_zh_a_minute = sina_minute
    source = AKShareSource(client=client)

    result = source.fetch_minute_bar("000001.SZ", date(2024, 1, 4), date(2024, 1, 4), freq="5min")

    assert client.calls == [
        ("stock_zh_a_minute", {"symbol": "sz000001", "period": "5", "adjust": ""})
    ]
    assert result.to_dict(orient="records") == [
        {
            "ts_code": "000001.SZ",
            "datetime": pd.Timestamp("2024-01-04 09:35:00"),
            "freq": "5min",
            "open": 10.0,
            "high": 10.2,
            "low": 9.9,
            "close": 10.1,
            "vol": 1234,
            "amount": 5678.9,
        }
    ]


def test_akshare_minute_bar_falls_back_to_tushare_when_sina_history_window_is_empty(client: RecordingClient) -> None:
    """The adapter should use Tushare as a final historical fallback when Sina cannot cover the requested window."""

    class TushareFallback:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        def fetch_minute_bar(
            self,
            ts_code: str,
            start_date: date,
            end_date: date,
            freq: str = "1min",
        ) -> pd.DataFrame:
            self.calls.append(
                (
                    "fetch_minute_bar",
                    {
                        "ts_code": ts_code,
                        "start_date": start_date,
                        "end_date": end_date,
                        "freq": freq,
                    },
                )
            )
            return pd.DataFrame(
                [
                    {
                        "ts_code": ts_code,
                        "datetime": pd.Timestamp("2024-01-04 09:35:00"),
                        "open": 10.0,
                        "high": 10.2,
                        "low": 9.9,
                        "close": 10.1,
                        "vol": 1234.0,
                        "amount": 5678.0,
                        "freq": freq,
                    }
                ]
            )

    def broken_hist(**kwargs: Any) -> pd.DataFrame:
        raise requests.exceptions.ConnectionError("remote disconnected")

    def sina_minute(**kwargs: Any) -> pd.DataFrame:
        client.calls.append(("stock_zh_a_minute", kwargs))
        return pd.DataFrame(
            [
                {
                    "day": "2026-05-08 15:00:00",
                    "open": 10.0,
                    "high": 10.2,
                    "low": 9.9,
                    "close": 10.1,
                    "volume": 1234,
                    "amount": 5678.9,
                }
            ]
        )

    tushare_fallback = TushareFallback()
    client.stock_zh_a_hist_min_em = broken_hist
    client.stock_zh_a_minute = sina_minute
    source = AKShareSource(client=client, tushare_fallback=tushare_fallback)

    result = source.fetch_minute_bar("000001.SZ", date(2024, 1, 4), date(2024, 1, 5), freq="5min")

    assert client.calls == [
        ("stock_zh_a_minute", {"symbol": "sz000001", "period": "5", "adjust": ""})
    ]
    assert tushare_fallback.calls == [
        (
            "fetch_minute_bar",
            {
                "ts_code": "000001.SZ",
                "start_date": date(2024, 1, 4),
                "end_date": date(2024, 1, 5),
                "freq": "5min",
            },
        )
    ]
    assert result.to_dict(orient="records") == [
        {
            "ts_code": "000001.SZ",
            "datetime": pd.Timestamp("2024-01-04 09:35:00"),
            "open": 10.0,
            "high": 10.2,
            "low": 9.9,
            "close": 10.1,
            "vol": 1234.0,
            "amount": 5678.0,
            "freq": "5min",
        }
    ]


def test_akshare_limit_pool_output_is_normalized_to_standard_columns(
    client: RecordingClient,
) -> None:
    """Chinese AKShare limit-pool columns are normalized to the project schema."""

    def limit_pool(**kwargs: Any) -> pd.DataFrame:
        client.calls.append(("stock_zt_pool_em", kwargs))
        return pd.DataFrame(
            [
                {
                    "代码": "000001",
                    "名称": "平安银行",
                    "最新价": 12.34,
                    "涨跌幅": 9.98,
                    "成交额": 123456789.0,
                    "封板资金": 54321.0,
                    "流通市值": 2000000000.0,
                    "总市值": 3000000000.0,
                    "换手率": 5.67,
                    "首次封板时间": "093100",
                    "最后封板时间": "145600",
                    "炸板次数": 1,
                    "涨停统计": "2/5",
                    "连板数": 2,
                    "所属行业": "银行",
                }
            ]
        )

    client.stock_zt_pool_em = limit_pool
    source = AKShareSource(client=client)

    result = source.fetch_limit_pool(trade_date=date(2024, 1, 2), kind="U")

    assert result.to_dict(orient="records") == [
        {
            "trade_date": date(2024, 1, 2),
            "ts_code": "000001.SZ",
            "name": "平安银行",
            "close": 12.34,
            "pct_chg": 9.98,
            "amount": 123456789.0,
            "fd_amount": 54321.0,
            "float_mv": 2000000000.0,
            "total_mv": 3000000000.0,
            "turnover_ratio": 5.67,
            "first_time": "093100",
            "last_time": "145600",
            "open_times": 1,
            "up_stat": "2/5",
            "limit_times": 2,
            "industry": "银行",
        }
    ]


def test_akshare_daily_bar_output_is_normalized_to_standard_columns(
    client: RecordingClient,
) -> None:
    """AKShare daily bars are renamed to the canonical market-data columns."""

    def daily_bar(**kwargs: Any) -> pd.DataFrame:
        client.calls.append(("stock_zh_a_hist", kwargs))
        return pd.DataFrame(
            [
                {
                    "日期": "2024-01-02",
                    "股票代码": "600000",
                    "开盘": 10.0,
                    "收盘": 10.5,
                    "最高": 10.8,
                    "最低": 9.9,
                    "成交量": 1000.0,
                    "成交额": 10500.0,
                    "振幅": 3.0,
                    "涨跌幅": 5.0,
                    "涨跌额": 0.5,
                    "换手率": 1.2,
                }
            ]
        )

    client.stock_zh_a_hist = daily_bar
    source = AKShareSource(client=client)

    result = source.fetch_daily_bar(
        ts_code="600000.SH",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 2),
    )

    assert result.to_dict(orient="records") == [
        {
            "trade_date": date(2024, 1, 2),
            "ts_code": "600000.SH",
            "open": 10.0,
            "close": 10.5,
            "high": 10.8,
            "low": 9.9,
            "vol": 1000.0,
            "amount": 10500.0,
            "pct_chg": 5.0,
            "change": 0.5,
        }
    ]


def test_akshare_hk_hold_output_is_normalized_to_standard_columns(
    client: RecordingClient,
) -> None:
    """AKShare northbound holding payloads are normalized to the metadata schema."""

    def hk_hold(**kwargs: Any) -> pd.DataFrame:
        client.calls.append(("stock_hsgt_hold_stock_em", kwargs))
        return pd.DataFrame(
            [
                {
                    "代码": "600000",
                    "名称": "浦发银行",
                    "持股数量": 123456.0,
                    "持股占流通股比": 1.23,
                    "交易所": "SH",
                }
            ]
        )

    client.stock_hsgt_hold_stock_em = hk_hold
    source = AKShareSource(client=client)

    result = source.fetch_hk_hold(trade_date=date(2024, 1, 2))

    assert result.to_dict(orient="records") == [
        {
            "trade_date": date(2024, 1, 2),
            "ts_code": "600000.SH",
            "name": "浦发银行",
            "vol": 123456.0,
            "ratio": 1.23,
            "exchange": "SH",
        }
    ]

def test_akshare_concept_money_flow_output_is_normalized_to_standard_columns(
    client: RecordingClient,
) -> None:
    """Concept money-flow payloads are normalized to the metadata schema."""

    def concept_flow(**kwargs: Any) -> pd.DataFrame:
        client.calls.append(("stock_fund_flow_concept", kwargs))
        return pd.DataFrame(
            [
                {
                    "序号": 1,
                    "行业": "F5G概念",
                    "行业指数": 4891.05,
                    "行业-涨跌幅": 3.13,
                    "流入资金": 446.7,
                    "流出资金": 418.09,
                    "净额": 28.61,
                    "公司家数": 36,
                    "领涨股": "东田微",
                    "领涨股-涨跌幅": 20.0,
                    "当前价": 240.4,
                }
            ]
        )

    client.stock_fund_flow_concept = concept_flow
    source = AKShareSource(client=client)

    result = source.fetch_concept_money_flow(trade_date=date(2024, 1, 5))

    assert client.calls == [("stock_fund_flow_concept", {"symbol": "即时"})]
    assert result.to_dict(orient="records") == [
        {
            "trade_date": date(2024, 1, 5),
            "concept_code": "F5G概念",
            "concept_name": "F5G概念",
            "pct_chg": 3.13,
            "main_inflow": 28.61,
            "main_inflow_pct": None,
            "super_inflow": None,
            "big_inflow": None,
            "mid_inflow": None,
            "small_inflow": None,
        }
    ]


def test_akshare_industry_money_flow_output_is_normalized_to_standard_columns(
    client: RecordingClient,
) -> None:
    """Industry money-flow payloads are normalized to the metadata schema."""

    def industry_flow(**kwargs: Any) -> pd.DataFrame:
        client.calls.append(("stock_fund_flow_industry", kwargs))
        return pd.DataFrame(
            [
                {
                    "序号": 1,
                    "行业": "军工装备",
                    "行业指数": 2686.91,
                    "行业-涨跌幅": 3.31,
                    "流入资金": 296.0,
                    "流出资金": 244.29,
                    "净额": 51.71,
                    "公司家数": 83,
                    "领涨股": "电科蓝天",
                    "领涨股-涨跌幅": 19.99,
                    "当前价": 85.64,
                }
            ]
        )

    client.stock_fund_flow_industry = industry_flow
    source = AKShareSource(client=client)

    result = source.fetch_industry_money_flow(trade_date=date(2024, 1, 5))

    assert client.calls == [("stock_fund_flow_industry", {"symbol": "即时"})]
    assert result.to_dict(orient="records") == [
        {
            "trade_date": date(2024, 1, 5),
            "industry_code": "军工装备",
            "industry_name": "军工装备",
            "pct_chg": 3.31,
            "main_inflow": 51.71,
            "main_inflow_pct": None,
            "super_inflow": None,
            "big_inflow": None,
            "mid_inflow": None,
            "small_inflow": None,
        }
    ]


def test_akshare_stock_money_flow_output_is_normalized_to_standard_columns(
    client: RecordingClient,
) -> None:
    """Stock money-flow payloads are normalized to the metadata schema."""

    def stock_flow(**kwargs: Any) -> pd.DataFrame:
        client.calls.append(("stock_individual_fund_flow", kwargs))
        return pd.DataFrame(
            [
                {
                    "日期": date(2024, 1, 5),
                    "收盘价": 12.34,
                    "涨跌幅": 1.23,
                    "主力净流入-净额": 1000.0,
                    "主力净流入-净占比": 10.0,
                    "超大单净流入-净额": 200.0,
                    "超大单净流入-净占比": 2.0,
                    "大单净流入-净额": 300.0,
                    "大单净流入-净占比": 3.0,
                    "中单净流入-净额": 400.0,
                    "中单净流入-净占比": 4.0,
                    "小单净流入-净额": 500.0,
                    "小单净流入-净占比": 5.0,
                }
            ]
        )

    client.stock_individual_fund_flow = stock_flow
    source = AKShareSource(client=client)

    result = source.fetch_stock_money_flow(trade_date=date(2024, 1, 5))

    assert client.calls == [("stock_individual_fund_flow", {"stock": "000001"})]
    assert result.to_dict(orient="records") == [
        {
            "trade_date": date(2024, 1, 5),
            "ts_code": "000001.SZ",
            "name": None,
            "pct_chg": 1.23,
            "main_inflow": 1000.0,
            "main_inflow_pct": 10.0,
            "super_inflow": 200.0,
            "big_inflow": 300.0,
            "mid_inflow": 400.0,
            "small_inflow": 500.0,
        }
    ]


def test_akshare_minute_bar_falls_back_to_tushare_when_sina_payload_is_empty(client: RecordingClient) -> None:
    class TushareFallback:
        def fetch_minute_bar(self, ts_code: str, start_date: date, end_date: date, freq: str = "1min") -> pd.DataFrame:
            return pd.DataFrame([{"ts_code": ts_code, "datetime": pd.Timestamp("2024-01-04 09:35:00"), "freq": freq}])

    client.stock_zh_a_hist_min_em = lambda **kwargs: (_ for _ in ()).throw(requests.exceptions.ConnectionError("remote disconnected"))
    client.stock_zh_a_minute = lambda **kwargs: pd.DataFrame()
    source = AKShareSource(client=client, tushare_fallback=TushareFallback())

    result = source.fetch_minute_bar("000001.SZ", date(2024, 1, 4), date(2024, 1, 4), freq="5min")

    assert result.to_dict(orient="records") == [{"ts_code": "000001.SZ", "datetime": pd.Timestamp("2024-01-04 09:35:00"), "freq": "5min"}]


def test_akshare_minute_bar_falls_back_to_tushare_when_sina_payload_lacks_datetime(client: RecordingClient) -> None:
    class TushareFallback:
        def fetch_minute_bar(self, ts_code: str, start_date: date, end_date: date, freq: str = "1min") -> pd.DataFrame:
            return pd.DataFrame([{"ts_code": ts_code, "datetime": pd.Timestamp("2024-01-04 09:35:00"), "freq": freq}])

    client.stock_zh_a_hist_min_em = lambda **kwargs: (_ for _ in ()).throw(requests.exceptions.ConnectionError("remote disconnected"))
    client.stock_zh_a_minute = lambda **kwargs: pd.DataFrame([{"open": 1.0}])
    source = AKShareSource(client=client, tushare_fallback=TushareFallback())

    result = source.fetch_minute_bar("000001.SZ", date(2024, 1, 4), date(2024, 1, 4), freq="5min")

    assert result.to_dict(orient="records") == [{"ts_code": "000001.SZ", "datetime": pd.Timestamp("2024-01-04 09:35:00"), "freq": "5min"}]


def test_akshare_fetch_limit_pool_rejects_unsupported_kind(source: AKShareSource) -> None:
    with pytest.raises(DataSourceError, match="Unsupported limit pool kind"):
        source.fetch_limit_pool(date(2024, 1, 2), kind="X")


def test_akshare_call_rejects_local_rate_limit_before_request(client: RecordingClient, monkeypatch: pytest.MonkeyPatch) -> None:
    source = AKShareSource(client=client)
    monkeypatch.setattr(source._rate_limiter, "consume", lambda: False)

    with pytest.raises(DataSourceError, match="rate limit exceeded"):
        source._call("stock_zh_a_hist")


def test_akshare_fetch_minute_bar_builds_default_tushare_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    class BuiltFallback:
        def fetch_minute_bar(self, ts_code: str, start_date: date, end_date: date, freq: str = "1min") -> pd.DataFrame:
            return pd.DataFrame([{"ts_code": ts_code, "datetime": pd.Timestamp("2024-01-04 09:35:00"), "freq": freq}])

    class OwnedClient:
        def stock_zh_a_hist_min_em(self, **kwargs: Any) -> pd.DataFrame:
            raise requests.exceptions.ConnectionError("remote disconnected")

    def build_owned_client() -> OwnedClient:
        return OwnedClient()

    monkeypatch.setattr(akshare_source_module, "TushareSource", BuiltFallback)
    monkeypatch.setattr(akshare_source_module, "_create_default_client", build_owned_client)
    source = AKShareSource()

    result = source.fetch_minute_bar("000001.SZ", date(2024, 1, 4), date(2024, 1, 4), freq="5min")

    assert isinstance(source._tushare_fallback, BuiltFallback)
    assert result.to_dict(orient="records") == [{"ts_code": "000001.SZ", "datetime": pd.Timestamp("2024-01-04 09:35:00"), "freq": "5min"}]


def test_akshare_create_default_client_imports_akshare_module(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()
    monkeypatch.setattr(akshare_source_module, "import_module", lambda name: sentinel)

    assert akshare_source_module._create_default_client() is sentinel


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ([], None),
        (["000001.SZ", "600000.SH"], "000001.SZ"),
    ],
)
def test_akshare_first_symbol_handles_none_empty_and_lists(value: Any, expected: str | None) -> None:
    assert akshare_source_module._first_symbol(value) == expected


def test_akshare_join_symbols_handles_none() -> None:
    assert akshare_source_module._join_symbols(None) is None


def test_akshare_normalize_minute_period_rejects_unsupported_freq() -> None:
    with pytest.raises(DataSourceError, match="Unsupported minute frequency"):
        akshare_source_module._normalize_minute_period("2min")


def test_akshare_normalize_frame_returns_empty_frames_unchanged() -> None:
    frame = pd.DataFrame(columns=["日期"])

    result = akshare_source_module._normalize_frame("stock_zh_a_hist", frame, {})

    assert result.empty
    assert result.columns.tolist() == ["日期"]


def test_akshare_normalize_minute_bar_frame_infers_missing_ts_code_and_filters_window() -> None:
    frame = pd.DataFrame(
        [
            {"时间": "2024-01-04 09:29:00", "开盘": 1.0},
            {"时间": "2024-01-04 09:35:00", "开盘": 2.0},
            {"时间": "2024-01-04 15:01:00", "开盘": 3.0},
        ]
    )

    result = akshare_source_module._normalize_minute_bar_frame(
        frame,
        {"period": "5", "start_date": "2024-01-04 09:30:00", "end_date": "2024-01-04 15:00:00"},
    )

    assert result.to_dict(orient="records") == [{"ts_code": None, "datetime": pd.Timestamp("2024-01-04 09:35:00"), "freq": "5min", "open": 2.0}]


def test_akshare_hk_hold_infers_exchange_from_ts_code_when_missing(client: RecordingClient) -> None:
    client.stock_hsgt_hold_stock_em = lambda **kwargs: pd.DataFrame([{"代码": "600000", "名称": "浦发银行", "持股数量": 1.0, "持股占流通股比": 2.0}])
    source = AKShareSource(client=client)

    result = source.fetch_hk_hold(trade_date=date(2024, 1, 2))

    assert result.loc[0, "exchange"] == "SH"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("", None),
        ("600000.SH", "SH"),
        ("600000", "SH"),
        ("000001", "SZ"),
    ],
)
def test_akshare_exchange_from_ts_code(value: Any, expected: str | None) -> None:
    assert akshare_source_module._exchange_from_ts_code(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("600000", "sh600000"),
        ("000001", "sz000001"),
        ("bj430001", "bj430001"),
    ],
)
def test_akshare_normalize_sina_symbol(value: str, expected: str) -> None:
    assert akshare_source_module._normalize_sina_symbol(value) == expected


def test_akshare_minute_freq_from_period_returns_none_for_unknown_period() -> None:
    assert akshare_source_module._minute_freq_from_period("2") is None


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [("430001", "430001.BJ"), ("123456", "123456.SZ")],
)
def test_akshare_with_exchange_suffix_covers_bj_and_default_branches(symbol: str, expected: str) -> None:
    assert akshare_source_module._with_exchange_suffix(symbol) == expected

