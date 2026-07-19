from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path('/Volumes/quant-ssd/projects/xy_quant')
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.storage.pg_store import PostgresMetaStore
from data.updater.limit_list_updater import LimitListUpdater

START = date(2020, 1, 1)
END = date.today()
SUMMARY_PATH = ROOT / 'tmp' / 'backfill_limit_list_from_2020_summary.json'


def load_state() -> dict:
    if SUMMARY_PATH.exists():
        return json.loads(SUMMARY_PATH.read_text(encoding='utf-8'))
    return {
        'start_date': START.isoformat(),
        'end_date': END.isoformat(),
        'completed_dates': [],
        'counts': {'limit_list': 0},
        'errors': [],
    }


def save_state(state: dict) -> None:
    SUMMARY_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')


state = load_state()
completed = set(state['completed_dates'])
meta = PostgresMetaStore()
updater = LimitListUpdater()
try:
    cal = meta.query(
        "select cal_date from trade_calendar where is_open = 1 and cal_date between %(start)s and %(end)s order by cal_date",
        {'start': START, 'end': END},
    )
    trade_dates = [value.date().isoformat() if hasattr(value, 'date') else str(value) for value in cal['cal_date'].tolist()]
    state['total_trade_dates'] = len(trade_dates)
    for idx, trade_date_str in enumerate(trade_dates, start=1):
        if trade_date_str in completed:
            continue
        try:
            y, m, d = map(int, trade_date_str.split('-'))
            result = updater.run(date(y, m, d), kind='U')
            state['counts']['limit_list'] = int(state['counts'].get('limit_list', 0) + int(result.get('limit_list', 0)))
            state['completed_dates'].append(trade_date_str)
            completed.add(trade_date_str)
            state['last_completed_date'] = trade_date_str
            state['completed_count'] = len(state['completed_dates'])
            state['remaining_count'] = len(trade_dates) - len(state['completed_dates'])
            save_state(state)
            if idx % 10 == 0:
                print(f"progress {idx}/{len(trade_dates)} trade_date={trade_date_str} rows={state['counts']['limit_list']}", flush=True)
        except Exception as exc:  # noqa: BLE001
            state['errors'].append({'trade_date': trade_date_str, 'error': str(exc)})
            save_state(state)
            print(f"ERROR limit_list trade_date={trade_date_str} error={exc}", flush=True)
    save_state(state)
    print(f"summary_path={SUMMARY_PATH}", flush=True)
finally:
    updater.close()
    meta.close()
