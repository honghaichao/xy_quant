"""因子抽象接口。所有因子必须实现此接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd


class IFactor(ABC):
    """Factor interface. Each factor computes a cross-sectional value per
    (date, code) pair from market data."""

    name: str = ""
    category: str = ""  # technical / fundamental / custom

    @abstractmethod
    def compute(self, data: pd.DataFrame) -> pd.Series:
        """Compute factor values from input data.

        Args:
            data: DataFrame with OHLCV columns (trade_date, ts_code, open, high,
                  low, close, vol) plus optional indicators.

        Returns:
            Series of factor values, indexed by (date, code).
        """
        ...

    @abstractmethod
    def validate(self, values: pd.Series) -> bool:
        """Validate computed factor values.

        Returns:
            True if values are within acceptable bounds.
        """
        ...
