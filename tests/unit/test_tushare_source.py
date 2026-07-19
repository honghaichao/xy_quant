"""Unit tests for the Tushare data source adapter."""

from __future__ import annotations

import inspect
from datetime import date
from typing import Any, cast

import pandas as pd
import pytest

import data.source.tushare_source as tushare_source_module
from data.source.tushare_source import TushareSource
from interfaces.data_source import IDataSource
from utils.exception import ConfigError, DataSourceError


class RecordingClient:
    """Simple client stub that records method calls and returns DataFrames."""

    daily: Any
    stk_mins: Any
    pro_bar: Any
    moneyflow: Any

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
def source(client: RecordingClient) -> TushareSource:
    """Create the adapter with an injected test client."""
    return TushareSource(client=client)


@pytest.mark.parametrize(
    ("method_name", "kwargs", "client_method", "expected_kwargs"),
    [
        (
            "fetch_daily_bar",
            {"ts_code": ["000001.SZ", "000002.SZ"], "start_date": date(2024, 1, 1), "end_date": date(2024, 1, 31)},
            "daily",
            {"ts_code": "000001.SZ,000002.SZ", "start_date": "20240101", "end_date": "20240131"},
        ),
        (
            "fetch_minute_bar",
            {"ts_code": "000001.SZ", "start_date": date(2024, 1, 1), "end_date": date(2024, 1, 2), "freq": "5min"},
            "pro_bar",
            {
                "ts_code": "000001.SZ",
                "asset": "E",
                "start_date": "2024-01-01 09:30:00",
                "end_date": "2024-01-02 15:00:00",
                "freq": "5min",
            },
        ),
        (
            "fetch_adj_factor",
            {"ts_code": "000001.SZ", "start_date": date(2024, 1, 1), "end_date": date(2024, 1, 31)},
            "adj_factor",
            {"ts_code": "000001.SZ", "start_date": "20240101", "end_date": "20240131"},
        ),
        (
            "fetch_daily_basic",
            {"ts_code": None, "trade_date": date(2024, 1, 2), "start_date": None, "end_date": None},
            "daily_basic",
            {"trade_date": "20240102"},
        ),
        (
            "fetch_index_daily",
            {"ts_code": "000300.SH", "start_date": date(2024, 1, 1), "end_date": date(2024, 1, 31)},
            "index_daily",
            {"ts_code": "000300.SH", "start_date": "20240101", "end_date": "20240131"},
        ),
        (
            "fetch_limit_pool",
            {"trade_date": date(2024, 1, 2), "kind": "D"},
            "limit_list_d",
            {"trade_date": "20240102", "limit_type": "D"},
        ),
        (
            "fetch_limit_pool",
            {"trade_date": date(2024, 1, 2), "kind": "U"},
            "limit_list_d",
            {"trade_date": "20240102", "limit_type": "U"},
        ),
        (
            "fetch_limit_pool",
            {"trade_date": date(2024, 1, 2), "kind": "Z"},
            "limit_list_d",
            {"trade_date": "20240102", "limit_type": "Z"},
        ),
        ("fetch_stock_basic", {}, "stock_basic", {"exchange": "", "list_status": "L"}),
        (
            "fetch_trade_calendar",
            {"start_date": date(2024, 1, 1), "end_date": date(2024, 1, 5)},
            "trade_cal",
            {"exchange": "SSE", "start_date": "20240101", "end_date": "20240105"},
        ),
        (
            "fetch_stock_suspend",
            {"trade_date": date(2024, 1, 2), "ts_code": "000001.SZ"},
            "suspend_d",
            {"trade_date": "20240102", "ts_code": "000001.SZ"},
        ),
        (
            "fetch_income",
            {"ts_code": "000001.SZ", "start_date": date(2023, 1, 1), "end_date": date(2023, 12, 31)},
            "income",
            {"ts_code": "000001.SZ", "start_date": "20230101", "end_date": "20231231"},
        ),
        (
            "fetch_balancesheet",
            {"ts_code": "000001.SZ", "start_date": date(2023, 1, 1), "end_date": date(2023, 12, 31)},
            "balancesheet",
            {"ts_code": "000001.SZ", "start_date": "20230101", "end_date": "20231231"},
        ),
        (
            "fetch_cashflow",
            {"ts_code": "000001.SZ", "start_date": date(2023, 1, 1), "end_date": date(2023, 12, 31)},
            "cashflow",
            {"ts_code": "000001.SZ", "start_date": "20230101", "end_date": "20231231"},
        ),
        (
            "fetch_fina_indicator",
            {"ts_code": "000001.SZ", "start_date": date(2023, 1, 1), "end_date": date(2023, 12, 31)},
            "fina_indicator",
            {"ts_code": "000001.SZ", "start_date": "20230101", "end_date": "20231231"},
        ),
        ("fetch_dividend", {"ts_code": "000001.SZ"}, "dividend", {"ts_code": "000001.SZ"}),
        (
            "fetch_top_list",
            {"trade_date": date(2024, 1, 2)},
            "top_list",
            {"trade_date": "20240102"},
        ),
        (
            "fetch_margin_detail",
            {"trade_date": date(2024, 1, 2)},
            "margin_detail",
            {"trade_date": "20240102"},
        ),
        (
            "fetch_stk_holdertrade",
            {"ts_code": "000001.SZ", "ann_date": date(2024, 1, 2)},
            "stk_holdertrade",
            {"ts_code": "000001.SZ", "ann_date": "20240102"},
        ),
        (
            "fetch_hk_hold",
            {"trade_date": date(2024, 1, 2), "ts_code": "000001.SZ"},
            "hk_hold",
            {"trade_date": "20240102", "ts_code": "000001.SZ"},
        ),
        (
            "fetch_concept_money_flow",
            {"trade_date": date(2024, 1, 2)},
            "concept_moneyflow",
            {"trade_date": "20240102"},
        ),
        (
            "fetch_industry_money_flow",
            {"trade_date": date(2024, 1, 2)},
            "industry_moneyflow",
            {"trade_date": "20240102"},
        ),
        (
            "fetch_stock_money_flow",
            {"trade_date": date(2024, 1, 2)},
            "moneyflow",
            {"trade_date": "20240102"},
        ),
        ("fetch_concept_list", {}, "concept", {}),
        (
            "fetch_concept_member",
            {"concept_code": "TS1001"},
            "concept_detail",
            {"id": "TS1001"},
        ),
        ("fetch_industry_list", {}, "index_classify", {"src": "SW2021"}),
        (
            "fetch_industry_member",
            {"industry_code": "801010.SI"},
            "index_member",
            {"index_code": "801010.SI"},
        ),
        (
            "fetch_index_weight",
            {"index_code": "000300.SH", "trade_date": date(2024, 1, 2)},
            "index_weight",
            {"index_code": "000300.SH", "trade_date": "20240102"},
        ),
    ],
)
def test_tushare_methods_delegate_to_expected_client_calls(
    source: TushareSource,
    client: RecordingClient,
    method_name: str,
    kwargs: dict[str, Any],
    client_method: str,
    expected_kwargs: dict[str, Any],
) -> None:
    """Every interface method should delegate to the mapped Tushare client method."""
    result = getattr(source, method_name)(**kwargs)

    assert isinstance(result, pd.DataFrame)
    assert client.calls[-1] == (client_method, expected_kwargs)


