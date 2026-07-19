"""CLI smoke tests for P0 script entrypoints."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_NAMES = [
    'full_load.py',
    'full_load_all.py',
    'full_load_basic.py',
    'full_load_calendar.py',
    'full_load_daily_bar.py',
    'full_load_minute_bar.py',
    'full_load_adj_factor.py',
    'full_load_daily_basic.py',
    'full_load_index_daily.py',
    'full_load_limit_list.py',
    'full_load_money_flow.py',
    'full_load_top_list.py',
    'full_load_margin.py',
    'full_load_hk_hold.py',
    'full_load_suspend.py',
    'full_load_member.py',
    'full_load_holdertrade.py',
    'full_load_finance.py',
    'init_db.py',
    'update_all.py',
    'update_basic.py',
    'update_calendar.py',
    'update_daily.py',
    'update_daily_bar.py',
    'update_minute_bar.py',
    'update_adj_factor.py',
    'update_daily_basic.py',
    'update_index_daily.py',
    'update_limit_list.py',
    'update_money_flow.py',
    'update_top_list.py',
    'update_margin.py',
    'update_hk_hold.py',
    'update_suspend.py',
    'update_member.py',
    'update_holdertrade.py',
    'update_finance.py',
    'run_scheduler.py',
]


@pytest.mark.parametrize('script_name', SCRIPT_NAMES)
def test_p0_script_help_entrypoints_exit_cleanly(script_name: str) -> None:
    """Each P0 script entrypoint should support --help when invoked as a file path."""
    script_path = Path(__file__).resolve().parents[2] / 'scripts' / script_name
    result = subprocess.run(
        [sys.executable, str(script_path), '--help'],
        capture_output=True,
        check=False,
        text=True,
        cwd=script_path.parent.parent,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert 'usage:' in result.stdout.lower()
