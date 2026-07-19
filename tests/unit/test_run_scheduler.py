"""Unit tests for the P0.10 scheduler entry script."""

from __future__ import annotations

import importlib
import sys
from argparse import Namespace

import pytest


class DummyLogger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, message: str) -> None:
        self.messages.append(message)


def test_run_scheduler_parse_args_uses_default_settings_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, 'argv', ['run_scheduler.py'])

    module = importlib.import_module('scripts.run_scheduler')

    args = module.parse_args()

    assert args == Namespace(settings_path='config/settings.yaml')


def test_run_scheduler_main_starts_and_shuts_down_on_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module('scripts.run_scheduler')
    logger = DummyLogger()
    events: list[tuple[str, object]] = []

    class FakeScheduler:
        pass

    scheduler = FakeScheduler()

    class FakeSchedulerService:
        def __init__(self, settings_path: str) -> None:
            events.append(('init', settings_path))

        def start(self) -> FakeScheduler:
            events.append(('start', scheduler))
            return scheduler

        @staticmethod
        def shutdown(active_scheduler: FakeScheduler) -> None:
            events.append(('shutdown', active_scheduler))

    def fake_wait_for_shutdown(active_scheduler: FakeScheduler) -> None:
        events.append(('wait', active_scheduler))
        raise KeyboardInterrupt

    monkeypatch.setattr(module, 'parse_args', lambda: Namespace(settings_path='config/custom.yaml'))
    monkeypatch.setattr(module, 'SchedulerService', FakeSchedulerService)
    monkeypatch.setattr(module, 'wait_for_shutdown', fake_wait_for_shutdown)
    monkeypatch.setattr(module, 'logger', logger)

    result = module.main()

    assert result is scheduler
    assert events == [
        ('init', 'config/custom.yaml'),
        ('start', scheduler),
        ('wait', scheduler),
        ('shutdown', scheduler),
    ]
    assert logger.messages == [
        'Starting scheduler service.',
        'Scheduler service stopped by user interrupt.',
        'Scheduler service shutdown complete.',
    ]
