from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import data.source.tushare_source as module
from utils.exception import ConfigError


class _EmptyTokenFileErrorModule:
    def __init__(self) -> None:
        self.token_calls: list[str] = []
        self.pro_api_calls: list[object] = []

    def set_token(self, token: str) -> None:
        self.token_calls.append(token)

    def pro_api(self, token=None):
        self.pro_api_calls.append(token)
        if token is not None:
            raise TypeError('legacy client does not accept token argument')
        raise module.pd.errors.EmptyDataError('No columns to parse from file')

    def pro_bar(self, **kwargs):
        return pd.DataFrame()


class _SuccessNoArgTsModule:
    def __init__(self) -> None:
        self.token_calls: list[str] = []
        self.pro_api_calls: list[object] = []
        self._client = SimpleNamespace(stock_basic=lambda **kwargs: pd.DataFrame())

    def set_token(self, token: str) -> None:
        self.token_calls.append(token)

    def pro_api(self, token=None):
        self.pro_api_calls.append(token)
        if token is not None:
            raise TypeError('legacy client does not accept token argument')
        return self._client

    def pro_bar(self, **kwargs):
        return pd.DataFrame()


def test_create_default_client_raises_config_error_when_token_file_is_empty_after_typeerror_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ts = _EmptyTokenFileErrorModule()
    monkeypatch.setattr(module.settings, 'tushare_token', 'test-token')
    monkeypatch.setattr(module, 'ts', fake_ts)

    with pytest.raises(ConfigError, match='token cache file is empty or corrupted'):
        module._create_default_client()

    assert fake_ts.token_calls == ['test-token']
    assert fake_ts.pro_api_calls == ['test-token', None]


def test_create_default_client_uses_legacy_noarg_fallback_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ts = _SuccessNoArgTsModule()
    monkeypatch.setattr(module.settings, 'tushare_token', 'test-token')
    monkeypatch.setattr(module, 'ts', fake_ts)

    client = module._create_default_client()

    assert fake_ts.token_calls == ['test-token']
    assert fake_ts.pro_api_calls == ['test-token', None]
    assert hasattr(client, 'stock_basic')


def test_create_default_client_requires_configured_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module.settings, 'tushare_token', '')

    with pytest.raises(ConfigError, match='Tushare token is required'):
        module._create_default_client()
