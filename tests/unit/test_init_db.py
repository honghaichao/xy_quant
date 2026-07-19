"""Unit tests for database initialization script."""

from __future__ import annotations

import sys

import pytest

from scripts import init_db


class DummyStore:
    """Simple store spy used to validate init_db orchestration."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def init_schema(self) -> None:
        """Record schema initialization."""
        self.calls.append("init_schema")

    def close(self) -> None:
        """Record close calls."""
        self.calls.append("close")


class DummyLogger:
    """Collect log messages from init_db without touching real sinks."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, message: str) -> None:
        """Record info messages."""
        self.messages.append(message)


def test_main_initializes_market_and_meta_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    """Script initializes both stores and logs progress."""
    market_store = DummyStore()
    meta_store = DummyStore()
    logger = DummyLogger()

    monkeypatch.setattr(sys, "argv", ["init_db.py"])
    monkeypatch.setattr(init_db, "get_market_store", lambda name: market_store)
    monkeypatch.setattr(init_db, "get_meta_store", lambda name: meta_store)
    monkeypatch.setattr(init_db, "logger", logger)

    init_db.main()

    assert market_store.calls == ["init_schema", "close"]
    assert meta_store.calls == ["init_schema", "close"]
    assert logger.messages == [
        "Initializing database schemas.",
        "Database initialization complete.",
    ]
