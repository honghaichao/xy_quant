#!/usr/bin/env python3
"""Schedule P0 daily backfill with a trading-day guard.

This script is intended to be run by cron/system scheduler. It inspects the
current P0 data coverage, checks the trade calendar from PostgreSQL, and only
calls scripts.backfill_day.run_job() when the next trading day is due.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import duckdb

from config.settings import settings
from data.storage.factory import get_meta_store
from scripts.backfill_day import run_job as run_backfill_day
from scripts.update_calendar import run_job as run_calendar_update

MARKET_DB: Final[Path] = PROJECT_ROOT / 'data_store' / 'market.duckdb'
P0_MARKET_TABLES: Final[tuple[str, ...]] = ('daily_bar', 'daily_basic', 'adj_factor', 'index_daily', 'limit_list')


@dataclass(frozen=True)
class Coverage:
    table: str
    latest: str | None


def _duckdb_latest(table: str, column: str = 'trade_date') -> str | None:
    if not MARKET_DB.exists():
        raise FileNotFoundError(f'Market DB not found: {MARKET_DB}')
    con = duckdb.connect(str(MARKET_DB), read_only=True)
    try:
        row = con.execute(f'SELECT max({column}) FROM {table}').fetchone()
        value = row[0] if row else None
        return value.isoformat() if hasattr(value, 'isoformat') else (str(value) if value is not None else None)
    finally:
        con.close()


def _duckdb_scalar(sql: str) -> object | None:
    if not MARKET_DB.exists():
        raise FileNotFoundError(f'Market DB not found: {MARKET_DB}')
    con = duckdb.connect(str(MARKET_DB), read_only=True)
    try:
        row = con.execute(sql).fetchone()
        return row[0] if row else None
    finally:
        con.close()


def _postgres_scalar(sql: str) -> object | None:
    store = get_meta_store('postgres')
    try:
        df = store.query(sql)
        if df.empty:
            return None
        return df.iloc[0, 0]
    finally:
        store.close()


def get_latest_market_coverage() -> list[Coverage]:
    out: list[Coverage] = []
    for table in P0_MARKET_TABLES:
        col = 'datetime' if table == 'minute_bar' else 'trade_date'
        out.append(Coverage(table=table, latest=_duckdb_latest(table, col)))
    return out


def infer_latest_covered_day() -> date:
    coverages = get_latest_market_coverage()
    latest_dates: list[date] = []
    for cov in coverages:
        if not cov.latest:
            continue
        latest_dates.append(date.fromisoformat(cov.latest.split(' ')[0]))
    if not latest_dates:
        raise RuntimeError('Cannot infer covered day: no P0 market coverage found')
    return max(latest_dates)


def _next_trading_day(after_day: date) -> date | None:
    sql = f"""
    SELECT MIN(cal_date)
    FROM trade_calendar
    WHERE exchange = 'SSE'
      AND is_open = 1
      AND cal_date > DATE '{after_day.isoformat()}'
    """
    value = _postgres_scalar(sql)
    return value if isinstance(value, date) else (date.fromisoformat(str(value)) if value else None)


def _already_covered(day: date) -> bool:
    sql = f"""
    SELECT COUNT(*)
    FROM daily_bar
    WHERE trade_date = DATE '{day.isoformat()}'
    """
    value = _duckdb_scalar(sql)
    return int(value or 0) > 0


def main() -> int:
    calendar_result = run_calendar_update()
    print(f'[schedule_p0_backfill] calendar update result: {calendar_result}')
    latest_covered_day = infer_latest_covered_day()
    target_day = _next_trading_day(latest_covered_day)
    if target_day is None:
        print(f'[schedule_p0_backfill] latest covered day: {latest_covered_day.isoformat()}')
        print('[schedule_p0_backfill] no next trading day found; skip')
        return 0
    if _already_covered(target_day):
        print(f'[schedule_p0_backfill] latest covered day: {latest_covered_day.isoformat()}')
        print(f'[schedule_p0_backfill] target trading day already covered: {target_day.isoformat()}')
        return 0
    print(f'[schedule_p0_backfill] latest covered day: {latest_covered_day.isoformat()}')
    print(f'[schedule_p0_backfill] next trading day to fill: {target_day.isoformat()}')
    result = run_backfill_day(trade_date=target_day)
    print(f'[schedule_p0_backfill] backfill result: {result}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
