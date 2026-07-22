"""盘中实时数据采集脚本 — 调度器兼容入口。

由 APScheduler intraday_snapshot job 每 5 分钟调用一次，
也支持命令行独立运行（--mode / --loop）。

写入三表:
  fetcher.fetch_spot()            → intraday_spot
  fetcher.fetch_fund_flow_rank()  → intraday_fund_flow
  fetcher.fetch_sector_fund_flow() → intraday_sector_flow

Usage:
  .venv/bin/python scripts/run_intraday_collect.py              # full mode (scheduler)
  .venv/bin/python scripts/run_intraday_collect.py --mode spot  # spot only
  .venv/bin/python scripts/run_intraday_collect.py --loop       # polling until close
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import json
import time
from datetime import date, datetime

import duckdb

from config.settings import settings
from data.source.intraday_source import IntradayFetcher
from utils.logger import get_logger

logger = get_logger("run_intraday_collect")
DB_PATH = str(Path(settings.duckdb_path))


# ── helpers ──────────────────────────────────────────────────────────

def _upsert(df, table: str) -> int:
    """Upsert DataFrame into DuckDB table by PK. Returns row count."""
    if df.empty:
        return 0
    conn = duckdb.connect(DB_PATH, read_only=False)
    try:
        conn.register("_tmp", df)
        conn.execute(f"INSERT OR REPLACE INTO {table} BY NAME SELECT * FROM _tmp")
        conn.unregister("_tmp")
        return len(df)
    finally:
        conn.close()


def _ensure_sector_flow_table() -> None:
    """Ensure intraday_sector_flow table exists (may be missing from duckdb_store init)."""
    conn = duckdb.connect(DB_PATH, read_only=False)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS intraday_sector_flow (
                fetch_time TIMESTAMP NOT NULL,
                sector_name VARCHAR NOT NULL,
                sector_type VARCHAR NOT NULL,
                trade_date DATE NOT NULL,
                pct_chg DOUBLE,
                main_inflow DOUBLE,
                main_inflow_pct DOUBLE,
                super_inflow DOUBLE,
                big_inflow DOUBLE,
                mid_inflow DOUBLE,
                small_inflow DOUBLE,
                top_stock VARCHAR,
                sector_code VARCHAR,
                PRIMARY KEY (sector_name, sector_type, trade_date, fetch_time)
            )
        """)
    finally:
        conn.close()


# ── collectors ───────────────────────────────────────────────────────

def collect_spot(fetcher: IntradayFetcher, dry: bool = False) -> int:
    """Full-market spot snapshot → intraday_spot."""
    logger.info("Fetching spot snapshot...")
    df = fetcher.fetch_spot()
    if df.empty:
        logger.warning("spot returned empty")
        return 0
    logger.info(f"spot: {len(df)} stocks")
    if dry:
        return len(df)
    return _upsert(df, "intraday_spot")


def collect_fundflow(fetcher: IntradayFetcher, dry: bool = False) -> int:
    """Individual stock fund flow rank → intraday_fund_flow."""
    logger.info("Fetching fund flow rank...")
    df = fetcher.fetch_fund_flow_rank()
    if df.empty:
        logger.warning("fundflow returned empty")
        return 0
    logger.info(f"fundflow: {len(df)} stocks")
    if dry:
        return len(df)
    return _upsert(df, "intraday_fund_flow")


def collect_sector(fetcher: IntradayFetcher, dry: bool = False) -> int:
    """Sector (industry + concept) fund flow → intraday_sector_flow."""
    logger.info("Fetching sector flow...")
    df = fetcher.fetch_sector_fund_flow()
    if df.empty:
        logger.warning("sector flow returned empty")
        return 0
    # Ensure trade_date column for PK
    if "trade_date" not in df.columns:
        df["trade_date"] = date.today()
    logger.info(f"sector flow: {len(df)} entries (industry+concept)")
    if dry:
        return len(df)
    _ensure_sector_flow_table()
    return _upsert(df, "intraday_sector_flow")


