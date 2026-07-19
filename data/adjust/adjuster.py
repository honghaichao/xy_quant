"""复权工具。"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from utils.exception import ValidationError
from utils.logger import get_logger

logger = get_logger("price_adjuster")


class PriceAdjuster:
    """Apply pre/post adjustment factors to standardized daily bars."""

    def apply(
        self,
        daily_bar: pd.DataFrame,
        adj_factor: pd.DataFrame,
        fq: str | None = "pre",
        price_columns: Sequence[str] = ("open", "high", "low", "close", "pre_close"),
    ) -> pd.DataFrame:
        """Return adjusted daily bars using the provided factor table."""
        result = daily_bar.copy()
        if fq is None:
            return result
        if fq not in {"pre", "post"}:
            raise ValidationError(f"Unsupported fq value: {fq}")

        self._validate_daily_bar_columns(daily_bar=daily_bar)
        self._validate_adj_factor_columns(adj_factor=adj_factor)
        if result.empty:
            return result

        merged = result.merge(
            adj_factor.loc[:, ["ts_code", "trade_date", "adj_factor"]],
            on=["ts_code", "trade_date"],
            how="left",
        )
        if merged["adj_factor"].isna().any():
            missing_rows = merged.loc[merged["adj_factor"].isna(), ["ts_code", "trade_date"]]
            sample = missing_rows.iloc[0].to_dict()
            raise ValidationError(f"Missing adj_factor for daily_bar row: {sample}")

        base_factor = merged.groupby("ts_code")["adj_factor"].transform("last")
        if fq == "post":
            base_factor = merged.groupby("ts_code")["adj_factor"].transform("first")

        ratio = merged["adj_factor"] / base_factor
        for column in price_columns:
            if column in merged.columns:
                merged[column] = merged[column] * ratio

        merged.drop(columns=["adj_factor"], inplace=True)
        logger.info(f"Applied {fq} adjustment to {len(merged.index)} daily_bar rows")
        return merged

    @staticmethod
    def _validate_daily_bar_columns(daily_bar: pd.DataFrame) -> None:
        required_columns = ["ts_code", "trade_date"]
        missing_columns = [column for column in required_columns if column not in daily_bar.columns]
        if missing_columns:
            raise ValidationError(
                "Daily-bar adjustment requires columns: "
                f"{', '.join(sorted(missing_columns))}"
            )

    @staticmethod
    def _validate_adj_factor_columns(adj_factor: pd.DataFrame) -> None:
        required_columns = ["ts_code", "trade_date", "adj_factor"]
        missing_columns = [column for column in required_columns if column not in adj_factor.columns]
        if missing_columns:
            raise ValidationError(
                "Adjustment-factor data requires columns: "
                f"{', '.join(sorted(missing_columns))}"
            )
