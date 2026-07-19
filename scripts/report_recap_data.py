"""Collect recap data for the P0 retrospective report.

This script is intentionally read-only. It gathers:
- minute_bar progress from the active background log
- DuckDB table statistics
- Postgres table counts
- scheduler config snapshot
- quality gate status hints

Run from the project root with the venv activated and .env sourced.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import psycopg

from config.settings import settings
from data.source.factory import get_data_source

ROOT = Path(__file__).resolve().parents[1]
DUCKDB_PATH = ROOT / "data_store" / "market.duckdb"
SCHEDULER_CONFIG_PATH = ROOT / "config" / "scheduler_jobs.yaml"
PLAN_PATH = ROOT / "PLAN.md"
LOG_DIR = Path(os.environ.get("HERMES_RESULTS_DIR", "/var/folders/pc/3yg961_s6kzdr2qs_6sbbk1m0000gn/T/hermes-results"))
MINUTE_LOG_PATTERN = "call_*.txt"


@dataclass
class MinuteProgress:
    session_id: str | None
    latest_ts_code: str | None
    latest_chunk: str | None
    latest_range: str | None
    latest_total_rows: int | None
    completed_ts_codes: list[str]
    completed_count: int
    current_ts_code: str | None
    current_chunk: str | None
    current_range: str | None
    current_total_rows: int | None


@dataclass
class DuckDBStats:
    table_counts: dict[str, int]
    minute_bar_rows: int | None
    minute_bar_trade_date_min: str | None
    minute_bar_trade_date_max: str | None
    minute_bar_symbol_count: int | None


@dataclass
class PostgresStats:
    public_table_count: int
    key_table_counts: dict[str, int]


@dataclass
class SchedulerSnapshot:
    path: str
    exists: bool
    raw_text_preview: str | None
    enabled_job_lines: list[str]


@dataclass
class RecapData:
    minute_progress: MinuteProgress
    duckdb_stats: DuckDBStats
    postgres_stats: PostgresStats
    scheduler_snapshot: SchedulerSnapshot
    plan_path: str
    duckdb_path: str


MARKET_TABLES = ["daily_bar", "adj_factor", "daily_basic", "index_daily", "limit_list", "minute_bar"]
META_TABLES = ["stock_suspend", "top_list", "margin_detail", "hk_hold", "stock_money_flow", "concept_money_flow", "industry_money_flow"]


def _load_trade_dates(start_date: date, end_date: date) -> list[date]:
    trade_calendar = get_data_source(settings.primary_data_source).fetch_trade_calendar(
        start_date=start_date,
        end_date=end_date,
    )
    if trade_calendar.empty or "cal_date" not in trade_calendar.columns:
        return []
    if "is_open" in trade_calendar.columns:
        trade_calendar = trade_calendar.loc[trade_calendar["is_open"].astype(str) == "1"]

    trade_dates: list[date] = []
    for raw in trade_calendar["cal_date"].tolist():
        text = str(raw)
        if len(text) == 8 and text.isdigit():
            trade_dates.append(date.fromisoformat(f"{text[:4]}-{text[4:6]}-{text[6:8]}"))
        else:
            trade_dates.append(date.fromisoformat(text))
    return sorted(set(trade_dates))


def _duckdb_trade_date_expr(table: str) -> str:
    return "DATE(datetime)" if table == "minute_bar" else "DATE(trade_date)"


def _count_market_trade_days(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    start_date: date,
    end_date: date,
) -> int:
    trade_date_expr = _duckdb_trade_date_expr(table)
    row = conn.execute(
        f"""
        select count(*)
        from (
            select distinct {trade_date_expr} as trade_day
            from {table}
            where {trade_date_expr} between ? and ?
        ) q
        """,
        [start_date, end_date],
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _count_meta_trade_days(
    conn: psycopg.Connection[Any],
    table: str,
    start_date: date,
    end_date: date,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            select count(*)
            from (
                select distinct trade_date::date as trade_day
                from {table}
                where trade_date::date between %s and %s
            ) q
            """,
            (start_date, end_date),
        )
        row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _latest_log_file() -> Path | None:
    candidates = sorted(LOG_DIR.glob(MINUTE_LOG_PATTERN), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _parse_minute_log(text: str) -> MinuteProgress:
    progress_matches = list(
        re.finditer(
            r"minute_bar progress ts_code=(?P<ts_code>\S+) chunk=(?P<chunk>\d+/\d+) range=(?P<range>\S+\.\.\S+) chunk_rows=(?P<chunk_rows>\d+) total_rows=(?P<total_rows>\d+)",
            text,
        )
    )
    latest = progress_matches[-1] if progress_matches else None
    completed_ts_codes: list[str] = []
    for match in re.finditer(
        r"minute_bar progress ts_code=(?P<ts_code>\S+) chunk=117/117 range=.*? chunk_rows=0 total_rows=(?P<total_rows>\d+)",
        text,
    ):
        completed_ts_codes.append(match.group("ts_code"))

    return MinuteProgress(
        session_id=None,
        latest_ts_code=latest.group("ts_code") if latest else None,
        latest_chunk=latest.group("chunk") if latest else None,
        latest_range=latest.group("range") if latest else None,
        latest_total_rows=int(latest.group("total_rows")) if latest else None,
        completed_ts_codes=completed_ts_codes,
        completed_count=len(completed_ts_codes),
        current_ts_code=latest.group("ts_code") if latest else None,
        current_chunk=latest.group("chunk") if latest else None,
        current_range=latest.group("range") if latest else None,
        current_total_rows=int(latest.group("total_rows")) if latest else None,
    )


def collect_minute_progress() -> MinuteProgress:
    latest = _latest_log_file()
    if latest is None:
        return MinuteProgress(None, None, None, None, None, [], 0, None, None, None, None)
    text = latest.read_text(errors="replace")
    progress = _parse_minute_log(text)
    progress.session_id = latest.stem
    return progress


def collect_duckdb_stats() -> DuckDBStats:
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        table_counts: dict[str, int] = {}
        for table in MARKET_TABLES:
            try:
                row = con.execute(f"select count(*) from {table}").fetchone()
            except Exception:
                table_counts[table] = 0
                continue
            if row is None:
                table_counts[table] = 0
                continue
            table_counts[table] = int(row[0])

        minute_bar_rows = table_counts.get("minute_bar", 0)
        try:
            minute_row = con.execute(
                "select cast(min(trade_date) as varchar), cast(max(trade_date) as varchar), count(distinct ts_code) from minute_bar"
            ).fetchone()
        except Exception:
            minute_row = None
        if minute_row is None:
            minute_bar_trade_date_min = None
            minute_bar_trade_date_max = None
            minute_bar_symbol_count = 0
        else:
            minute_bar_trade_date_min, minute_bar_trade_date_max, minute_bar_symbol_count = minute_row
        return DuckDBStats(
            table_counts=table_counts,
            minute_bar_rows=minute_bar_rows,
            minute_bar_trade_date_min=minute_bar_trade_date_min,
            minute_bar_trade_date_max=minute_bar_trade_date_max,
            minute_bar_symbol_count=int(minute_bar_symbol_count or 0),
        )
    finally:
        con.close()


def collect_postgres_stats() -> PostgresStats:
    dsn = (
        f"host={settings.pg_host} port={settings.pg_port} dbname={settings.pg_database} "
        f"user={settings.pg_user} password={settings.pg_password}"
    )
    try:
        conn = psycopg.connect(dsn)
    except Exception:
        return PostgresStats(public_table_count=0, key_table_counts={})
    try:
        with conn, conn.cursor() as cur:
            try:
                cur.execute("select count(*) from information_schema.tables where table_schema='public'")
                public_row = cur.fetchone()
                public_table_count = int(public_row[0]) if public_row else 0
            except Exception:
                public_table_count = 0
            key_table_counts: dict[str, int] = {}
            for table in ["data_quality_report", "data_update_log", "concept_member", "industry_member", "concept_money_flow", "industry_money_flow", "stock_money_flow"]:
                try:
                    cur.execute(f"select count(*) from {table}")
                    row = cur.fetchone()
                    key_table_counts[table] = int(row[0]) if row else 0
                except Exception:
                    key_table_counts[table] = 0
            return PostgresStats(public_table_count=public_table_count, key_table_counts=key_table_counts)
    finally:
        conn.close()


def collect_scheduler_snapshot() -> SchedulerSnapshot:
    exists = SCHEDULER_CONFIG_PATH.exists()
    raw_text = SCHEDULER_CONFIG_PATH.read_text() if exists else None
    enabled_job_lines: list[str] = []
    if raw_text:
        for line in raw_text.splitlines():
            if "enabled:" in line or line.strip().startswith("- name:") or "start_date:" in line or "end_date:" in line:
                enabled_job_lines.append(line)
    return SchedulerSnapshot(
        path=str(SCHEDULER_CONFIG_PATH),
        exists=exists,
        raw_text_preview=(raw_text[:1000] if raw_text else None),
        enabled_job_lines=enabled_job_lines,
    )


def build_report(start_date: date, end_date: date) -> dict[str, Any]:
    trade_dates = _load_trade_dates(start_date, end_date)
    total_trade_days = len(trade_dates)
    market_rows: list[dict[str, Any]] = []
    meta_rows: list[dict[str, Any]] = []

    market_conn = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        for table in MARKET_TABLES:
            try:
                covered_trade_days = _count_market_trade_days(market_conn, table, start_date, end_date)
            except Exception:
                covered_trade_days = 0
            market_rows.append(
                {
                    "table": table,
                    "store": "duckdb",
                    "covered_trade_days": covered_trade_days,
                    "missing_trade_days": max(total_trade_days - covered_trade_days, 0),
                    "coverage_pct": round((covered_trade_days / total_trade_days * 100) if total_trade_days else 0.0, 2),
                }
            )
    finally:
        market_conn.close()

    pg_dsn = (
        f"host={settings.pg_host} port={settings.pg_port} dbname={settings.pg_database} "
        f"user={settings.pg_user} password={settings.pg_password}"
    )
    try:
        pg_conn = psycopg.connect(pg_dsn)
    except Exception:
        pg_conn = None

    if pg_conn is not None:
        try:
            with pg_conn:
                for table in META_TABLES:
                    try:
                        covered_trade_days = _count_meta_trade_days(pg_conn, table, start_date, end_date)
                    except Exception:
                        covered_trade_days = 0
                    meta_rows.append(
                        {
                            "table": table,
                            "store": "postgres",
                            "covered_trade_days": covered_trade_days,
                            "missing_trade_days": max(total_trade_days - covered_trade_days, 0),
                            "coverage_pct": round((covered_trade_days / total_trade_days * 100) if total_trade_days else 0.0, 2),
                        }
                    )
        finally:
            close = getattr(pg_conn, "close", None)
            if callable(close):
                close()

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "total_trade_days": total_trade_days,
        "market": market_rows,
        "meta": meta_rows,
    }


def main() -> None:
    recap = RecapData(
        minute_progress=collect_minute_progress(),
        duckdb_stats=collect_duckdb_stats(),
        postgres_stats=collect_postgres_stats(),
        scheduler_snapshot=collect_scheduler_snapshot(),
        plan_path=str(PLAN_PATH),
        duckdb_path=str(DUCKDB_PATH),
    )
    print(json.dumps(asdict(recap), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
