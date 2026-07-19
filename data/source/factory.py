"""数据源工厂。"""

from __future__ import annotations

from data.source.akshare_source import AKShareSource
from data.source.tushare_source import TushareSource
from interfaces.data_source import IDataSource
from utils.exception import ConfigError

DATA_SOURCE_REGISTRY: dict[str, type[IDataSource]] = {
    AKShareSource.name: AKShareSource,
    TushareSource.name: TushareSource,
}


def get_data_source(name: str) -> IDataSource:
    """Return data source instance by name."""
    data_source_class = DATA_SOURCE_REGISTRY.get(name)
    if data_source_class is None:
        raise ConfigError(f"Unsupported data source: {name}")
    return data_source_class()
