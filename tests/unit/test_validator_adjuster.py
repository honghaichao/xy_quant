"""Unit tests for P0.5 validators and price adjuster."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from data.adjust.adjuster import PriceAdjuster
from data.validator.anomaly import AnomalyDetector
from data.validator.completeness import CompletenessValidator
from data.validator.consistency import ConsistencyValidator
from utils.exception import ValidationError


class TestCompletenessValidator:
    """Behavioral tests for completeness validation."""

    def test_validate_required_columns_raises_for_missing_columns(self) -> None:
        """Required-column validation should reject incomplete frames."""
        validator = CompletenessValidator()
        frame = pd.DataFrame([{"trade_date": date(2024, 1, 2)}])

        with pytest.raises(ValidationError) as exc:
            validator.validate_required_columns(
                table="daily_bar",
                frame=frame,
                required_columns=("ts_code", "trade_date", "close"),
            )

        assert "ts_code" in str(exc.value)
        assert "close" in str(exc.value)

    def test_find_missing_trade_dates_filters_by_symbol(self) -> None:
        """Missing-date detection should work per symbol when a symbol filter is provided."""
        validator = CompletenessValidator()
        frame = pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": date(2024, 1, 2)},
                {"ts_code": "000001.SZ", "trade_date": date(2024, 1, 4)},
                {"ts_code": "000002.SZ", "trade_date": date(2024, 1, 3)},
            ]
        )

        missing_dates = validator.find_missing_trade_dates(
            frame=frame,
            expected_dates=[date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)],
            ts_code="000001.SZ",
        )

        assert missing_dates == [date(2024, 1, 3)]


class TestConsistencyValidator:
    """Behavioral tests for consistency validation."""

    def test_validate_unique_keys_rejects_duplicate_daily_bar_keys(self) -> None:
        """Duplicate business keys should fail consistency validation."""
        validator = ConsistencyValidator()
        frame = pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": date(2024, 1, 2), "close": 10.0},
                {"ts_code": "000001.SZ", "trade_date": date(2024, 1, 2), "close": 10.5},
            ]
        )

        with pytest.raises(ValidationError) as exc:
            validator.validate_unique_keys(
                table="daily_bar",
                frame=frame,
                key_columns=("ts_code", "trade_date"),
            )

        assert "daily_bar" in str(exc.value)
        assert "000001.SZ" in str(exc.value)

    def test_validate_frame_alignment_rejects_missing_adj_factor_keys(self) -> None:
        """Every daily bar row should have a matching adjustment factor row."""
        validator = ConsistencyValidator()
        daily_bar = pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": date(2024, 1, 2)},
                {"ts_code": "000002.SZ", "trade_date": date(2024, 1, 2)},
            ]
        )
        adj_factor = pd.DataFrame(
            [{"ts_code": "000001.SZ", "trade_date": date(2024, 1, 2), "adj_factor": 1.0}]
        )

        with pytest.raises(ValidationError) as exc:
            validator.validate_frame_alignment(
                left_name="daily_bar",
                left_frame=daily_bar,
                right_name="adj_factor",
                right_frame=adj_factor,
                key_columns=("ts_code", "trade_date"),
            )

        assert "adj_factor" in str(exc.value)
        assert "000002.SZ" in str(exc.value)


class TestAnomalyDetector:
    """Behavioral tests for anomaly detection."""

    def test_detect_daily_bar_anomalies_reports_invalid_rows(self) -> None:
        """Price-range, non-positive-price, and pct-change outliers should be detected."""
        detector = AnomalyDetector()
        frame = pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": date(2024, 1, 2),
                    "open": 10.0,
                    "high": 9.5,
                    "low": 9.0,
                    "close": 9.8,
                    "pct_chg": -2.0,
                },
                {
                    "ts_code": "000001.SZ",
                    "trade_date": date(2024, 1, 3),
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.5,
                    "close": 0.0,
                    "pct_chg": -100.0,
                },
                {
                    "ts_code": "000001.SZ",
                    "trade_date": date(2024, 1, 4),
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.8,
                    "close": 10.1,
                    "pct_chg": 25.1,
                },
            ]
        )

        anomalies = detector.detect_daily_bar_anomalies(frame=frame, pct_chg_limit=20.0)

        assert list(anomalies["anomaly_type"]) == [
            "price_range",
            "price_range",
            "non_positive_price",
            "pct_chg_outlier",
            "pct_chg_outlier",
        ]
        assert list(anomalies["trade_date"]) == [
            date(2024, 1, 2),
            date(2024, 1, 3),
            date(2024, 1, 3),
            date(2024, 1, 3),
            date(2024, 1, 4),
        ]


class TestPriceAdjuster:
    """Behavioral tests for daily-bar adjustment."""

    def test_apply_pre_adjustment_scales_prices_by_latest_factor(self) -> None:
        """Pre-adjusted prices should be normalized by the latest factor per symbol."""
        adjuster = PriceAdjuster()
        daily_bar = pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": date(2024, 1, 2),
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.0,
                    "close": 10.0,
                    "pre_close": 9.5,
                    "vol": 100.0,
                },
                {
                    "ts_code": "000001.SZ",
                    "trade_date": date(2024, 1, 3),
                    "open": 12.0,
                    "high": 13.0,
                    "low": 11.0,
                    "close": 12.0,
                    "pre_close": 10.0,
                    "vol": 110.0,
                },
                {
                    "ts_code": "000001.SZ",
                    "trade_date": date(2024, 1, 4),
                    "open": 14.0,
                    "high": 15.0,
                    "low": 13.0,
                    "close": 14.0,
                    "pre_close": 12.0,
                    "vol": 120.0,
                },
            ]
        )
        adj_factor = pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": date(2024, 1, 2), "adj_factor": 1.0},
                {"ts_code": "000001.SZ", "trade_date": date(2024, 1, 3), "adj_factor": 2.0},
                {"ts_code": "000001.SZ", "trade_date": date(2024, 1, 4), "adj_factor": 2.0},
            ]
        )

        adjusted = adjuster.apply(daily_bar=daily_bar, adj_factor=adj_factor, fq="pre")

        assert adjusted["close"].tolist() == pytest.approx([5.0, 12.0, 14.0])
        assert adjusted["open"].tolist() == pytest.approx([5.0, 12.0, 14.0])
        assert adjusted["pre_close"].tolist() == pytest.approx([4.75, 10.0, 12.0])
        assert adjusted["vol"].tolist() == [100.0, 110.0, 120.0]

    def test_apply_post_adjustment_scales_prices_by_first_factor(self) -> None:
        """Post-adjusted prices should be normalized by the earliest factor per symbol."""
        adjuster = PriceAdjuster()
        daily_bar = pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": date(2024, 1, 2), "close": 10.0},
                {"ts_code": "000001.SZ", "trade_date": date(2024, 1, 3), "close": 12.0},
                {"ts_code": "000001.SZ", "trade_date": date(2024, 1, 4), "close": 14.0},
            ]
        )
        adj_factor = pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": date(2024, 1, 2), "adj_factor": 1.0},
                {"ts_code": "000001.SZ", "trade_date": date(2024, 1, 3), "adj_factor": 2.0},
                {"ts_code": "000001.SZ", "trade_date": date(2024, 1, 4), "adj_factor": 2.0},
            ]
        )

        adjusted = adjuster.apply(daily_bar=daily_bar, adj_factor=adj_factor, fq="post")

        assert adjusted["close"].tolist() == pytest.approx([10.0, 24.0, 28.0])

    def test_apply_without_adjustment_returns_copy_of_input(self) -> None:
        """Disabling复权 should leave the original prices unchanged."""
        adjuster = PriceAdjuster()
        daily_bar = pd.DataFrame(
            [{"ts_code": "000001.SZ", "trade_date": date(2024, 1, 2), "close": 10.0}]
        )
        adj_factor = pd.DataFrame(
            [{"ts_code": "000001.SZ", "trade_date": date(2024, 1, 2), "adj_factor": 1.0}]
        )

        adjusted = adjuster.apply(daily_bar=daily_bar, adj_factor=adj_factor, fq=None)

        assert adjusted.equals(daily_bar)
        assert adjusted is not daily_bar
