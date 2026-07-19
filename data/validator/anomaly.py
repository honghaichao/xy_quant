"""异常检测工具。"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from utils.exception import ValidationError
from utils.logger import get_logger

logger = get_logger("anomaly_detector")


class AnomalyDetector:
    """Detect suspicious rows in standardized market data."""

    def detect_daily_bar_anomalies(
        self,
        frame: pd.DataFrame,
        pct_chg_limit: float = 20.0,
        price_columns: Sequence[str] = ("open", "high", "low", "close"),
    ) -> pd.DataFrame:
        """Return rows whose prices or percentage changes look invalid."""
        required_columns = ["ts_code", "trade_date", *price_columns, "pct_chg"]
        missing_columns = [column for column in required_columns if column not in frame.columns]
        if missing_columns:
            raise ValidationError(
                "Daily-bar anomaly detection requires columns: "
                f"{', '.join(sorted(missing_columns))}"
            )
        if frame.empty:
            return pd.DataFrame(columns=[*frame.columns, "anomaly_type"])

        anomalies: list[pd.DataFrame] = []

        price_range_mask = (frame["high"] < frame["low"]) | (frame["high"] < frame["open"]) | (frame["high"] < frame["close"]) | (frame["low"] > frame["open"]) | (frame["low"] > frame["close"])
        non_positive_price_mask = (frame.loc[:, list(price_columns)] <= 0).any(axis=1)
        pct_chg_outlier_mask = frame["pct_chg"].abs() > pct_chg_limit

        anomalies.extend(
            self._collect(frame=frame, mask=price_range_mask, anomaly_type="price_range")
        )
        anomalies.extend(
            self._collect(
                frame=frame,
                mask=non_positive_price_mask,
                anomaly_type="non_positive_price",
            )
        )
        anomalies.extend(
            self._collect(
                frame=frame,
                mask=pct_chg_outlier_mask,
                anomaly_type="pct_chg_outlier",
            )
        )

        if not anomalies:
            return pd.DataFrame(columns=[*frame.columns, "anomaly_type"])

        result = pd.concat(anomalies, ignore_index=True)
        logger.info(f"Detected {len(result.index)} daily-bar anomalies")
        return result

    @staticmethod
    def _collect(frame: pd.DataFrame, mask: pd.Series, anomaly_type: str) -> list[pd.DataFrame]:
        if not mask.any():
            return []
        result = frame.loc[mask].copy()
        result["anomaly_type"] = anomaly_type
        return [result]
