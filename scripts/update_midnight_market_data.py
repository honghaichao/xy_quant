# ruff: noqa: E402
"""Scheduler entrypoint for midnight market-data updates."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.update_hk_hold import run_job as run_hk_hold_job
from scripts.update_margin import run_job as run_margin_job
from scripts.update_minute_bar import run_job as run_minute_bar_job


def run_job(**kwargs: object) -> dict[str, dict[str, int]]:
    """Run minute-bar plus related midnight datasets in one scheduler task."""
    payload = dict(kwargs)
    trade_date = payload.get('trade_date')
    start_date = payload.get('start_date')
    end_date = payload.get('end_date')
    ts_code = payload.get('ts_code')
    freq = payload.get('freq', '1min')

    minute_kwargs: dict[str, Any] = {'freq': freq}
    if ts_code is not None:
        minute_kwargs['ts_code'] = ts_code
    if start_date is not None:
        minute_kwargs['start_date'] = start_date
    if end_date is not None:
        minute_kwargs['end_date'] = end_date

    related_kwargs: dict[str, Any] = {}
    if trade_date is not None:
        related_kwargs['trade_date'] = trade_date

    return {
        'minute_bar': run_minute_bar_job(**minute_kwargs),
        'margin': run_margin_job(**related_kwargs),
        'hk_hold': run_hk_hold_job(**related_kwargs),
    }
