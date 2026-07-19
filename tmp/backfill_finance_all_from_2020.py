from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path('/Volumes/quant-ssd/projects/xy_quant')
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.source.tushare_source import TushareSource
from data.updater.finance_updater import FinanceUpdater

START = date(2020, 1, 1)
END = date.today()
SUMMARY_PATH = ROOT / 'tmp' / 'backfill_finance_all_from_2020_summary.json'


def load_state() -> dict:
    if SUMMARY_PATH.exists():
        return json.loads(SUMMARY_PATH.read_text(encoding='utf-8'))
    return {
        'start_date': START.isoformat(),
        'end_date': END.isoformat(),
        'completed_codes': [],
        'counts': {'income': 0, 'balancesheet': 0, 'cashflow': 0, 'fina_indicator': 0, 'dividend': 0},
        'errors': [],
    }


def save_state(state: dict) -> None:
    SUMMARY_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')


state = load_state()
completed = set(state['completed_codes'])
source = TushareSource()
updater = FinanceUpdater(source=source)
try:
    stock_basic = source.fetch_stock_basic()
    codes = [code for code in stock_basic['ts_code'].tolist() if isinstance(code, str) and code]
    state['total_codes'] = len(codes)
    for idx, code in enumerate(codes, start=1):
        if code in completed:
            continue
        try:
            result = updater.run([code], start_date=START, end_date=END)
            for key, value in result.items():
                state['counts'][key] = int(state['counts'].get(key, 0) + int(value))
            state['completed_codes'].append(code)
            completed.add(code)
            state['last_completed_code'] = code
            state['completed_count'] = len(state['completed_codes'])
            state['remaining_count'] = len(codes) - len(state['completed_codes'])
            if idx % 25 == 0:
                save_state(state)
                print(f"progress {idx}/{len(codes)} code={code} counts={state['counts']}", flush=True)
        except Exception as exc:  # noqa: BLE001
            try:
                updater.meta_store.connection.rollback()
            except Exception:  # noqa: BLE001
                pass
            state['errors'].append({'ts_code': code, 'error': str(exc)})
            save_state(state)
            print(f"ERROR finance code={code} error={exc}", flush=True)
    save_state(state)
    print(f"summary_path={SUMMARY_PATH}", flush=True)
finally:
    updater.close()
