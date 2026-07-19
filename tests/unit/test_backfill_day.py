from __future__ import annotations

from argparse import Namespace
from datetime import date
from pathlib import Path

import pytest

import scripts.backfill_day as backfill_day
from utils.exception import PartialUpdateError


def test_backfill_day_runs_all_incremental_jobs(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_run_subjob(job_name: str, **kwargs: object) -> dict[str, int]:
        calls.append((job_name, kwargs))
        return {job_name: 1}

    monkeypatch.setattr(backfill_day, 'orchestration_run_subjob', fake_run_subjob)

    result = backfill_day.run_job(trade_date=date(2024, 1, 2))

    assert list(result) == [job.name for job in backfill_day.INCREMENTAL_JOB_SPECS]
    assert [name for name, _ in calls] == [job.name for job in backfill_day.INCREMENTAL_JOB_SPECS]
    assert all(kwargs['trade_date'] == date(2024, 1, 2) for _, kwargs in calls if 'trade_date' in kwargs)


def test_backfill_day_normalizes_missing_bounds() -> None:
    args = Namespace(
        trade_date=date(2024, 1, 2),
        ts_codes=None,
        index_codes=None,
        concept_codes=None,
        industry_codes=None,
        progress_file=None,
    )
    normalized = backfill_day._normalize_args(args)

    assert normalized.start_date == date(2024, 1, 2)
    assert normalized.end_date == date(2024, 1, 2)


def test_backfill_day_logs_partial_failure_and_continues(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    progress_file = tmp_path / 'backfill_day_progress.jsonl'

    def fake_run_subjob(job_name: str, **kwargs: object) -> dict[str, int]:
        del kwargs
        if job_name == 'daily':
            raise PartialUpdateError(
                'money flow partial',
                counts={'stock_money_flow': 10, 'concept_money_flow': 0, 'industry_money_flow': 0},
                failures={
                    'concept_money_flow': 'moneyflow_ths exceeded remote rate-limit retry budget',
                    'industry_money_flow': 'moneyflow_ind_dc exceeded remote rate-limit retry budget',
                },
            )
        return {job_name: 1}

    monkeypatch.setattr(backfill_day, 'orchestration_run_subjob', fake_run_subjob)

    result = backfill_day.run_job(trade_date=date(2024, 1, 2), progress_file=str(progress_file))

    assert result['daily'] == {'stock_money_flow': 10, 'concept_money_flow': 0, 'industry_money_flow': 0}
    assert '_failures' in result

    lines = progress_file.read_text(encoding='utf-8').strip().splitlines()
    daily_record = [line for line in lines if '"job": "daily"' in line][0]
    assert 'concept_money_flow' in daily_record
    assert 'industry_money_flow' in daily_record


def test_backfill_day_logs_fatal_failure_and_continues(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    progress_file = tmp_path / 'backfill_day_progress.jsonl'

    def fake_run_subjob(job_name: str, **kwargs: object) -> dict[str, int]:
        del kwargs
        if job_name == 'daily':
            raise RuntimeError('boom')
        return {job_name: 1}

    monkeypatch.setattr(backfill_day, 'orchestration_run_subjob', fake_run_subjob)

    result = backfill_day.run_job(trade_date=date(2024, 1, 2), progress_file=str(progress_file))

    assert result['daily'] == {}
    assert result['calendar'] == {'calendar': 1}
    assert result['basic'] == {'basic': 1}
    assert '_failures' in result

    lines = progress_file.read_text(encoding='utf-8').strip().splitlines()
    daily_record = [line for line in lines if '"job": "daily"' in line][0]
    assert '"type": "fatal"' in daily_record
    assert 'boom' in daily_record
