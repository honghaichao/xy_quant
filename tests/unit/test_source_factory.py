"""Unit tests for data source factory registration."""

from __future__ import annotations

import pytest

from data.source.akshare_source import AKShareSource
from data.source.factory import get_data_source
from data.source.tushare_source import TushareSource
from utils.exception import ConfigError


@pytest.fixture(autouse=True)
def stub_factory_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid real external client initialization inside the factory tests."""
    monkeypatch.setattr(TushareSource, "__init__", lambda self: None)
    monkeypatch.setattr(AKShareSource, "__init__", lambda self: None)


def test_factory_returns_supported_data_source_instances() -> None:
    """Factory resolves both built-in data source adapters."""
    assert isinstance(get_data_source("tushare"), TushareSource)
    assert isinstance(get_data_source("akshare"), AKShareSource)


def test_factory_rejects_unknown_data_source_name() -> None:
    """Factory raises ConfigError for unsupported data source names."""
    with pytest.raises(ConfigError, match="Unsupported data source"):
        get_data_source("wind")
