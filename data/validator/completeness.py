"""完整性校验工具。"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date

import pandas as pd

from utils.calendar import ensure_date
from utils.exception import ValidationError
from utils.logger import get_logger

logger = get_logger("completeness_validator")


class CompletenessValidator:
    """Validate required columns and expected trading-date coverage."""

    def validate_required_columns(
        self,
        table: str,
        frame: pd.DataFrame,
        required_columns: Sequence[str],
    ) -> None:
        """Ensure a frame contains the required schema columns."""
        missing_columns = [column for column in required_columns if column not in frame.columns]
        if missing_columns:
            message = (
                f"Table {table} is missing required columns: {', '.join(sorted(missing_columns))}"
            )
            logger.warning(message)
            raise ValidationError(message)

    def find_missing_trade_dates(
        self,
        frame: pd.DataFrame,
        expected_dates: Iterable[date],
        ts_code: str | None = None,
        date_column: str = "trade_date",
        ts_code_column: str = "ts_code",
    ) -> list[date]:
        """Return expected trade dates that are absent from the frame."""
        required_columns = [date_column]
        if ts_code is not None:
            required_columns.append(ts_code_column)
        self.validate_required_columns("trade_date_coverage", frame, required_columns)

        scoped_frame = frame
        if ts_code is not None:
            scoped_frame = frame.loc[frame[ts_code_column] == ts_code]

        actual_dates = {
            ensure_date(value)
            for value in scoped_frame[date_column].dropna().tolist()
        }
        normalized_expected_dates = sorted({ensure_date(value) for value in expected_dates})
        return [trade_date for trade_date in normalized_expected_dates if trade_date not in actual_dates]
