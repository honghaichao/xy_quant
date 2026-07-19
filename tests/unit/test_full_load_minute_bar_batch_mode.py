from __future__ import annotations

from datetime import date
from pathlib import Path
import sys

import pytest

pytest.importorskip('duckdb')
pytest.importorskip('pandas')

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import full_load_minute_bar as module


def test_run_code_batches_executes_in_process_without_subprocess(monkeypatch):
    calls: list[tuple[list[str], date, date, str, str | None]] = []

    def fake_run_job(run_kwargs: dict[str, object], progress_file: str | None) -> dict[str, int]:
        calls.append((
            list(run_kwargs['ts_codes']),
            run_kwargs['start_date'],
            run_kwargs['end_date'],
            run_kwargs['freq'],
            progress_file,
        ))
        return {'minute_bar': 123}

    monkeypatch.setattr(module, '_run_job', fake_run_job)

    results = module.run_code_batches(
        ['000001.SZ', '000002.SZ', '000003.SZ'],
        date(2020, 1, 1),
        date(2020, 1, 31),
        '1min',
        workers=3,
        chunk_size=1,
        progress_file='progress.jsonl',
    )

    assert len(results) == 3
    assert all(result['returncode'] == 0 for result in results)
    assert sorted(result['ts_codes'] for result in results) == [
        ['000001.SZ'],
        ['000002.SZ'],
        ['000003.SZ'],
    ]
    assert all(result['counts'] == {'minute_bar': 123} for result in results)
    assert sorted(calls) == [
        (['000001.SZ'], date(2020, 1, 1), date(2020, 1, 31), '1min', 'progress.jsonl'),
        (['000002.SZ'], date(2020, 1, 1), date(2020, 1, 31), '1min', 'progress.jsonl'),
        (['000003.SZ'], date(2020, 1, 1), date(2020, 1, 31), '1min', 'progress.jsonl'),
    ]
