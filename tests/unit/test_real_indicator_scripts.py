"""Unit tests for real-indicator ingestion workflow."""

from __future__ import annotations

import importlib
from argparse import Namespace
from datetime import date

import pytest


class DummyLogger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, message: str) -> None:
        self.messages.append(message)


def test_real_indicator_main_runs_expected_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module('scripts.full_load_real_indicator')
    logger = DummyLogger()
    executed: list[tuple[str, dict[str, object]]] = []

    def fake_run_subjob(job_name: str, **kwargs: object) -> dict[str, int]:
        executed.append((job_name, dict(kwargs)))
        return {job_name: 1}

    monkeypatch.setattr(module, 'parse_args', lambda: Namespace(
        ts_codes=['000001.SZ', '600000.SH'],
        index_codes=['000300.SH'],
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
    ))
    monkeypatch.setattr(module, 'logger', logger)
    monkeypatch.setattr(module, 'run_subjob', fake_run_subjob)

    result = module.main()

    assert result == {
        'daily_bar': {'daily_bar': 1},
        'daily_basic': {'daily_basic': 1},
        'adj_factor': {'adj_factor': 1},
        'index_daily': {'index_daily': 1},
    }
    assert executed == [
        ('daily_bar', {'ts_codes': ['000001.SZ', '600000.SH'], 'start_date': date(2024, 1, 1), 'end_date': date(2024, 1, 31)}),
        ('daily_basic', {'ts_codes': ['000001.SZ', '600000.SH'], 'start_date': date(2024, 1, 1), 'end_date': date(2024, 1, 31)}),
        ('adj_factor', {'ts_codes': ['000001.SZ', '600000.SH'], 'start_date': date(2024, 1, 1), 'end_date': date(2024, 1, 31)}),
        ('index_daily', {'index_codes': ['000300.SH'], 'start_date': date(2024, 1, 1), 'end_date': date(2024, 1, 31)}),
    ]
    assert logger.messages == [
        'Starting real-indicator ingestion.',
        'Real-indicator ingestion complete.',
    ]