def collect_full(fetcher: IntradayFetcher, dry: bool = False) -> dict[str, int]:
    """Run all three collectors. Failures in one don't stop others."""
    counts: dict[str, int] = {}
    for label, fn in [
        ("spot", collect_spot),
        ("fundflow", collect_fundflow),
        ("sector", collect_sector),
    ]:
        try:
            counts[label] = fn(fetcher, dry)
        except Exception as e:
            logger.error(f"{label} failed: {e}")
            counts[label] = 0
    return counts


# ── alert check ──────────────────────────────────────────────────────

def _check_market_alert(spot_df, sector_df) -> list[dict]:
    """Check for market alert conditions. Returns list of alert dicts."""
    alerts: list[dict] = []

    # 1) Check Shanghai index drop vs open
    sh_row = spot_df[spot_df["ts_code"].str.startswith("000001")] if not spot_df.empty else None
    if sh_row is not None and not sh_row.empty:
        row = sh_row.iloc[0]
        open_p = row.get("open", 0)
        close_p = row.get("close", 0)
        if open_p and close_p and open_p > 0:
            drop_pct = (close_p - open_p) / open_p * 100
            if drop_pct < -2.0:
                alerts.append({
                    "type": "index_drop",
                    "msg": f"上证指数较开盘跌{abs(drop_pct):.1f}%",
                    "drop_pct": round(drop_pct, 2),
                })

    # 2) Sector flow outlier check
    if not sector_df.empty and "main_inflow" in sector_df.columns:
        top_in = sector_df.nlargest(5, "main_inflow")
        top_out = sector_df.nsmallest(5, "main_inflow")
        for _, r in top_in.iterrows():
            name = r.get("name", "?")
            inflow = float(r.get("main_inflow", 0))
            if inflow > 20_0000:  # 20亿 (in 万元)
                alerts.append({
                    "type": "sector_inflow",
                    "msg": f"{name} 主力大幅流入 {inflow/1e4:.1f}亿",
                })
        for _, r in top_out.iterrows():
            name = r.get("name", "?")
            outflow = float(r.get("main_inflow", 0))
            if outflow < -20_0000:
                alerts.append({
                    "type": "sector_outflow",
                    "msg": f"{name} 主力大幅流出 {abs(outflow)/1e4:.1f}亿",
                })

    return alerts


def _send_feishu_alerts(alerts: list[dict]) -> None:
    """Send alerts via Feishu card. Gracefully skip if config missing."""
    if not alerts:
        return
    try:
        from utils.feishu_alert import send_alert_card
    except ImportError:
        logger.info(f"Skipping feishu alert ({len(alerts)} conditions, utils.feishu_alert not available)")
        return

    try:
        send_alert_card("盘中预警", alerts)
    except Exception as e:
        logger.warning(f"Feishu alert send failed: {e}")


# ── main ─────────────────────────────────────────────────────────────

def main(**kwargs) -> dict:
    """Scheduler-compatible entry: no required args.

    The scheduler calls main() with no arguments. When called from CLI,
    parse_args() provides argparse-style control.
    """
    # Detect if called from CLI (has sys.argv beyond script name) or scheduler (no args)
    args = parse_args() if any(a.startswith("-") for a in sys.argv[1:]) else argparse.Namespace(
        mode="full", loop=False, interval=300, dry_run=False, code=None,
    )

    fetcher = IntradayFetcher()

    if args.loop:
        return _run_loop(fetcher, args)

    return _run_once(fetcher, args)


