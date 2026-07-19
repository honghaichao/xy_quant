"""元数据存储接口(关系型,基本面/财务)。"""
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

import pandas as pd


class IMetaStore(ABC):
    """Metadata store interface."""

    @abstractmethod
    def init_schema(self) -> None:
        """Initialize schema."""

    @abstractmethod
    def upsert(self, table: str, df: pd.DataFrame) -> int:
        """Upsert rows into meta store."""

    @abstractmethod
    def query(self, sql: str, params: Mapping[str, Any] | None = None) -> pd.DataFrame:
        """Query metadata."""

    @abstractmethod
    def execute(self, sql: str, params: Mapping[str, Any] | None = None) -> int:
        """Execute statement."""

    @abstractmethod
    def close(self) -> None:
        """Close resources."""
