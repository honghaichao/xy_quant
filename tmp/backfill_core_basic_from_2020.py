from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path('/Volumes/quant-ssd/projects/xy_quant')
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.init_db import main as init_db_main
from data.source.tushare_source import TushareSource
from data.storage.duckdb_store import DuckDBMarketStore
from data.storage.pg_store import PostgresMetaStore

ROOT = Path('/Volumes/quant-ssd/projects/xy_quant')
OUT_PATH = ROOT / 'tmp' / 'backfill_core_basic_from_2020_summary.json'
START_DATE = date(2020, 1, 1)
END_DATE = date.today()
INDEX_CODES = ['000001.SH', '399001.SZ', '399006.SZ', '000300.SH', '000905.SH', '000852.SH']


def main() -> None:
    init_db_main([])
    source = TushareSource()
    market_store = DuckDBMarketStore()
    meta_store = PostgresMetaStore()

    summary: dict[str, object] = {
        'started_at': datetime.now().isoformat(),
        'start_date': START_DATE.isoformat(),
        'end_date': END_DATE.isoformat(),
        'index_codes': INDEX_CODES,
        'steps': {},
        'progress': {'completed_trade_dates': 0, 'total_trade_dates': 0},
        'errors': [],
    }

    try:
        stock_basic = source.fetch_stock_basic()
        summary['steps']['stock_basic'] = {
            'fetched_rows': len(stock_basic),
            'loaded_rows': meta_store.upsert('stock_basic', stock_basic),
        }
        print(f"stock_basic rows={len(stock_basic)}", flush=True)

        calendar = source.fetch_trade_calendar(START_DATE, END_DATE)
        calendar_loaded = meta_store.upsert('trade_calendar', calendar)
        open_dates = sorted(calendar.loc[calendar['is_open'] == 1, 'cal_date'].dropna().tolist())
        summary['steps']['trade_calendar'] = {
            'fetched_rows': len(calendar),
            'loaded_rows': calendar_loaded,
            'open_dates': len(open_dates),
            'min_date': str(min(open_dates)) if open_dates else None,
            'max_date': str(max(open_dates)) if open_dates else None,
        }
        summary['progress']['total_trade_dates'] = len(open_dates)
        print(f"trade_calendar rows={len(calendar)} open_dates={len(open_dates)}", flush=True)

        daily_counts = {'daily_bar': 0, 'adj_factor': 0, 'daily_basic': 0}
        daily_fetch_rows = {'daily_bar': 0, 'adj_factor': 0, 'daily_basic': 0}
        for idx, trade_date in enumerate(open_dates, start=1):
            try:
                daily_bar = source.fetch_daily_bar([], trade_date, trade_date)
                adj_factor = source.fetch_adj_factor([], trade_date, trade_date)
                daily_basic = source.fetch_daily_basic([], trade_date=trade_date)

                daily_fetch_rows['daily_bar'] += len(daily_bar)
                daily_fetch_rows['adj_factor'] += len(adj_factor)
                daily_fetch_rows['daily_basic'] += len(daily_basic)

                daily_counts['daily_bar'] += market_store.upsert('daily_bar', daily_bar)
                daily_counts['adj_factor'] += market_store.upsert('adj_factor', adj_factor)
                daily_counts['daily_basic'] += market_store.upsert('daily_basic', daily_basic)
            except Exception as exc:  # noqa: BLE001
                summary['errors'].append({'stage': 'daily_loop', 'trade_date': str(trade_date), 'error': f'{type(exc).__name__}: {exc}'})
                print(f"ERROR daily_loop trade_date={trade_date} error={type(exc).__name__}: {exc}", flush=True)

            summary['progress']['completed_trade_dates'] = idx
            if idx % 20 == 0 or idx == len(open_dates):
                print(
                    f"progress {idx}/{len(open_dates)} trade_dates loaded "
                    f"daily_bar={daily_counts['daily_bar']} adj_factor={daily_counts['adj_factor']} daily_basic={daily_counts['daily_basic']}",
                    flush=True,
                )
                OUT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding='utf-8')

        summary['steps']['daily_bar'] = {
            'fetched_rows': daily_fetch_rows['daily_bar'],
            'loaded_rows': daily_counts['daily_bar'],
        }
        summary['steps']['adj_factor'] = {
            'fetched_rows': daily_fetch_rows['adj_factor'],
            'loaded_rows': daily_counts['adj_factor'],
        }
        summary['steps']['daily_basic'] = {
            'fetched_rows': daily_fetch_rows['daily_basic'],
            'loaded_rows': daily_counts['daily_basic'],
        }

        index_counts: dict[str, int] = {}
        for code in INDEX_CODES:
            try:
                frame = source.fetch_index_daily(code, START_DATE, END_DATE)
                index_counts[code] = market_store.upsert('index_daily', frame)
                print(f"index_daily {code} rows={len(frame)}", flush=True)
            except Exception as exc:  # noqa: BLE001
                summary['errors'].append({'stage': 'index_daily', 'index_code': code, 'error': f'{type(exc).__name__}: {exc}'})
                print(f"ERROR index_daily code={code} error={type(exc).__name__}: {exc}", flush=True)
        summary['steps']['index_daily'] = {'loaded_rows_by_code': index_counts}

    finally:
        try:
            market_store.close()
        except Exception:
            pass
        try:
            meta_store.close()
        except Exception:
            pass
        summary['finished_at'] = datetime.now().isoformat()
        OUT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        print(f"summary_path={OUT_PATH}", flush=True)


if __name__ == '__main__':
    main()
