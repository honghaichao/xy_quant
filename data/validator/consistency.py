"""一致性校验工具。"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from utils.exception import ValidationError
from utils.logger import get_logger

logger = get_logger("consistency_validator")


class ConsistencyValidator:
    """Validate uniqueness and key alignment across related frames."""

    def validate_unique_keys(
        self,
        table: str,
        frame: pd.DataFrame,
        key_columns: Sequence[str],
    ) -> None:
        """Ensure each business key appears at most once."""
        self._validate_columns_present(frame=frame, column_names=key_columns, context=table)
        if frame.empty:
            return

        duplicate_mask = frame.duplicated(subset=list(key_columns), keep=False)
        if not duplicate_mask.any():
            return

        duplicate_rows = frame.loc[duplicate_mask, list(key_columns)].drop_duplicates()
        sample = duplicate_rows.iloc[0].to_dict()
        message = f"Table {table} contains duplicate keys: {sample}"
        logger.warning(message)
        raise ValidationError(message)

    def validate_frame_alignment(
        self,
        left_name: str,
        left_frame: pd.DataFrame,
        right_name: str,
        right_frame: pd.DataFrame,
        key_columns: Sequence[str],
    ) -> None:
        """Ensure every key in the left frame exists in the right frame."""
        self._validate_columns_present(frame=left_frame, column_names=key_columns, context=left_name)
        self._validate_columns_present(frame=right_frame, column_names=key_columns, context=right_name)
        if left_frame.empty:
            return

        left_keys = left_frame.loc[:, list(key_columns)].drop_duplicates()
        right_keys = right_frame.loc[:, list(key_columns)].drop_duplicates()
        merged = left_keys.merge(right_keys, on=list(key_columns), how="left", indicator=True)
        missing = merged.loc[merged["_merge"] == "left_only", list(key_columns)]
        if missing.empty:
            return

        sample = missing.iloc[0].to_dict()
        message = f"Frame {left_name} has keys missing in {right_name}: {sample}"
        logger.warning(message)
        raise ValidationError(message)

    @staticmethod
    def _validate_columns_present(
        frame: pd.DataFrame,
        column_names: Sequence[str],
        context: str,
    ) -> None:
        missing_columns = [column for column in column_names if column not in frame.columns]
        if missing_columns:
            raise ValidationError(
                f"Frame {context} is missing required columns: {', '.join(sorted(missing_columns))}"
            )
