# ruff: noqa: E402
"""Read-only acceptance report for minute_bar full-load coverage."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import duckdb
import psycopg

from config.settings import settings
from scripts.update_helpers import parse_date

ROOT = Path(__file__).resolve().parents[1]
DUCKDB_PATH = ROOT / "data_store" / "market.duckdb"


@dataclass(frozen=True)
class ExpectedSymbolCoverage:
    ts_code: str
    expected_open_days: int
    suspend_days: int
    list_date: date | None
    delist_date: date | None


@dataclass(frozen=True)
class ActualSymbolCoverage:
    ts_code: str
    actual_days: int
    first_trade_date: date | None
    last_trade_date: date | None


@dataclass(frozen=True)
class MinuteCoverageReport:
    start_date: str
    end_date: str
    freq: str
    expected_symbol_count: int
    actual_symbol_count: int
    complete_symbol_count: int
    missing_symbol_count: int
    partial_symbol_count: int
    expected_open_day_total: int
    actual_open_day_total: int
    missing_symbols: list[str]
    partial_symbols: list[dict[str, object]]
    complete: bool


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify minute_bar symbol/day coverage after backfill completes.")
    parser.add_argument("--start-date", type=parse_date, required=True)
    parser.add_argument("--end-date", type=parse_date, required=True)
    parser.add_argument("--freq", default="1min")
    parser.add_argument("--sample-limit", type=int, default=20)
    return parser.parse_args(argv)


def _postgres_dsn() -> str:
    return (
        f"host={settings.pg_host} port={settings.pg_port} dbname={settings.pg_database} "
        f"user={settings.pg_user} password={settings.pg_password}"
    )


def fetch_expected_symbol_coverage(start_date: date, end_date: date) -> list[ExpectedSymbolCoverage]:
    sql = """
        WITH open_days AS (
            SELECT cal_date
            FROM trade_calendar
            WHERE is_open = 1
              AND cal_date BETWEEN %(start_date)s AND %(end_date)s
            GROUP BY cal_date
        ),
        suspend_days AS (
            SELECT ts_code, trade_date
            FROM stock_suspend
            WHERE suspend_type = 'S'
              AND trade_date BETWEEN %(start_date)s AND %(end_date)s
            GROUP BY ts_code, trade_date
        )
        SELECT
            sb.ts_code,
            COUNT(od.cal_date)::int - COUNT(sd.trade_date)::int AS expected_open_days,
            COUNT(sd.trade_date)::int AS suspend_days,
            sb.list_date,
            sb.delist_date
        FROM stock_basic AS sb
        LEFT JOIN open_days AS od
          ON od.cal_date BETWEEN GREATEST(COALESCE(sb.list_date, %(start_date)s), %(start_date)s)
                            AND LEAST(COALESCE(sb.delist_date, %(end_date)s), %(end_date)s)
        LEFT JOIN suspend_days AS sd
          ON sd.ts_code = sb.ts_code
         AND sd.trade_date = od.cal_date
        WHERE COALESCE(sb.list_date, %(start_date)s) <= %(end_date)s
          AND COALESCE(sb.delist_date, %(end_date)s) >= %(start_date)s
          AND COALESCE(sb.list_status, 'L') <> 'P'
        GROUP BY sb.ts_code, sb.list_date, sb.delist_date
        ORDER BY sb.ts_code
    """
    with psycopg.connect(_postgres_dsn()) as conn, conn.cursor() as cur:
        cur.execute(sql, {"start_date": start_date, "end_date": end_date})
        rows = cur.fetchall()
    return [
        ExpectedSymbolCoverage(
            ts_code=str(row[0]),
            expected_open_days=max(int(row[1]), 0),
            suspend_days=int(row[2]),
            list_date=row[3],
            delist_date=row[4],
        )
        for row in rows
    ]


def fetch_actual_symbol_coverage(start_date: date, end_date: date, *, freq: str) -> list[ActualSymbolCoverage]:
    sql = """
        SELECT
            ts_code,
            COUNT(DISTINCT CAST(datetime AS DATE))::BIGINT AS actual_days,
            MIN(CAST(datetime AS DATE)) AS first_trade_date,
            MAX(CAST(datetime AS DATE)) AS last_trade_date
        FROM minute_bar
        WHERE freq = ?
          AND CAST(datetime AS DATE) BETWEEN ? AND ?
        GROUP BY ts_code
        ORDER BY ts_code
    """
    with duckdb.connect(str(DUCKDB_PATH), read_only=True) as conn:
        rows = conn.execute(sql, [freq, start_date, end_date]).fetchall()
    return [
        ActualSymbolCoverage(
            ts_code=str(row[0]),
            actual_days=int(row[1]),
            first_trade_date=row[2],
            last_trade_date=row[3],
        )
        for row in rows
    ]


def build_minute_coverage_report(
    expected_rows: Iterable[ExpectedSymbolCoverage],
    actual_rows: Iterable[ActualSymbolCoverage],
    *,
    start_date: date,
    end_date: date,
    freq: str,
    sample_limit: int,
) -> MinuteCoverageReport:
    expected = {row.ts_code: row for row in expected_rows if row.expected_open_days > 0}
    actual = {row.ts_code: row for row in actual_rows}

    missing_symbols: list[str] = []
    partial_symbols: list[dict[str, object]] = []
    complete_symbol_count = 0

    for ts_code, expected_row in expected.items():
        actual_row = actual.get(ts_code)
        if actual_row is None or actual_row.actual_days == 0:
            missing_symbols.append(ts_code)
            continue
        if actual_row.actual_days < expected_row.expected_open_days:
            if len(partial_symbols) < sample_limit:
                partial_symbols.append(
                    {
                        "ts_code": ts_code,
                        "expected_open_days": expected_row.expected_open_days,
                        "actual_days": actual_row.actual_days,
                        "missing_days": expected_row.expected_open_days - actual_row.actual_days,
                        "suspend_days": expected_row.suspend_days,
                        "first_trade_date": actual_row.first_trade_date.isoformat() if actual_row.first_trade_date else None,
                        "last_trade_date": actual_row.last_trade_date.isoformat() if actual_row.last_trade_date else None,
                    }
                )
            continue
        complete_symbol_count += 1

    expected_open_day_total = sum(row.expected_open_days for row in expected.values())
    actual_open_day_total = sum(min(actual.get(ts_code).actual_days, row.expected_open_days) if ts_code in actual else 0 for ts_code, row in expected.items())
    missing_symbol_count = len(missing_symbols)
    partial_symbol_count = len(expected) - complete_symbol_count - missing_symbol_count

    return MinuteCoverageReport(
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        freq=freq,
        expected_symbol_count=len(expected),
        actual_symbol_count=len(actual),
        complete_symbol_count=complete_symbol_count,
        missing_symbol_count=missing_symbol_count,
        partial_symbol_count=partial_symbol_count,
        expected_open_day_total=expected_open_day_total,
        actual_open_day_total=actual_open_day_total,
        missing_symbols=missing_symbols[:sample_limit],
        partial_symbols=partial_symbols,
        complete=missing_symbol_count == 0 and partial_symbol_count == 0 and len(expected) > 0,
    )


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    report = build_minute_coverage_report(
        fetch_expected_symbol_coverage(args.start_date, args.end_date),
        fetch_actual_symbol_coverage(args.start_date, args.end_date, freq=args.freq),
        start_date=args.start_date,
        end_date=args.end_date,
        freq=args.freq,
        sample_limit=args.sample_limit,
    )
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
