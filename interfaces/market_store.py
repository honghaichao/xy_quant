"""行情存储接口。"""
from abc import ABC, abstractmethod
from collections.abc import Mapping
from datetime import date
from typing import Any

import pandas as pd


class IMarketStore(ABC):
    """行情数据存储接口。"""

    @abstractmethod
    def init_schema(self) -> None:
        """Initialize schema."""

    @abstractmethod
    def upsert(self, table: str, df: pd.DataFrame) -> int:
        """Upsert rows into market store."""

    @abstractmethod
    def query(self, sql: str, params: Mapping[str, Any] | None = None) -> pd.DataFrame:
        """Query market store."""

    @abstractmethod
    def execute(self, sql: str, params: Mapping[str, Any] | None = None) -> int:
        """Execute statement."""

    @abstractmethod
    def get_last_date(self, table: str, ts_code: str | None = None) -> date | None:
        """Get latest date for table or symbol."""

    @abstractmethod
    def count(self, table: str, where: str | None = None) -> int:
        """Count rows in a table."""

    @abstractmethod
    def close(self) -> None:
        """Close resources."""
