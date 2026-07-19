"""Populate signal_events table from daily_signals.

Extracts buy and sell signal rows from daily_signals and inserts them
as individual events into the signal_events table.

Usage:
    .venv/bin/python scripts/populate_signal_events.py
    .venv/bin/python scripts/populate_signal_events.py --date 20260714
    .venv/bin/python scripts/populate_signal_events.py --start-date 20260701 --end-date 20260714
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import json
from datetime import date, datetime

import duckdb

from config.settings import settings
from utils.db import connect_write
from utils.logger import get_logger

logger = get_logger("populate_signal_events")

# ── signal column → strategy abbreviation ──────────────────────────
BUY_SIGNAL_MAP: dict[str, str] = {
    "signal_buy_b1": "B1",
    "signal_buy_b2": "B2",
    "signal_buy_blk": "BLK",
    "signal_buy_dl": "DL",
    "signal_buy_dz30": "DZ30",
    "signal_buy_scb": "SCB",
    "signal_buy_blkB2": "BLKB2",
}

SELL_SIGNAL_MAP: dict[str, str] = {
    "signal_sell_b1": "B1",
    "signal_sell_b2": "B2",
    "signal_sell_blk": "BLK",
    "signal_sell_dl": "DL",
    "signal_sell_dz30": "DZ30",
    "signal_sell_scb": "SCB",
    "signal_sell_blkB2": "BLKB2",
    "signal_s1_full": "S1",
    "signal_s1_half": "S1",
    "signal_止损": "STOP",
    # NOTE: signal_跌破多空线 is intentionally excluded — it fires for ~90% of
    # stocks every day (close < 知行多空线 is a trend state, not a discrete sell event).
    # The 跌破多空线 signal is still used directly by build_positions / risk module.
}

SCORE_MAP: dict[str, str] = {
    "B1": "score_b1",
    "B2": "score_b2",
    "BLK": "score_blk",
    "DL": "score_dl",
    "DZ30": "score_dz30",
    "SCB": "score_scb",
    "BLKB2": "score_blkB2",
    "S1": "score_s1",
}

DB_PATH = str(Path(settings.duckdb_path))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Populate signal_events from daily_signals"
    )
    parser.add_argument("--date", type=str, default=None, help="Single date YYYYMMDD")
    parser.add_argument(
        "--start-date", type=str, default=None, help="Start date YYYYMMDD"
    )
    parser.add_argument(
        "--end-date", type=str, default=None, help="End date YYYYMMDD"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Count events without inserting"
    )
    return parser.parse_args()


def _parse_date(raw: str) -> date:
    return datetime.strptime(raw, "%Y%m%d").date()


def build_events(conn: duckdb.DuckDBPyConnection, target_date: date) -> list[dict]:
    """Extract signal events for a single date from daily_signals."""
    iso = target_date.isoformat()
    events: list[dict] = []

    # get ALL signals for this date (was fetchone() — bug!)
    rows = conn.execute(
        """SELECT * FROM daily_signals WHERE "date" = ?""", [iso]
    ).fetchall()
    if not rows:
        return events

    cols = [desc[0] for desc in conn.description]

    for row in rows:
        record = dict(zip(cols, row))
        code = record.get("code", "")
        name_val = record.get("name", "")

        # buy signals
        for col_name, abbrev in BUY_SIGNAL_MAP.items():
            if col_name in record and record[col_name]:
                score_col = SCORE_MAP.get(abbrev, "")
                score = float(record.get(score_col, 0) or 0)
                events.append({
                    "date": iso,
                    "code": code,
                    "name": name_val,
                    "signal_abbrev": abbrev,
                    "version": "1.0.0",
                    "signal_type": "buy",
                    "score": score,
                    "signal_field": f"{abbrev}_BUY",
                })

        # sell signals — 只对持仓股记录卖出事件
        # (未持仓股的 S1 signal 仅做监控，不产生可交易的卖出事件)
        positions_codes: set[str] = set()
        try:
            pos_rows = conn.execute(
                "SELECT code FROM positions WHERE status = 'holding'"
            ).fetchall()
            positions_codes = {r[0] for r in pos_rows}
        except Exception:
            pass

        for col_name, abbrev in SELL_SIGNAL_MAP.items():
            if col_name in record and record[col_name]:
                # 跳过非持仓股的卖出信号
                if code not in positions_codes:
                    continue
                score_col = SCORE_MAP.get(abbrev, "")
                score = float(record.get(score_col, 0) or 0)
                if col_name == "signal_s1_full":
                    signal_field = "S1_FULL"
                elif col_name == "signal_s1_half":
                    signal_field = "S1_HALF"
                else:
                    signal_field = col_name.upper()
                events.append({
                    "date": iso,
                    "code": code,
                    "name": name_val,
                    "signal_abbrev": abbrev,
                    "version": "1.0.0",
                    "signal_type": "sell",
                    "score": score,
                    "signal_field": signal_field,
                })

    return events


def run(
    target_date: date | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Populate signal_events.

    One of target_date or (start_date, end_date) must be given.
    """
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        if start_date is not None and end_date is not None:
            dates = [
                date.fromisoformat(str(row[0]))
                for row in conn.execute(
                    "SELECT DISTINCT \"date\" FROM daily_signals "
                    "WHERE \"date\" BETWEEN ? AND ? ORDER BY \"date\"",
                    [start_date.isoformat(), end_date.isoformat()],
                ).fetchall()
            ]
        elif target_date is not None:
            dates = [target_date]
        elif start_date is not None:
            dates = [
                date.fromisoformat(str(row[0]))
                for row in conn.execute(
                    "SELECT DISTINCT \"date\" FROM daily_signals "
                    "WHERE \"date\" = ? "
                    "ORDER BY \"date\"",
                    [start_date.isoformat()],
                ).fetchall()
            ]
        else:
            dates = [
                date.fromisoformat(str(row[0]))
                for row in conn.execute(
                    'SELECT DISTINCT "date" FROM daily_signals ORDER BY "date"'
                ).fetchall()
            ]
    finally:
        conn.close()

    if not dates:
        logger.info("No dates with signals found.")
        return {"events": 0}

    logger.info(f"Processing {len(dates)} date(s): {dates[0]} ~ {dates[-1]}")

    all_events: list[dict] = []
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        for d in dates:
            all_events.extend(build_events(conn, d))
    finally:
        conn.close()

    # Deduplicate by (date, code, signal_abbrev, signal_type)
    seen: set[tuple] = set()
    unique_events: list[dict] = []
    for ev in all_events:
        key = (ev["date"], ev["code"], ev["signal_abbrev"], ev["signal_type"])
        if key not in seen:
            seen.add(key)
            unique_events.append(ev)

    buy_count = sum(1 for e in unique_events if e["signal_type"] == "buy")
    sell_count = sum(1 for e in unique_events if e["signal_type"] == "sell")
    logger.info(
        f"Extracted {len(unique_events)} unique events "
        f"(buy={buy_count}, sell={sell_count})"
    )

    # Show per-strategy breakdown
    by_strategy: dict[str, dict[str, int]] = {}
    for ev in unique_events:
        by_strategy.setdefault(ev["signal_abbrev"], {"buy": 0, "sell": 0})
        by_strategy[ev["signal_abbrev"]][ev["signal_type"]] += 1
    for abbr, counts in sorted(by_strategy.items()):
        logger.info(f"  {abbr:6s}  buy={counts['buy']:>5}  sell={counts['sell']:>5}")

    if dry_run:
        logger.info("[DRY RUN] No data written.")
        return {"events": len(unique_events), "buy": buy_count, "sell": sell_count}

    # Write to signal_events
    w_conn = connect_write(DB_PATH)
    try:
        # Remove existing events for these dates to make re-runs idempotent
        date_strs = [d.isoformat() for d in dates]
        placeholders = ", ".join([f"'{d}'" for d in date_strs])
        deleted = w_conn.execute(
            f"DELETE FROM signal_events WHERE date IN ({placeholders})"
        ).fetchone()[0]
        if deleted:
            logger.info(f"Cleared {deleted} existing event(s) for re-run")

        # Insert new events
        inserted = 0
        # Get max existing id
        max_id_row = w_conn.execute(
            "SELECT COALESCE(MAX(id), 0) FROM signal_events"
        ).fetchone()
        next_id = int(max_id_row[0]) + 1
        for ev in unique_events:
            w_conn.execute(
                """INSERT INTO signal_events
                   (id, date, code, name, signal_abbrev, version, signal_type, score, signal_field)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    next_id, ev["date"], ev["code"], ev["name"],
                    ev["signal_abbrev"], ev["version"],
                    ev["signal_type"], ev["score"], ev["signal_field"],
                ],
            )
            next_id += 1
            inserted += 1

        logger.info(f"Inserted {inserted} events into signal_events")
    finally:
        w_conn.close()

    return {"events": inserted, "buy": buy_count, "sell": sell_count}


def main() -> int:
    args = parse_args()
    target_date = _parse_date(args.date) if args.date else None
    start_date = _parse_date(args.start_date) if args.start_date else None
    end_date = _parse_date(args.end_date) if args.end_date else None

    if not target_date and not start_date:
        logger.info("No date specified; processing all dates with signals")

    try:
        result = run(
            target_date=target_date,
            start_date=start_date,
            end_date=end_date,
            dry_run=args.dry_run,
        )
        logger.info(f"Done: {json.dumps(result)}")
        return 0
    except Exception:
        logger.exception("populate_signal_events failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
