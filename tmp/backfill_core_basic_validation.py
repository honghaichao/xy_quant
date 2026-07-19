from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import pandas as pd
import psycopg

ROOT = Path('/Volumes/quant-ssd/projects/xy_quant')
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import settings
from data.validator.anomaly import AnomalyDetector
from data.validator.completeness import CompletenessValidator
from data.validator.consistency import ConsistencyValidator
from utils.calendar import ensure_date

OUT_PATH = ROOT / 'tmp' / 'backfill_core_basic_validation.json'
INDEX_CODES = ['000001.SH', '399001.SZ', '399006.SZ', '000300.SH', '000905.SH', '000852.SH']


def fetch_duckdb_table(conn: duckdb.DuckDBPyConnection, table: str, columns: str = '*') -> pd.DataFrame:
    return conn.execute(f'SELECT {columns} FROM {table}').fetch_df()


def main() -> None:
    result: dict[str, object] = {'checks': {}, 'errors': []}
    completeness = CompletenessValidator()
    consistency = ConsistencyValidator()
    anomaly = AnomalyDetector()

    market_conn = duckdb.connect(settings.duckdb_path)
    pg_conn = psycopg.connect(
        host=settings.pg_host,
        port=settings.pg_port,
        user=settings.pg_user,
        password=settings.pg_password,
        dbname=settings.pg_database,
    )

    try:
        stock_basic = pd.read_sql('SELECT * FROM stock_basic', pg_conn)
        trade_calendar = pd.read_sql('SELECT * FROM trade_calendar ORDER BY cal_date', pg_conn)
        daily_bar = fetch_duckdb_table(market_conn, 'daily_bar')
        adj_factor = fetch_duckdb_table(market_conn, 'adj_factor')
        daily_basic = fetch_duckdb_table(market_conn, 'daily_basic')
        index_daily = fetch_duckdb_table(market_conn, 'index_daily')

        open_dates = sorted(
            ensure_date(value)
            for value in trade_calendar.loc[trade_calendar['is_open'] == 1, 'cal_date'].dropna().tolist()
        )

        result['checks']['stock_basic'] = {
            'rows': int(len(stock_basic)),
            'unique_ts_code': int(stock_basic['ts_code'].nunique()) if 'ts_code' in stock_basic.columns else None,
            'list_date_min': str(stock_basic['list_date'].min()) if 'list_date' in stock_basic.columns and len(stock_basic) else None,
            'list_date_max': str(stock_basic['list_date'].max()) if 'list_date' in stock_basic.columns and len(stock_basic) else None,
        }

        result['checks']['trade_calendar'] = {
            'rows': int(len(trade_calendar)),
            'open_dates': int(len(open_dates)),
            'min_date': str(min(open_dates)) if open_dates else None,
            'max_date': str(max(open_dates)) if open_dates else None,
        }

        for name, frame, date_col in [
            ('daily_bar', daily_bar, 'trade_date'),
            ('adj_factor', adj_factor, 'trade_date'),
            ('daily_basic', daily_basic, 'trade_date'),
        ]:
            completeness.validate_required_columns(name, frame, ['ts_code', date_col])
            consistency.validate_unique_keys(name, frame, ['ts_code', date_col])
            missing_dates = completeness.find_missing_trade_dates(frame, open_dates, date_column=date_col)
            result['checks'][name] = {
                'rows': int(len(frame)),
                'unique_ts_code': int(frame['ts_code'].nunique()),
                'min_date': str(frame[date_col].min()) if len(frame) else None,
                'max_date': str(frame[date_col].max()) if len(frame) else None,
                'missing_trade_dates_count': int(len(missing_dates)),
                'missing_trade_dates_sample': [str(item) for item in missing_dates[:10]],
            }

        consistency.validate_frame_alignment('daily_bar', daily_bar, 'adj_factor', adj_factor, ['ts_code', 'trade_date'])
        result['checks']['daily_bar_vs_adj_factor'] = {'aligned': True}

        daily_anomalies = anomaly.detect_daily_bar_anomalies(daily_bar)
        result['checks']['daily_bar_anomalies'] = {
            'count': int(len(daily_anomalies)),
            'sample': daily_anomalies.head(10).to_dict(orient='records'),
        }

        index_rows_by_code: dict[str, int] = {}
        index_missing_by_code: dict[str, int] = {}
        index_range_by_code: dict[str, dict[str, str | int | None]] = {}
        completeness.validate_required_columns('index_daily', index_daily, ['ts_code', 'trade_date'])
        consistency.validate_unique_keys('index_daily', index_daily, ['ts_code', 'trade_date'])
        for code in INDEX_CODES:
            scoped = index_daily.loc[index_daily['ts_code'] == code].copy()
            missing_dates = completeness.find_missing_trade_dates(scoped, open_dates, date_column='trade_date')
            index_rows_by_code[code] = int(len(scoped))
            index_missing_by_code[code] = int(len(missing_dates))
            index_range_by_code[code] = {
                'min_date': str(scoped['trade_date'].min()) if len(scoped) else None,
                'max_date': str(scoped['trade_date'].max()) if len(scoped) else None,
                'missing_trade_dates_sample': [str(item) for item in missing_dates[:5]],
            }
        result['checks']['index_daily'] = {
            'rows': int(len(index_daily)),
            'rows_by_code': index_rows_by_code,
            'missing_trade_dates_by_code': index_missing_by_code,
            'ranges_by_code': index_range_by_code,
        }

    except Exception as exc:  # noqa: BLE001
        result['errors'].append(f'{type(exc).__name__}: {exc}')
    finally:
        market_conn.close()
        pg_conn.close()

    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    print(OUT_PATH)


if __name__ == '__main__':
    main()
