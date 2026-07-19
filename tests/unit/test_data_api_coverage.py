"""Additional branch-coverage tests for data.api."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

import data.api as data_api


def test_helper_validators_and_selectors_cover_edge_cases() -> None:
    assert data_api._ensure_code_list(None) == []
    assert data_api._ensure_code_list("000001.SZ") == ["000001.SZ"]
    assert data_api._ensure_code_list(["000001.SZ"]) == ["000001.SZ"]
    assert data_api._price_date_column("5m") == "datetime"
    assert data_api._price_date_column("daily") == "trade_date"
    assert data_api._normalize_frequency("1D") == "1d"
    assert data_api._infer_date_column(pd.DataFrame([{"value": 1}]), ("end_date", "trade_date")) is None
    assert data_api._resolve_code_column(pd.DataFrame(), "stock") == "ts_code"
    assert data_api._resolve_code_column(pd.DataFrame(), "concept") == "concept_code"
    assert data_api._resolve_code_column(pd.DataFrame(), "industry") == "industry_code"

    with pytest.raises(ValueError, match="Unsupported fq mode"):
        data_api._validate_fq("forward")
    with pytest.raises(ValueError, match="Unsupported price frequency"):
        data_api._price_table("000001.SZ", "weekly")
    with pytest.raises(ValueError, match="Unsupported table"):
        data_api._validate_table("mystery", ("known",))


def test_get_price_filters_minute_frequency_and_selected_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "datetime": "2024-01-01 09:31:00", "freq": "1m", "close": 10.0, "vol": 1},
            {"ts_code": "000001.SZ", "datetime": "2024-01-01 09:35:00", "freq": "5m", "close": 10.5, "vol": 2},
            {"ts_code": "000002.SZ", "datetime": "2024-01-01 09:35:00", "freq": "5m", "close": 20.5, "vol": 3},
        ]
    )
    monkeypatch.setattr(data_api, "_load_price_frame", lambda security, frequency: frame)

    result = data_api.get_price(
        "000001.SZ",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 1),
        frequency="5M",
        fields=["ts_code", "close"],
    )

    assert result.to_dict("records") == [{"ts_code": "000001.SZ", "close": 10.5}]


def test_get_fundamentals_without_date_column_sorts_by_ts_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        data_api,
        "_query_meta_table",
        lambda table: pd.DataFrame([
            {"ts_code": "600000.SH", "metric": 2, "other": "b"},
            {"ts_code": "000001.SZ", "metric": 1, "other": "a"},
        ]),
    )

    result = data_api.get_fundamentals("income", ["600000.SH", "000001.SZ"], fields=["ts_code", "metric"])

    assert result.to_dict("records") == [
        {"ts_code": "000001.SZ", "metric": 1},
        {"ts_code": "600000.SH", "metric": 2},
    ]


def test_get_index_stocks_trade_days_and_security_info_empty_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_query(table: str) -> pd.DataFrame:
        if table == "index_weight":
            return pd.DataFrame([{"index_code": "000300.SH", "trade_date": "2024-01-02", "ts_code": "000001.SZ"}])
        if table == "trade_calendar":
            return pd.DataFrame()
        if table == "stock_basic":
            return pd.DataFrame([{"ts_code": "000001.SZ", "name": "Ping An"}])
        raise AssertionError(table)

    monkeypatch.setattr(data_api, "_query_meta_table", fake_query)

    assert data_api.get_index_stocks("000300.SH", date(2024, 1, 1)) == []
    assert data_api.get_trade_days(date(2024, 1, 1), date(2024, 1, 31)) == []
    assert data_api.get_security_info("999999.SZ") == {}


def test_attribute_history_handles_non_positive_count_and_minute_frequency(monkeypatch: pytest.MonkeyPatch) -> None:
    empty = data_api.attribute_history("000001.SZ", 0, fields=["close"])
    assert empty.empty
    assert list(empty.columns) == ["close"]

    monkeypatch.setattr(
        data_api,
        "_load_price_frame",
        lambda security, frequency: pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "datetime": "2024-01-01 09:31:00", "freq": "1m", "close": 10.0},
                {"ts_code": "000001.SZ", "datetime": "2024-01-01 09:35:00", "freq": "5m", "close": 10.5},
                {"ts_code": "000001.SZ", "datetime": "2024-01-01 09:40:00", "freq": "5m", "close": 10.8},
            ]
        ),
    )

    result = data_api.attribute_history("000001.SZ", 2, unit="5M", fields=["close"])
    assert result.to_dict("records") == [{"close": 10.5}, {"close": 10.8}]


def test_get_money_flow_validation_and_code_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="Unsupported money flow"):
        data_api.get_money_flow("board")

    def fake_query(table: str) -> pd.DataFrame:
        mapping = {
            "concept_money_flow": pd.DataFrame(
                [
                    {"trade_date": "2024-01-02", "concept_code": "C01", "net_amount": 1},
                    {"trade_date": "2024-01-03", "concept_code": "C02", "net_amount": 2},
                ]
            ),
            "industry_money_flow": pd.DataFrame(
                [
                    {"trade_date": "2024-01-02", "industry_code": "I01", "net_amount": 3},
                    {"trade_date": "2024-01-03", "industry_code": "I01", "net_amount": 4},
                ]
            ),
        }
        return mapping[table]

    monkeypatch.setattr(data_api, "_query_meta_table", fake_query)

    concept = data_api.get_money_flow("concept", ["C01"], trade_date=date(2024, 1, 2))
    industry = data_api.get_money_flow("industry", "I01", start_date=date(2024, 1, 2), end_date=date(2024, 1, 2))

    assert concept.to_dict("records") == [{"trade_date": pd.Timestamp("2024-01-02"), "concept_code": "C01", "net_amount": 1}]
    assert industry.to_dict("records") == [{"trade_date": pd.Timestamp("2024-01-02"), "industry_code": "I01", "net_amount": 3}]


def test_get_limit_pool_and_load_price_frame_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        data_api,
        "_query_market_table",
        lambda table: pd.DataFrame(
            [
                {"trade_date": "2024-01-02", "ts_code": "000001.SZ", "limit": "U", "close": 10},
                {"trade_date": "2024-01-03", "ts_code": "000001.SZ", "limit": "D", "close": 9},
            ]
        )
        if table == "limit_list"
        else (
            pd.DataFrame(columns=["ts_code", "trade_date", "close"])
            if table == "index_daily"
            else pd.DataFrame([{"ts_code": "000300.SH", "trade_date": "2024-01-02", "close": 3000}])
        ),
    )

    limit_pool = data_api.get_limit_pool(start_date=date(2024, 1, 1), end_date=date(2024, 1, 2), kind="U")
    assert limit_pool.to_dict("records") == [
        {"trade_date": pd.Timestamp("2024-01-02"), "ts_code": "000001.SZ", "limit": "U", "close": 10}
    ]

    monkeypatch.setattr(data_api, "_price_table", lambda security, frequency: "index_daily")
    loaded = data_api._load_price_frame("000300.SH", "1d")
    assert loaded.to_dict("records") == [{"ts_code": "000300.SH", "trade_date": "2024-01-02", "close": 3000}]


def test_active_member_codes_and_filter_by_date_range_helpers() -> None:
    frame = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "in_date": "2024-01-01", "out_date": None, "is_active": 1},
            {"ts_code": "000002.SZ", "in_date": "2024-01-01", "out_date": "2024-01-02", "is_active": 1},
            {"ts_code": "000003.SZ", "in_date": "2024-01-01", "out_date": None, "is_active": 0},
        ]
    )

    assert data_api._active_member_codes(frame, date(2024, 1, 2)) == ["000001.SZ"]
    assert data_api._active_member_codes(pd.DataFrame(), date(2024, 1, 2)) == []

    filtered = data_api._filter_by_date_range(
        pd.DataFrame([{"trade_date": "2024-01-01"}, {"trade_date": "2024-01-02"}]),
        "trade_date",
        date(2024, 1, 2),
        date(2024, 1, 2),
    )
    assert filtered["trade_date"].dt.date.tolist() == [date(2024, 1, 2)]
    unchanged = data_api._filter_by_date_range(pd.DataFrame([{"value": 1}]), "trade_date", None, None)
    assert unchanged.to_dict("records") == [{"value": 1}]
