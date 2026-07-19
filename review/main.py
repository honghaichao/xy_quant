"""P1 复盘报告入口。"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from datetime import date
from pathlib import Path
import sys
from typing import Any

import duckdb
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from scripts.report_recap_data import (
    DUCKDB_PATH as RECAP_DUCKDB_PATH,
    RecapData,
    build_report,
    collect_duckdb_stats,
    collect_minute_progress,
    collect_postgres_stats,
    collect_scheduler_snapshot,
)

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "reports" / "review"
DEFAULT_MARKET_DUCKDB_PATH = PROJECT_ROOT / "data_store" / "market.duckdb"
DEFAULT_META_DB_PATH = PROJECT_ROOT / "data_store" / "meta.duckdb"
DEFAULT_REVIEW_META_DB_PATH = PROJECT_ROOT / "data_store" / "review_meta.duckdb"

from review.analyzer import ReviewAnalyzer, ReviewAnalysis
from review.collector import ReviewCollector
from review.narrative import ReviewNarrative


class DuckDBQueryStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def query(self, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
        normalized = sql
        values: list[Any] = []
        if params:
            for key, value in params.items():
                placeholder = f":{key}"
                while placeholder in normalized:
                    normalized = normalized.replace(placeholder, "?", 1)
                    values.append(value)
        with duckdb.connect(str(self._db_path), read_only=True) as conn:
            return conn.execute(normalized, values).df()


class PostgresQueryStore:
    def __init__(self) -> None:
        import psycopg

        self._psycopg = psycopg
        self._conn = psycopg.connect(
            host=settings.pg_host,
            port=settings.pg_port,
            user=settings.pg_user,
            password=settings.pg_password,
            dbname=settings.pg_database,
        )

    def query(self, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
        statement = sql
        values: list[Any] = []
        if params:
            for key, value in params.items():
                placeholder = f":{key}"
                while placeholder in statement:
                    statement = statement.replace(placeholder, "%s", 1)
                    values.append(value)
        with self._conn.cursor() as cursor:
            cursor.execute(statement, values or None)
            rows = cursor.fetchall()
            columns = [col.name for col in cursor.description or []]
        return pd.DataFrame(rows, columns=columns)

    def close(self) -> None:
        self._conn.close()



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a P1 review report")
    parser.add_argument("--trade-date", required=True, help="Trade date in YYYY-MM-DD format")
    parser.add_argument("--market-duckdb-path", type=Path, default=DEFAULT_MARKET_DUCKDB_PATH)
    parser.add_argument("--meta-db-path", type=Path, default=DEFAULT_META_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def run_daily_review(
    trade_date: str | date,
    market_duckdb_path: Path = DEFAULT_MARKET_DUCKDB_PATH,
    meta_db_path: Path = DEFAULT_META_DB_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> Path:
    trade_day = trade_date if isinstance(trade_date, date) else date.fromisoformat(trade_date)
    collector = ReviewCollector(
        market_store=DuckDBQueryStore(market_duckdb_path),
        meta_store=_build_meta_store(meta_db_path),
    )
    try:
        raw_data = collector.collect(trade_day)
        analysis = ReviewAnalyzer().analyze(raw_data)
        report_payload = _build_render_payload(analysis, trade_day)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"review_{trade_day.isoformat()}.md"
        rendered = ReviewNarrative().render(report_payload, output_path)
        output_path.write_text(rendered, encoding="utf-8")
        try:
            from review.renderer.image_renderer import render_review_image
            render_review_image(report_payload, output_dir, trade_day)
        except Exception:
            pass
        return output_path
    finally:
        meta_store = getattr(collector, "_meta_store", None)
        close = getattr(meta_store, "close", None)
        if callable(close):
            close()


def _build_meta_store(meta_db_path: Path) -> Any:
    if meta_db_path.exists():
        return DuckDBQueryStore(meta_db_path)
    review_meta_db_path = DEFAULT_REVIEW_META_DB_PATH
    if review_meta_db_path.exists():
        return DuckDBQueryStore(review_meta_db_path)
    return PostgresQueryStore()


def _build_render_payload(analysis: ReviewAnalysis, trade_day: date) -> dict[str, Any]:
    payload = _analysis_to_dict(analysis)
    recap_data = RecapData(
        minute_progress=collect_minute_progress(),
        duckdb_stats=collect_duckdb_stats(),
        postgres_stats=collect_postgres_stats(),
        scheduler_snapshot=collect_scheduler_snapshot(),
        plan_path=str(PROJECT_ROOT / "PLAN.md"),
        duckdb_path=str(RECAP_DUCKDB_PATH),
    )
    payload.setdefault("metrics", {})
    payload["metrics"]["recap_data"] = asdict(recap_data)
    payload["metrics"]["review_snapshot"] = {
        "market_duckdb_path": str(DEFAULT_MARKET_DUCKDB_PATH),
        "meta_db_path": str(DEFAULT_META_DB_PATH),
        "trade_date": trade_day.isoformat(),
    }
    return payload


def _analysis_to_dict(analysis: ReviewAnalysis) -> dict[str, Any]:
    if is_dataclass(analysis):
        return asdict(analysis)
    return {
        "trade_date": analysis.trade_date,
        "findings": analysis.findings,
        "metrics": analysis.metrics,
    }


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    output_path = run_daily_review(
        trade_date=args.trade_date,
        market_duckdb_path=args.market_duckdb_path,
        meta_db_path=args.meta_db_path,
        output_dir=args.output_dir,
    )
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
