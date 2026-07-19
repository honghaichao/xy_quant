# ruff: noqa: E402
"""Report P0 data-layer coverage progress across market and meta stores."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import json
from datetime import date
from typing import Any

import duckdb
import pandas as pd
import psycopg

from config.settings import settings
from data.source.factory import get_data_source

MARKET_TABLES = (
    'daily_bar',
    'daily_basic',
    'adj_factor',
    'index_daily',
    'limit_list',
    'minute_bar',
)
META_TABLES = (
    'stock_suspend',
    'top_list',
    'margin_detail',
    'hk_hold',
    'stock_money_flow',
    'concept_money_flow',
    'industry_money_flow',
)
DEFAULT_START_DATE = date(2020, 1, 1)


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Report P0 coverage progress.')
    parser.add_argument('--start-date', type=parse_date, default=DEFAULT_START_DATE)
    parser.add_argument('--end-date', type=parse_date, default=date.today())
    parser.add_argument('--json', action='store_true', help='Emit machine-readable JSON.')
    return parser.parse_args(argv)


def _load_trade_dates(start_date: date, end_date: date) -> list[date]:
    source = get_data_source(settings.primary_data_source)
    frame = source.fetch_trade_calendar(start_date=start_date, end_date=end_date)
    if frame.empty or 'cal_date' not in frame.columns:
        return []
    if 'is_open' in frame.columns:
        frame = frame.loc[frame['is_open'].astype(str) == '1']
    trade_dates: list[date] = []
    for raw in frame['cal_date'].tolist():
        text = str(raw)
        if len(text) == 8 and text.isdigit():
            trade_dates.append(date.fromisoformat(f'{text[:4]}-{text[4:6]}-{text[6:8]}'))
        else:
            trade_dates.append(date.fromisoformat(text))
    return sorted(set(trade_dates))


def _duckdb_expr(table: str) -> str:
    return 'DATE(datetime)' if table == 'minute_bar' else 'DATE(trade_date)'


def _count_market_trade_dates(conn: duckdb.DuckDBPyConnection, table: str, start_date: date, end_date: date) -> int:
    expr = _duckdb_expr(table)
    row = conn.execute(
        f'''
        SELECT COUNT(*)
        FROM (
            SELECT DISTINCT {expr} AS d
            FROM {table}
            WHERE {expr} BETWEEN ? AND ?
        ) q
        ''',
        [start_date.isoformat(), end_date.isoformat()],
    ).fetchone()
    return int(row[0] if row else 0)


def _count_meta_trade_dates(conn: psycopg.Connection[Any], table: str, start_date: date, end_date: date) -> int:
    with conn.cursor() as cur:
        cur.execute(
            f'''
            SELECT COUNT(*)
            FROM (
                SELECT DISTINCT trade_date::date AS d
                FROM {table}
                WHERE trade_date::date BETWEEN %s AND %s
            ) q
            ''',
            (start_date, end_date),
        )
        row = cur.fetchone()
    return int(row[0] if row else 0)


def build_report(start_date: date, end_date: date) -> dict[str, Any]:
    trade_dates = _load_trade_dates(start_date, end_date)
    total_trade_days = len(trade_dates)

    market_rows: list[dict[str, Any]] = []
    market_conn = duckdb.connect(settings.duckdb_path, read_only=True)
    try:
        for table in MARKET_TABLES:
            covered = _count_market_trade_dates(market_conn, table, start_date, end_date)
            market_rows.append(
                {
                    'table': table,
                    'store': 'duckdb',
                    'covered_trade_days': covered,
                    'missing_trade_days': max(total_trade_days - covered, 0),
                    'coverage_pct': round((covered / total_trade_days * 100) if total_trade_days else 0.0, 2),
                }
            )
    finally:
        market_conn.close()

    meta_rows: list[dict[str, Any]] = []
    with psycopg.connect(
        host=settings.pg_host,
        port=settings.pg_port,
        user=settings.pg_user,
        password=settings.pg_password,
        dbname=settings.pg_database,
    ) as pg_conn:
        for table in META_TABLES:
            covered = _count_meta_trade_dates(pg_conn, table, start_date, end_date)
            meta_rows.append(
                {
                    'table': table,
                    'store': 'postgres',
                    'covered_trade_days': covered,
                    'missing_trade_days': max(total_trade_days - covered, 0),
                    'coverage_pct': round((covered / total_trade_days * 100) if total_trade_days else 0.0, 2),
                }
            )

    return {
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'total_trade_days': total_trade_days,
        'market': market_rows,
        'meta': meta_rows,
    }


def _format_table(rows: list[dict[str, Any]]) -> str:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return '(empty)'
    return frame.to_string(index=False)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = parse_args(argv)
    report = build_report(args.start_date, args.end_date)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"P0 progress range: {report['start_date']} -> {report['end_date']}")
        print(f"Total trade days: {report['total_trade_days']}")
        print('\n[Market]')
        print(_format_table(report['market']))
        print('\n[Meta]')
        print(_format_table(report['meta']))
    return report


if __name__ == '__main__':
    main()
