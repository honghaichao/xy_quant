#!/usr/bin/env python3
"""Auto Factor Mining — daily cross-sectional IC on all indicators.

Mines indicators JSON from daily_signals, computes forward returns from
daily_bar, calculates IC per factor, ranks by |IC|, and persists to DuckDB.

Usage:
    .venv/bin/python scripts/auto_factor_mine.py                     # latest 20 days
    .venv/bin/python scripts/auto_factor_mine.py --date 20260716    # single day
    .venv/bin/python scripts/auto_factor_mine.py --all-dates         # full history
    .venv/bin/python scripts/auto_factor_mine.py --dry-run --top 20  # preview
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import json
from datetime import date, datetime, timedelta
from typing import Sequence

import duckdb
import numpy as np
import pandas as pd
from scipy import stats as sp_stats

from config.settings import settings
from utils.logger import get_logger

logger = get_logger("auto_factor_mine")

DB_PATH = str(settings.duckdb_path)
DEFAULT_LOOKBACK_DAYS = 20
MIN_CROSS_SECTIONAL = 100  # minimum stocks for a valid daily IC


def _to_date(v) -> date:
    if isinstance(v, date):
        return v
    if isinstance(v, pd.Timestamp):
        return v.date()
    return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()


def _date_range(conn: duckdb.DuckDBPyConnection,
                start: date | None, end: date | None) -> list[date]:
    """List trading days with daily_signals that have actual indicators."""
    where = "indicators IS NOT NULL AND indicators != '{}'"
    params: list = []
    if start:
        where += " AND date >= ?"
        params.append(start.isoformat())
    if end:
        where += " AND date <= ?"
        params.append(end.isoformat())
    rows = conn.execute(
        f"SELECT DISTINCT date FROM daily_signals WHERE {where} ORDER BY date", params
    ).fetchall()
    return [_to_date(r[0]) for r in rows]


def _to_datestr(v) -> str:
    """Convert Timestamp/date/datetime to 'YYYY-MM-DD'."""
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y-%m-%d")
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d")
    s = str(v)[:10]
    return s


def _indicators_snapshot(target: date) -> pd.DataFrame | None:
    """Parse indicators JSON → wide DataFrame (code + numeric cols)."""
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        rows = conn.execute(
            "SELECT code, indicators FROM daily_signals "
            "WHERE date = ? AND indicators IS NOT NULL AND indicators != '{}'",
            [target.isoformat()],
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return None

    records: list[dict] = []
    for code, raw in rows:
        try:
            ind = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            continue
        rec: dict = {"code": code}
        for k, v in ind.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                rec[k] = float(v)
        if len(rec) > 1:
            records.append(rec)
    if not records:
        return None
    df = pd.DataFrame(records)
    # Drop constant columns (e.g. all-zero flags)
    for c in list(df.columns):
        if c == "code":
            continue
        if df[c].nunique(dropna=False) <= 1:
            df.drop(columns=c, inplace=True)
    return df


def _fwd_returns(target: date, forward: int = 1) -> pd.DataFrame:
    """Compute forward period return from daily_bar.

    Returns DataFrame: code, ret_fwd
    """
    max_dt = target + timedelta(days=forward + 10)
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        df = conn.execute("""
            SELECT ts_code, trade_date, close
            FROM daily_bar
            WHERE trade_date >= ? AND trade_date <= ?
            ORDER BY ts_code, trade_date
        """, [target.isoformat(), max_dt.isoformat()]).fetchdf()
    finally:
        conn.close()
    if df.empty:
        return pd.DataFrame()

    df["code"] = df["ts_code"].str[:6]
    rets: list[dict] = []
    for _, g in df.groupby("code"):
        g = g.sort_values("trade_date")
        closes = g["close"].values
        tdates = g["trade_date"].values
        # find target date index
        for i, td in enumerate(tdates):
            if _to_datestr(td) == target.isoformat() and i + forward < len(g):
                if closes[i] > 0:
                    ret = (closes[i + forward] - closes[i]) / closes[i]
                    rets.append({"code": g.iloc[i]["code"], "ret_fwd": float(ret)})
                break
    return pd.DataFrame(rets)


def _ensure_tables(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS factor_ic (
            date         DATE    NOT NULL,
            factor_name  VARCHAR NOT NULL,
            ic           DOUBLE,
            ir           DOUBLE,
            ic_positive_ratio DOUBLE,
            sample_count INTEGER,
            updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (date, factor_name)
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS factor_rank (
            factor_name  VARCHAR NOT NULL,
            abs_ic_mean  DOUBLE,
            ic_std       DOUBLE,
            n_days       INTEGER,
            rank         INTEGER,
            updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (factor_name)
        )""")


def _ic_one_day(factor_df: pd.DataFrame, ret_df: pd.DataFrame,
                forward_days: Sequence[int] = (1, 5)) -> list[dict]:
    """Compute cross-sectional IC for every numeric factor column × forward day."""
    merged = factor_df.merge(ret_df, on="code", how="inner")
    if merged.empty or len(merged) < MIN_CROSS_SECTIONAL:
        return []

    records: list[dict] = []
    for col in factor_df.columns:
        if col == "code":
            continue
        valid = merged[[col, "ret_fwd"]].dropna()
        if len(valid) < MIN_CROSS_SECTIONAL:
            continue
        try:
            ic, _ = sp_stats.pearsonr(valid[col], valid["ret_fwd"])
        except Exception:
            continue
        if np.isfinite(ic):
            records.append({
                "factor_name": col,
                "ic": round(float(ic), 6),
                "sample_count": len(valid),
            })
    return records