def _run_once(fetcher: IntradayFetcher, args: argparse.Namespace) -> dict:
    """Single-shot collection. Returns counts dict."""
    dry = args.dry_run
    code = args.code

    try:
        if args.mode == "spot":
            return {"spot": collect_spot(fetcher, dry)}
        elif args.mode == "fundflow":
            return {"fundflow": collect_fundflow(fetcher, dry)}
        elif args.mode == "sector":
            return {"sector": collect_sector(fetcher, dry)}
        elif args.mode == "minute":
            if not code:
                logger.error("--code required for minute mode")
                return {"minute": 0}
            return {"minute": _collect_minute(fetcher, code, dry)}
        elif args.mode == "tick":
            if not code:
                logger.error("--code required for tick mode")
                return {"tick": 0}
            return {"tick": _collect_tick(fetcher, code, dry)}
        else:  # "full"
            result = collect_full(fetcher, dry)

            # Check alerts (non-blocking; only in full mode)
            if not dry:
                try:
                    spot_df = fetcher.fetch_spot()
                    sector_df = fetcher.fetch_sector_fund_flow()
                    alerts = _check_market_alert(spot_df, sector_df)
                    if alerts:
                        _send_feishu_alerts(alerts)
                except Exception as e:
                    logger.warning(f"Alert check failed: {e}")

            return result
    except Exception as e:
        logger.error(f"Collection failed: {e}")
        return {"error": str(e)}


def _run_loop(fetcher: IntradayFetcher, args: argparse.Namespace) -> dict:
    """Polling loop until market close. Returns final summary."""
    logger.info(f"Loop mode: every {args.interval}s, mode={args.mode}")
    totals: dict[str, int] = {}

    while True:
        now = datetime.now()
        if now.weekday() >= 5:
            logger.info("Weekend — stopping")
            break
        if now.hour < 9 or (now.hour == 9 and now.minute < 25):
            logger.info("Before market open — skipping")
            time.sleep(args.interval)
            continue
        if now.hour >= 15 and now.minute >= 5:
            logger.info("After market close — stopping")
            break

        try:
            result = _run_once(fetcher, args)
            for k, v in result.items():
                totals[k] = totals.get(k, 0) + (v if isinstance(v, int) else 0)
            logger.info(f"loop result: {json.dumps(result)}")
        except Exception as e:
            logger.error(f"loop iteration failed: {e}")

        time.sleep(args.interval)

    logger.info(f"Loop done. Totals: {json.dumps(totals)}")
    return totals


def _collect_minute(fetcher: IntradayFetcher, code: str, dry: bool = False) -> int:
    """Fetch today's 1-min bars for a single stock → minute_bar_YYYY_MM."""
    logger.info(f"Fetching minute bars for {code}...")
    df = fetcher.fetch_minute_today(code, period="1")
    if df.empty:
        logger.warning(f"minute {code}: empty")
        return 0
    logger.info(f"minute {code}: {len(df)} bars")
    if dry:
        return len(df)

    conn = duckdb.connect(DB_PATH, read_only=False)
    try:
        month_str = df["datetime"].iloc[0][:7].replace("-", "_")
        table = f"minute_bar_{month_str}"
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {table} AS SELECT * FROM minute_bar WHERE 1=0"
        )
        conn.register("_tmp_min", df)
        conn.execute(f"INSERT OR REPLACE INTO {table} BY NAME SELECT * FROM _tmp_min")
        conn.unregister("_tmp_min")
        return len(df)
    finally:
        conn.close()


def _collect_tick(fetcher: IntradayFetcher, code: str, dry: bool = False) -> int:
    """Fetch today's tick data for a single stock (display only, no persist)."""
    logger.info(f"Fetching ticks for {code}...")
    df = fetcher.fetch_tick(code)
    if df.empty:
        logger.warning(f"tick {code}: empty")
        return 0
    logger.info(f"tick {code}: {len(df)} trades")
    return len(df)


# ── argparse (CLI mode only) ─────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch intraday data (scheduler-compatible)")
    p.add_argument("--mode", default="full",
                   choices=["spot", "fundflow", "sector", "full", "minute", "tick"])
    p.add_argument("--code", default=None, help="Stock code for minute/tick mode")
    p.add_argument("--loop", action="store_true", help="Keep polling until market close")
    p.add_argument("--interval", type=int, default=300, help="Polling interval in seconds")
    p.add_argument("--dry-run", action="store_true", help="Print without writing")
    return p.parse_args()


if __name__ == "__main__":
    result = main()
    if result:
        print(json.dumps(result, ensure_ascii=False, indent=2))