def test_tushare_source_is_concrete_and_reports_supported_capabilities() -> None:
    """The adapter implements the full interface and exposes capabilities."""
    assert issubclass(TushareSource, IDataSource)
    assert inspect.isabstract(TushareSource) is False

    source = TushareSource(client=RecordingClient())
    assert source.supports("minute_bar")
    assert source.supports("daily_bar")
    assert not source.supports("made_up_capability")


class ChunkRecordingClient:
    """Client stub that returns one row per request so chunking is observable."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Any:
        def _method(**kwargs: Any) -> pd.DataFrame:
            self.calls.append((name, kwargs))
            return pd.DataFrame([
                {
                    "ts_code": kwargs["ts_code"],
                    "trade_time": kwargs["start_date"],
                    "open": 1.0,
                    "high": 1.0,
                    "low": 1.0,
                    "close": 1.0,
                    "vol": 1.0,
                    "amount": 1.0,
                }
            ])

        return _method


def test_tushare_minute_bar_fetch_splits_large_ranges_into_multiple_calls() -> None:
    """Minute-bar fetching should split long ranges to avoid endpoint caps."""
    client = ChunkRecordingClient()
    source = TushareSource(client=client)

    result = source.fetch_minute_bar(
        "000001.SZ",
        date(2024, 1, 1),
        date(2024, 3, 31),
        freq="5min",
    )

    assert len(client.calls) == 4
    assert [call[0] for call in client.calls] == ["pro_bar", "pro_bar", "pro_bar", "pro_bar"]
    assert client.calls[0][1]["start_date"] == "2024-01-01 09:30:00"
    assert client.calls[0][1]["end_date"] == "2024-01-30 15:00:00"
    assert client.calls[1][1]["start_date"] == "2024-01-31 09:30:00"
    assert client.calls[1][1]["end_date"] == "2024-02-29 15:00:00"
    assert client.calls[2][1]["start_date"] == "2024-03-01 09:30:00"
    assert client.calls[2][1]["end_date"] == "2024-03-30 15:00:00"
    assert client.calls[3][1]["start_date"] == "2024-03-31 09:30:00"
    assert client.calls[3][1]["end_date"] == "2024-03-31 15:00:00"
    assert all(call[1]["asset"] == "E" for call in client.calls)
    assert len(result) == len(client.calls)
    assert result["ts_code"].tolist() == [call[1]["ts_code"] for call in client.calls]
    assert result["freq"].tolist() == ["5min"] * len(client.calls)



def test_tushare_source_wraps_client_errors(client: RecordingClient) -> None:
    """Upstream client exceptions are normalized into DataSourceError."""

    def broken_daily(**kwargs: Any) -> pd.DataFrame:
        raise RuntimeError(f"boom: {kwargs['ts_code']}")

    client.daily = broken_daily
    source = TushareSource(client=client)

    with pytest.raises(DataSourceError, match="boom: 000001.SZ"):
        source.fetch_daily_bar(ts_code="000001.SZ")


def test_tushare_source_normalizes_minute_bar_columns(client: RecordingClient) -> None:
    """Minute-bar payloads are normalized to the DuckDB schema contract."""

    def fake_pro_bar(**kwargs: Any) -> pd.DataFrame:
        client.calls.append(("pro_bar", kwargs))
        return pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_time": "2024-02-20 09:31:00",
                    "open": 10.0,
                    "high": 10.2,
                    "low": 9.9,
                    "close": 10.1,
                    "vol": 1234.0,
                    "amount": 5678.0,
                    "trade_date": "20240220",
                    "pre_close": 9.95,
                    "change": 0.15,
                    "pct_chg": 1.51,
                }
            ]
        )

    client.pro_bar = fake_pro_bar
    source = TushareSource(client=client)

    result = source.fetch_minute_bar(
        ts_code="000001.SZ",
        start_date=date(2024, 2, 20),
        end_date=date(2024, 2, 20),
        freq="1min",
    )

    assert "trade_time" not in result.columns
    assert result.columns.tolist() == [
        "ts_code",
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "vol",
        "amount",
        "freq",
    ]
    assert result.loc[0, "datetime"] == pd.Timestamp("2024-02-20 09:31:00")
    assert result.loc[0, "freq"] == "1min"


def test_tushare_source_falls_back_to_supported_moneyflow_endpoints_when_legacy_names_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = TushareSource(client=RecordingClient())
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_call(method_name: str, **kwargs: Any) -> pd.DataFrame:
        calls.append((method_name, kwargs))
        if method_name in {"concept_moneyflow", "industry_moneyflow"}:
            raise DataSourceError("请指定正确的接口名")
        if method_name == "moneyflow_ths":
            return pd.DataFrame(
                [
                    {
                        "trade_date": "20240220",
                        "ts_code": "885001.TI",
                        "name": "人形机器人",
                        "pct_change": 5.2,
                        "net_amount": 123.4,
                        "buy_lg_amount_rate": 1.5,
                        "buy_lg_amount": 80.0,
                        "buy_md_amount": 30.0,
                        "buy_sm_amount": 13.4,
                    }
                ]
            )
        if method_name == "moneyflow_ind_dc":
            return pd.DataFrame(
                [
                    {
                        "trade_date": "20240220",
                        "ts_code": "BK0420.DC",
                        "name": "汽车整车",
                        "pct_change": 2.3,
                        "net_amount": 456.7,
                        "net_amount_rate": 3.4,
                        "buy_elg_amount": 200.0,
                        "buy_lg_amount": 150.0,
                        "buy_md_amount": 70.0,
                        "buy_sm_amount": 36.7,
                    }
                ]
            )
        raise AssertionError(f"unexpected method: {method_name}")

    monkeypatch.setattr(source, "_call", fake_call)

    concept = source.fetch_concept_money_flow(date(2024, 2, 20))
    industry = source.fetch_industry_money_flow(date(2024, 2, 20))

    assert calls[:2] == [
        ("concept_moneyflow", {"trade_date": "20240220"}),
        ("moneyflow_ths", {"trade_date": "20240220"}),
    ]
    assert calls[2:] == [
        ("industry_moneyflow", {"trade_date": "20240220"}),
        ("moneyflow_ind_dc", {"trade_date": "20240220"}),
    ]
    assert concept.loc[0, "concept_code"] == "885001.TI"
    assert concept.loc[0, "concept_name"] == "人形机器人"
    assert concept.loc[0, "main_inflow"] == 123.4
    assert industry.loc[0, "industry_code"] == "BK0420.DC"
    assert industry.loc[0, "industry_name"] == "汽车整车"
    assert industry.loc[0, "super_inflow"] == 200.0


def test_tushare_source_normalizes_stock_money_flow_columns(client: RecordingClient) -> None:
    def fake_moneyflow(**kwargs: Any) -> pd.DataFrame:
        client.calls.append(("moneyflow", kwargs))
        return pd.DataFrame(
            [
                {
                    "trade_date": "20240220",
                    "ts_code": "000001.SZ",
                    "buy_sm_amount": 100.0,
                    "sell_sm_amount": 40.0,
                    "buy_md_amount": 60.0,
                    "sell_md_amount": 10.0,
                    "buy_lg_amount": 90.0,
                    "sell_lg_amount": 30.0,
                    "buy_elg_amount": 50.0,
                    "sell_elg_amount": 20.0,
                }
            ]
        )

    client.moneyflow = fake_moneyflow
    source = TushareSource(client=client)

    result = source.fetch_stock_money_flow(date(2024, 2, 20))

    assert client.calls[-1] == ("moneyflow", {"trade_date": "20240220"})
    assert result.columns.tolist() == [
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
    assert result.loc[0, "super_inflow"] == 30.0
    assert result.loc[0, "big_inflow"] == 60.0
    assert result.loc[0, "mid_inflow"] == 50.0
    assert result.loc[0, "small_inflow"] == 60.0
    assert result.loc[0, "main_inflow"] == 90.0
    assert result.loc[0, "main_inflow_pct"] == pytest.approx(30.0)


def test_tushare_source_retries_moneyflow_ths_rate_limit_with_rule_based_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = TushareSource(client=RecordingClient())
    calls: list[tuple[str, dict[str, Any]]] = []
    sleeps: list[float] = []

    def fake_call(method_name: str, **kwargs: Any) -> pd.DataFrame:
        calls.append((method_name, kwargs))
        if method_name == "concept_moneyflow":
            raise DataSourceError("请指定正确的接口名")
        if method_name == "moneyflow_ths" and len([name for name, _ in calls if name == "moneyflow_ths"]) == 1:
            raise DataSourceError(
                "抱歉，您访问接口(moneyflow_ths)频率超限(2次/分钟)，具体频次详情：https://tushare.pro/document/1?doc_id=108。"
            )
        if method_name == "moneyflow_ths":
            return pd.DataFrame(
                [
                    {
                        "trade_date": "20240220",
                        "ts_code": "885001.TI",
                        "name": "人形机器人",
                        "pct_change": 5.2,
                        "net_amount": 123.4,
                        "buy_lg_amount_rate": 1.5,
                        "buy_lg_amount": 80.0,
                        "buy_md_amount": 30.0,
                        "buy_sm_amount": 13.4,
                    }
                ]
            )
        raise AssertionError(f"unexpected method: {method_name}")

    monkeypatch.setattr(source, "_call", fake_call)
    monkeypatch.setattr("data.source.tushare_source.sleep", lambda seconds: sleeps.append(seconds))

    result = source.fetch_concept_money_flow(date(2024, 2, 20))

    assert calls == [
        ("concept_moneyflow", {"trade_date": "20240220"}),
        ("moneyflow_ths", {"trade_date": "20240220"}),
        ("moneyflow_ths", {"trade_date": "20240220"}),
    ]
    assert sleeps == [30.0]
    assert result.loc[0, "concept_code"] == "885001.TI"


def test_tushare_source_retries_moneyflow_industry_rate_limit_with_rule_based_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = TushareSource(client=RecordingClient())
    calls: list[tuple[str, dict[str, Any]]] = []
    sleeps: list[float] = []

    def fake_call(method_name: str, **kwargs: Any) -> pd.DataFrame:
        calls.append((method_name, kwargs))
        if method_name == "industry_moneyflow":
            raise DataSourceError("请指定正确的接口名")
        if method_name == "moneyflow_ind_dc" and len([name for name, _ in calls if name == "moneyflow_ind_dc"]) == 1:
            raise DataSourceError(
                "抱歉，您访问接口(moneyflow_ind_dc)频率超限(60次/小时)，具体频次详情：https://tushare.pro/document/1?doc_id=108。"
            )
        if method_name == "moneyflow_ind_dc":
            return pd.DataFrame(
                [
                    {
                        "trade_date": "20240220",
                        "ts_code": "BK0420.DC",
                        "name": "汽车整车",
                        "pct_change": 2.3,
                        "net_amount": 456.7,
                        "net_amount_rate": 3.4,
                        "buy_elg_amount": 200.0,
                        "buy_lg_amount": 150.0,
                        "buy_md_amount": 70.0,
                        "buy_sm_amount": 36.7,
                    }
                ]
            )
        raise AssertionError(f"unexpected method: {method_name}")

    monkeypatch.setattr(source, "_call", fake_call)
    monkeypatch.setattr("data.source.tushare_source.sleep", lambda seconds: sleeps.append(seconds))

    result = source.fetch_industry_money_flow(date(2024, 2, 20))

    assert calls == [
        ("industry_moneyflow", {"trade_date": "20240220"}),
        ("moneyflow_ind_dc", {"trade_date": "20240220"}),
        ("moneyflow_ind_dc", {"trade_date": "20240220"}),
    ]
    assert sleeps == [60.0]
    assert result.loc[0, "industry_code"] == "BK0420.DC"


def test_tushare_source_stops_supported_moneyflow_retry_after_max_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = TushareSource(client=RecordingClient())
    calls: list[tuple[str, dict[str, Any]]] = []
    sleeps: list[float] = []

    def fake_call(method_name: str, **kwargs: Any) -> pd.DataFrame:
        calls.append((method_name, kwargs))
        if method_name == "concept_moneyflow":
            raise DataSourceError("请指定正确的接口名")
        if method_name == "moneyflow_ths":
            raise DataSourceError(
                "抱歉，您访问接口(moneyflow_ths)频率超限(2次/分钟)，具体频次详情：https://tushare.pro/document/1?doc_id=108。"
            )
        raise AssertionError(f"unexpected method: {method_name}")

    monkeypatch.setattr(source, "_call", fake_call)
    monkeypatch.setattr("data.source.tushare_source.sleep", lambda seconds: sleeps.append(seconds))

    with pytest.raises(DataSourceError, match="exceeded remote rate-limit retry budget"):
        source.fetch_concept_money_flow(date(2024, 2, 20))

    assert calls == [
        ("concept_moneyflow", {"trade_date": "20240220"}),
        ("moneyflow_ths", {"trade_date": "20240220"}),
        ("moneyflow_ths", {"trade_date": "20240220"}),
        ("moneyflow_ths", {"trade_date": "20240220"}),
    ]
    assert sleeps == [30.0, 30.0]


def test_tushare_source_stops_supported_industry_moneyflow_retry_after_max_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = TushareSource(client=RecordingClient())
    calls: list[tuple[str, dict[str, Any]]] = []
    sleeps: list[float] = []

    def fake_call(method_name: str, **kwargs: Any) -> pd.DataFrame:
        calls.append((method_name, kwargs))
        if method_name == "industry_moneyflow":
            raise DataSourceError("请指定正确的接口名")
        if method_name == "moneyflow_ind_dc":
            raise DataSourceError(
                "抱歉，您访问接口(moneyflow_ind_dc)频率超限(60次/小时)，具体频次详情：https://tushare.pro/document/1?doc_id=108。"
            )
        raise AssertionError(f"unexpected method: {method_name}")

    monkeypatch.setattr(source, "_call", fake_call)
    monkeypatch.setattr("data.source.tushare_source.sleep", lambda seconds: sleeps.append(seconds))

    with pytest.raises(DataSourceError, match="exceeded remote rate-limit retry budget"):
        source.fetch_industry_money_flow(date(2024, 2, 20))

    assert calls == [
        ("industry_moneyflow", {"trade_date": "20240220"}),
        ("moneyflow_ind_dc", {"trade_date": "20240220"}),
        ("moneyflow_ind_dc", {"trade_date": "20240220"}),
        ("moneyflow_ind_dc", {"trade_date": "20240220"}),
    ]
    assert sleeps == [60.0, 60.0]


def test_tushare_minute_bar_rate_limiter_uses_configured_per_minute_capacity() -> None:
    source = TushareSource(client=RecordingClient())

    assert source._minute_bar_rate_limiter.capacity == tushare_source_module.settings.minute_bar_rate_limit_per_min
    assert source._minute_bar_rate_limiter.refill_rate == pytest.approx(
        tushare_source_module.settings.minute_bar_rate_limit_per_min / 60
    )



def test_tushare_minute_bar_uses_only_minute_bar_rate_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    source = TushareSource(client=RecordingClient())
    minute_bar_acquires: list[int] = []
    default_acquires: list[int] = []

    def fake_minute_bar_acquire(tokens: int = 1) -> bool:
        minute_bar_acquires.append(tokens)
        return True

    def fake_default_acquire(tokens: int = 1) -> bool:
        default_acquires.append(tokens)
        return True

    def fake_call(method_name: str, **kwargs: Any) -> pd.DataFrame:
        assert method_name == "pro_bar"
        return pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_time": "2024-02-20 09:31:00",
                    "open": 10.0,
                    "high": 10.2,
                    "low": 9.9,
                    "close": 10.1,
                    "vol": 1234.0,
                    "amount": 5678.0,
                }
            ]
        )

    monkeypatch.setattr(source._minute_bar_rate_limiter, "acquire", fake_minute_bar_acquire)
    monkeypatch.setattr(source._rate_limiter, "acquire", fake_default_acquire)
    monkeypatch.setattr(source, "_call", fake_call)

    result = source.fetch_minute_bar(
        ts_code="000001.SZ",
        start_date=date(2024, 2, 20),
        end_date=date(2024, 2, 20),
        freq="1min",
    )

    assert minute_bar_acquires == [1]
    assert default_acquires == []
    assert result.loc[0, "freq"] == "1min"



def test_tushare_minute_bar_waits_and_retries_on_remote_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    source = TushareSource(client=RecordingClient())
    retries: list[float] = []
    acquire_calls: list[int] = []
    call_count = 0

    def fake_acquire(tokens: int = 1) -> bool:
        acquire_calls.append(tokens)
        return True

    def fake_call(method_name: str, **kwargs: Any) -> pd.DataFrame:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise DataSourceError(
                "抱歉，您访问接口(stk_mins)频率超限(2次/分钟)，具体频次详情：https://tushare.pro/document/1?doc_id=108。"
            )
        return tushare_source_module._normalize_tushare_frame(
            pd.DataFrame(
                [
                    {
                        "ts_code": "000001.SZ",
                        "trade_time": "2024-02-20 09:31:00",
                        "open": 10.0,
                        "high": 10.2,
                        "low": 9.9,
                        "close": 10.1,
                        "vol": 1234.0,
                        "amount": 5678.0,
                    }
                ]
            ),
            request_kwargs=kwargs,
        )

    def fake_sleep(seconds: float) -> None:
        retries.append(seconds)

    monkeypatch.setattr(source, "_call", fake_call)
    monkeypatch.setattr(source._minute_bar_rate_limiter, "acquire", fake_acquire)
    monkeypatch.setattr(tushare_source_module, "sleep", fake_sleep)

    result = source.fetch_minute_bar(
        ts_code="000001.SZ",
        start_date=date(2024, 2, 20),
        end_date=date(2024, 2, 20),
        freq="5min",
    )

    assert call_count == 2
    assert acquire_calls == [1, 1]
    assert retries == [30.0]
    assert result.loc[0, "datetime"] == pd.Timestamp("2024-02-20 09:31:00")
    assert result.loc[0, "freq"] == "5min"


def test_tushare_limit_pool_falls_back_to_stk_limit_for_minute_limit_list_restriction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = TushareSource(client=RecordingClient())
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_call(method_name: str, **kwargs: Any) -> pd.DataFrame:
        calls.append((method_name, kwargs))
        if method_name == "limit_list_d":
            raise DataSourceError(
                "抱歉，您访问接口(limit_list_d)频率超限(1次/分钟)，具体频次详情：https://tushare.pro/document/1?doc_id=108。"
            )
        if method_name == "stk_limit":
            return pd.DataFrame(
                [{"trade_date": "20240220", "ts_code": "000001.SZ", "up_limit": 11.0, "down_limit": 9.0}]
            )
        if method_name == "daily":
            return pd.DataFrame(
                [{"trade_date": "20240220", "ts_code": "000001.SZ", "close": 11.0, "pct_chg": 10.0, "amount": 12345.0}]
            )
        if method_name == "daily_basic":
            return pd.DataFrame(
                [{"trade_date": "20240220", "ts_code": "000001.SZ", "turnover_rate": 1.2, "float_mv": 200000.0, "total_mv": 300000.0}]
            )
        raise AssertionError(f"unexpected method: {method_name}")

    monkeypatch.setattr(source, "_call", fake_call)

    result = source.fetch_limit_pool(trade_date=date(2024, 2, 20), kind="U")

    assert [name for name, _ in calls] == ["limit_list_d", "stk_limit", "daily", "daily_basic"]
    assert result.loc[0, "ts_code"] == "000001.SZ"
    assert result.loc[0, "limit"] == "U"


def test_tushare_limit_pool_falls_back_to_stk_limit_for_hourly_limit_list_restriction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = TushareSource(client=RecordingClient())
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_limit_list_call(method_name: str, **kwargs: Any) -> pd.DataFrame:
        raise DataSourceError(
            "抱歉，您访问接口(limit_list_d)频率超限(1次/小时)，具体频次详情：https://tushare.pro/document/1?doc_id=108。"
        )

    def fake_call(method_name: str, **kwargs: Any) -> pd.DataFrame:
        calls.append((method_name, kwargs))
        if method_name == "stk_limit":
            return pd.DataFrame(
                [
                    {"trade_date": "20240508", "ts_code": "000001.SZ", "up_limit": 11.0, "down_limit": 9.0},
                    {"trade_date": "20240508", "ts_code": "000002.SZ", "up_limit": 12.0, "down_limit": 10.0},
                ]
            )
        if method_name == "daily":
            return pd.DataFrame(
                [
                    {
                        "trade_date": "20240508",
                        "ts_code": "000001.SZ",
                        "close": 11.0,
                        "pct_chg": 10.0,
                        "amount": 12345.0,
                    },
                    {
                        "trade_date": "20240508",
                        "ts_code": "000002.SZ",
                        "close": 11.5,
                        "pct_chg": 3.0,
                        "amount": 6789.0,
                    },
                ]
            )
        if method_name == "daily_basic":
            return pd.DataFrame(
                [
                    {
                        "trade_date": "20240508",
                        "ts_code": "000001.SZ",
                        "turnover_rate": 1.2,
                        "float_mv": 200000.0,
                        "total_mv": 300000.0,
                    },
                    {
                        "trade_date": "20240508",
                        "ts_code": "000002.SZ",
                        "turnover_rate": 0.8,
                        "float_mv": 150000.0,
                        "total_mv": 250000.0,
                    },
                ]
            )
        raise AssertionError(f"unexpected method: {method_name}")

    monkeypatch.setattr(source, "_call", fake_call)

    def fake_limit_list_entrypoint(method_name: str, **kwargs: Any) -> pd.DataFrame:
        if method_name == "limit_list_d":
            return fake_limit_list_call(method_name, **kwargs)
        return fake_call(method_name, **kwargs)

    monkeypatch.setattr(source, "_call", fake_limit_list_entrypoint)

    result = source.fetch_limit_pool(trade_date=date(2024, 5, 8), kind="U")

    assert calls == [
        ("stk_limit", {"trade_date": "20240508"}),
        ("daily", {"start_date": "20240508", "end_date": "20240508"}),
        ("daily_basic", {"trade_date": "20240508"}),
    ]
    assert result.to_dict(orient="records") == [
        {
            "trade_date": date(2024, 5, 8),
            "ts_code": "000001.SZ",
            "name": None,
            "close": 11.0,
            "pct_chg": 10.0,
            "amount": 12345.0,
            "limit_amount": None,
            "float_mv": 200000.0,
            "total_mv": 300000.0,
            "turnover_ratio": 1.2,
            "fd_amount": None,
            "first_time": None,
            "last_time": None,
            "open_times": None,
            "up_stat": None,
            "limit_times": None,
            "limit": "U",
        }
    ]


def test_tushare_source_normalizes_date_columns(client: RecordingClient) -> None:
    """Date-like columns from Tushare are converted out of raw YYYYMMDD strings."""

    def fake_daily(**kwargs: Any) -> pd.DataFrame:
        client.calls.append(("daily", kwargs))
        return pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20240220",
                    "list_date": "19910403",
                    "close": 10.2,
                }
            ]
        )

    client.daily = fake_daily
    source = TushareSource(client=client)

    result = source.fetch_daily_bar(ts_code="000001.SZ")

    assert result.loc[0, "trade_date"] == date(2024, 2, 20)
    assert result.loc[0, "list_date"] == date(1991, 4, 3)
    assert result.loc[0, "close"] == 10.2


def test_tushare_minute_bar_bubbles_non_rate_limit_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    source = TushareSource(client=RecordingClient())

    monkeypatch.setattr(source._minute_bar_rate_limiter, "acquire", lambda tokens=1: True)
    monkeypatch.setattr(source, "_call", lambda method_name, **kwargs: (_ for _ in ()).throw(DataSourceError("boom")))

    with pytest.raises(DataSourceError, match="boom"):
        source.fetch_minute_bar("000001.SZ", date(2024, 2, 20), date(2024, 2, 20))


def test_tushare_create_default_client_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    module_any = cast(Any, tushare_source_module)
    monkeypatch.setattr(module_any.settings, "tushare_token", "")

    with pytest.raises(ConfigError, match="Tushare token is required"):
        tushare_source_module._create_default_client()


def test_tushare_create_default_client_sets_token_and_exposes_pro_bar(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    sentinel = object()
    pro_bar_sentinel = object()
    module_any = cast(Any, tushare_source_module)
    monkeypatch.setattr(module_any.settings, "tushare_token", "test-token")
    monkeypatch.setattr(module_any.ts, "set_token", lambda value: captured.setdefault("token", value))
    monkeypatch.setattr(module_any.ts, "pro_api", lambda: sentinel)
    monkeypatch.setattr(module_any.ts, "pro_bar", pro_bar_sentinel)

    client = tushare_source_module._create_default_client()

    assert client._pro is sentinel
    assert client.pro_bar is pro_bar_sentinel
    assert captured == {"token": "test-token"}


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("普通错误", None),
        ("抱歉，您访问接口(stk_mins)频率超限，稍后再试。", 30.0),
        ("抱歉，您访问接口(stk_mins)频率超限(6次/分钟)，稍后再试。", 10.0),
        ("抱歉，您访问接口(limit_list_d)频率超限(1次/小时)，稍后再试。", 3600.0),
    ],
)
def test_parse_remote_rate_limit_wait_seconds(message: str, expected: float | None) -> None:
    assert tushare_source_module._parse_remote_rate_limit_wait_seconds(message) == expected


def test_tushare_stock_money_flow_retries_on_remote_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    source = TushareSource(client=RecordingClient())
    calls: list[tuple[str, dict[str, Any]]] = []
    sleeps: list[float] = []

    def fake_call(method_name: str, **kwargs: Any) -> pd.DataFrame:
        request_kwargs = dict(kwargs)
        request_kwargs.pop("acquire_rate_limit", None)
        calls.append((method_name, request_kwargs))
        if len(calls) == 1:
            raise DataSourceError("抱歉，您访问接口(moneyflow)频率超限(2次/分钟)，稍后再试。")
        return pd.DataFrame(
            [
                {
                    "trade_date": "20240229",
                    "ts_code": "000001.SZ",
                    "name": "平安银行",
                    "pct_change": 1.2,
                    "buy_elg_amount": 100.0,
                    "sell_elg_amount": 40.0,
                    "buy_lg_amount": 80.0,
                    "sell_lg_amount": 20.0,
                    "buy_md_amount": 30.0,
                    "sell_md_amount": 10.0,
                    "buy_sm_amount": 10.0,
                    "sell_sm_amount": 5.0,
                }
            ]
        )

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(source._rate_limiter, "acquire", lambda tokens=1: True)
    monkeypatch.setattr(source, "_call", fake_call)
    monkeypatch.setattr(tushare_source_module, "sleep", fake_sleep)

    result = source.fetch_stock_money_flow(date(2024, 2, 29))

    assert sleeps == [30.0]
    assert calls == [
        ("moneyflow", {"trade_date": "20240229"}),
        ("moneyflow", {"trade_date": "20240229"}),
    ]
    assert result.loc[0, "ts_code"] == "000001.SZ"
    assert result.loc[0, "main_inflow"] == 120.0


def test_normalize_tushare_frame_returns_empty_frame_unchanged() -> None:
    frame = pd.DataFrame(columns=["trade_date"])

    result = tushare_source_module._normalize_tushare_frame(frame)

    assert result.empty
    assert result.columns.tolist() == ["trade_date"]


def test_normalize_date_series_falls_back_to_generic_datetime_parsing() -> None:
    series = pd.Series(["2024-02-20", "2024-02-21"])

    result = tushare_source_module._normalize_date_series(series)

    assert result.tolist() == [date(2024, 2, 20), date(2024, 2, 21)]


def test_normalize_date_series_preserves_unparseable_values() -> None:
    series = pd.Series(["bad-date", "still-bad"])

    result = tushare_source_module._normalize_date_series(series)

    assert result.equals(series)


def test_normalize_datetime_series_preserves_unparseable_values() -> None:
    series = pd.Series(["bad-datetime"])

    result = tushare_source_module._normalize_datetime_series(series)

    assert result.equals(series)