def run(
    target_date: date | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    lookback: int = DEFAULT_LOOKBACK_DAYS,
    top_n: int = 20,
    dry_run: bool = False,
    forward_days: Sequence[int] = (1, 5),
) -> dict:
    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        if target_date:
            dates = [target_date]
        elif start_date and end_date:
            dates = _date_range(conn, start_date, end_date)
        else:
            # default: last N trading days
            all_dates = _date_range(conn, None, None)
            dates = all_dates[-lookback:]
    finally:
        conn.close()

    if not dates:
        logger.warning("No dates with indicators found. Run signal scan first.")
        return {"error": "no_data"}

    logger.info(f"Mining {len(dates)} dates ({dates[0]} ~ {dates[-1]}) "
                f"× {len(forward_days)} forward periods")

    # Accumulate |IC| per factor across all dates
    accum: dict[str, list[float]] = {}
    all_ic: list[dict] = []

    for i, d in enumerate(dates):
        factor_df = _indicators_snapshot(d)
        if factor_df is None or len(factor_df) < MIN_CROSS_SECTIONAL:
            continue

        for fwd in forward_days:
            ret_df = _fwd_returns(d, forward=fwd)
            if ret_df.empty:
                continue
            ic_recs = _ic_one_day(factor_df, ret_df)
            for rec in ic_recs:
                key = f"{rec['factor_name']}_{fwd}d"
                accum.setdefault(key, []).append(abs(rec["ic"]))
                all_ic.append({
                    "date": d.isoformat(),
                    "factor_name": key,
                    "ic": rec["ic"],
                    "sample_count": rec["sample_count"],
                })

        if (i + 1) % 10 == 0:
            logger.info(f"  {i + 1}/{len(dates)} days done, {len(accum)} factors tracked")

    if not accum:
        logger.warning("No IC computed — check daily_bar has forward data.")
        return {"error": "no_ic"}

    # Rank
    ranked = sorted(
        [(k, float(np.mean(v)), float(np.std(v)), len(v)) for k, v in accum.items()],
        key=lambda x: x[1], reverse=True,
    )

    # Persist
    if not dry_run:
        conn = duckdb.connect(DB_PATH)
        try:
            _ensure_tables(conn)
            for rec in all_ic:
                conn.execute(
                    "INSERT OR REPLACE INTO factor_ic (date, factor_name, ic, sample_count) "
                    "VALUES (?, ?, ?, ?)",
                    [rec["date"], rec["factor_name"], rec["ic"], rec["sample_count"]],
                )
            for rank_i, (name, abs_mean, std, ndays) in enumerate(ranked):
                conn.execute(
                    "INSERT OR REPLACE INTO factor_rank (factor_name, abs_ic_mean, ic_std, n_days, rank) "
                    "VALUES (?, ?, ?, ?, ?)",
                    [name, round(abs_mean, 6), round(std, 6), ndays, rank_i + 1],
                )
            conn.commit()
        finally:
            conn.close()

    # Report
    print(f"\n{'='*68}")
    print(f"  Auto Factor Mining — {len(dates)} days, {len(ranked)} factors")
    print(f"{'='*68}")
    print(f"  {'Factor':35s} {'|IC| μ':>8s}  {'σ':>8s}  {'Days':>5s}")
    print(f"  {'-'*56}")
    for name, abs_mean, std, ndays in ranked[:top_n]:
        print(f"  {name:35s} {abs_mean:8.4f}  {std:8.4f}  {ndays:5d}")
    if len(ranked) > top_n:
        print(f"  ... ({len(ranked) - top_n} more)")

    return {
        "dates": len(dates),
        "factors_mined": len(ranked),
        "top_factor": ranked[0][0] if ranked else None,
        "ic_records": len(all_ic),
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Auto Factor Mining")
    p.add_argument("--date", type=str, default=None, help="YYYYMMDD")
    p.add_argument("--start", type=str, default=None, help="YYYYMMDD start")
    p.add_argument("--end", type=str, default=None, help="YYYYMMDD end")
    p.add_argument("--lookback", type=int, default=DEFAULT_LOOKBACK_DAYS,
                   help="Number of past trading days (default 20)")
    p.add_argument("--top", type=int, default=20, help="Top N to show")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    target = datetime.strptime(args.date, "%Y%m%d").date() if args.date else None
    start = datetime.strptime(args.start, "%Y%m%d").date() if args.start else None
    end = datetime.strptime(args.end, "%Y%m%d").date() if args.end else None

    try:
        result = run(target_date=target, start_date=start, end_date=end,
                     lookback=args.lookback, top_n=args.top, dry_run=args.dry_run)
        logger.info(f"Done: {json.dumps(result, default=str)}")
        return 0 if "error" not in result else 1
    except Exception:
        logger.exception("auto_factor_mine failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
