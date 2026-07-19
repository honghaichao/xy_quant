from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import scripts.backfill_history as backfill_history


def test_backfill_history_runs_pending_trade_dates(tmp_path, monkeypatch) -> None:
    progress_path = tmp_path / 'backfill_history_progress.jsonl'
    monkeypatch.setattr(backfill_history, '_load_trade_dates', lambda start_date, end_date: [date(2024, 1, 2), date(2024, 1, 3)])
    calls: list[date] = []

    def fake_run_trade_date(trade_date: date, args):
        calls.append(trade_date)
        return {'daily': {'daily_bar': 1}}

    monkeypatch.setattr(backfill_history, '_run_trade_date', fake_run_trade_date)

    result = backfill_history.run_job(
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 3),
        ts_codes=[],
        index_codes=[],
        concept_codes=[],
        industry_codes=[],
        progress_file=progress_path,
        resume=False,
        stop_on_error=False,
    )

    assert calls == [date(2024, 1, 2), date(2024, 1, 3)]
    assert result['trade_dates'] == 2
    assert result['completed_dates'] == 2
    assert result['failed_dates'] == 0

    events = [json.loads(line)['event'] for line in progress_path.read_text(encoding='utf-8').splitlines()]
    assert events == ['started', 'running', 'completed', 'running', 'completed', 'summary']


def test_backfill_history_resume_skips_completed_dates(tmp_path, monkeypatch) -> None:
    progress_path = tmp_path / 'backfill_history_progress.jsonl'
    progress_path.write_text(
        '\n'.join(
            [
                json.dumps({'event': 'completed', 'trade_date': '2024-01-02'}),
                json.dumps({'event': 'failed', 'trade_date': '2024-01-01', 'error': 'boom'}),
            ]
        )
        + '\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(backfill_history, '_load_trade_dates', lambda start_date, end_date: [date(2024, 1, 2), date(2024, 1, 3)])
    calls: list[date] = []

    def fake_run_trade_date(trade_date: date, args):
        calls.append(trade_date)
        return {'daily': {'daily_bar': 1}}

    monkeypatch.setattr(backfill_history, '_run_trade_date', fake_run_trade_date)

    result = backfill_history.run_job(
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 3),
        ts_codes=[],
        index_codes=[],
        concept_codes=[],
        industry_codes=[],
        progress_file=progress_path,
        resume=True,
        stop_on_error=False,
    )

    assert calls == [date(2024, 1, 3)]
    assert result['pending_dates'] == 1
    assert result['completed_dates'] == 1


def test_backfill_history_stop_on_error_raises(tmp_path, monkeypatch) -> None:
    progress_path = tmp_path / 'backfill_history_progress.jsonl'
    monkeypatch.setattr(backfill_history, '_load_trade_dates', lambda start_date, end_date: [date(2024, 1, 2)])

    def fake_run_trade_date(trade_date: date, args):
        raise RuntimeError('broken')

    monkeypatch.setattr(backfill_history, '_run_trade_date', fake_run_trade_date)

    try:
        backfill_history.run_job(
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 2),
            ts_codes=[],
            index_codes=[],
            concept_codes=[],
            industry_codes=[],
            progress_file=progress_path,
            resume=False,
            stop_on_error=True,
        )
    except RuntimeError as exc:
        assert str(exc) == 'broken'
    else:
        raise AssertionError('Expected RuntimeError')

    lines = [json.loads(line) for line in progress_path.read_text(encoding='utf-8').splitlines()]
    assert lines[-1]['event'] == 'failed'
