#!/usr/bin/env python3
"""全市场信号扫描 — 批量版（复用 DB 连接，~15min 跑完 5577 只）。

用法:
    PYTHONPATH=. python scripts/batch_scan.py --date 2026-07-14
    PYTHONPATH=. python scripts/batch_scan.py --date 2026-07-14 --batch-size 100
"""
import argparse, sys, os, time, json
from datetime import datetime
import numpy as np
import pandas as pd
import duckdb

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
DB_PATH = os.path.join(PROJ, "data_store/market.duckdb")

DATA_DAYS = 150


def code_to_ts(code: str) -> str:
    code = str(code)
    return f"{code}.SH" if code.startswith("6") else f"{code}.SZ"


def load_stock_data(db: duckdb.DuckDBPyConnection, ts_codes: list[str], target_date: str) -> pd.DataFrame:
    """一次查询拉取所有股票的 OHLCV（过去 DATA_DAYS 天）。"""
    placeholders = ",".join(["?"] * len(ts_codes))
    sql = f"""
        SELECT ts_code, trade_date, open, high, low, close, vol
        FROM daily_bar
        WHERE ts_code IN ({placeholders})
          AND trade_date <= ?
        ORDER BY ts_code, trade_date
    """
    params = ts_codes + [target_date]
    return db.execute(sql, params).fetchdf()


def compute_signals_for_code(ts_code: str, group: pd.DataFrame, name_map: dict[str, str]) -> dict | None:
    """对单只股票计算所有策略信号。"""
    # NOTE: lazy imports to avoid top-level import cost
    from signals.signal_cal.basic_module import calculate_indicators
    from signals.signal_cal.B1_module import calculate_b1_score
    from signals.signal_cal.B2_module import calculate_b2_score
    from signals.signal_cal.S1_module import calculate_s1_score
    from signals.signal_cal.BLKB2_module import check_暴力K, check_倍量柱, check_J拐头向上
    from signals.signal_cal.SCB_module import (
        check_dl_basic_condition, calculate_blk_signal, calculate_scb_signal,
    )
    from signals.signal_cal.DZ30_module import check_长短期KD, check_前20日非阴, calculate_倍量柱_arr

    if group.empty or len(group) < 60:
        return None

    df = group.sort_values("trade_date").tail(DATA_DAYS).reset_index(drop=True)
    df = df.rename(columns={"ts_code": "code", "trade_date": "date", "vol": "volume"})

    try:
        ind = calculate_indicators(df)
    except Exception:
        return None

    code = str(ts_code)[:6]
    b1 = calculate_b1_score(ind)
    b2 = calculate_b2_score(ind)
    s1 = calculate_s1_score(ind)

    trend = ind["知行短期趋势线"] > ind["知行多空线"]
    macd_ok = ind["dif"] >= 0
    j_low = ind["j"] < 13

    b1_buy = j_low and macd_ok and trend and b1 >= 8
    b2_buy = macd_ok and trend and b2 >= 8

    blk = check_暴力K(ind)
    blk_buy = trend and blk

    bzl = check_倍量柱(ind)
    jgt = check_J拐头向上(ind)
    blkb2_buy = macd_ok and trend and b2 >= 8 and blk and bzl and jgt

    # SCB
    dl_hist = []
    for offset in range(1, 6):
        hi = {
            "code": ind["code"], "close": ind["close_arr"][-offset - 1],
            "prev_close": ind["close_arr"][-offset - 2],
            "open": ind["open_arr"][-offset - 1], "high": ind["high_arr"][-offset - 1],
            "low": ind["low_arr"][-offset - 1], "volume": ind["volume_arr"][-offset - 1],
            "close_arr": ind["close_arr"][: -(offset + 1)],
            "open_arr": ind["open_arr"][: -(offset + 1)],
            "high_arr": ind["high_arr"][: -(offset + 1)],
            "low_arr": ind["low_arr"][: -(offset + 1)],
            "volume_arr": ind["volume_arr"][: -(offset + 1)],
        }
        dl_hist.append(check_dl_basic_condition(hi))
    blk_sig = calculate_blk_signal(ind)
    scb_sig, scb_score = calculate_scb_signal(ind, blk_sig, dl_hist)

    # DZ30
    skd, lkd = check_长短期KD(ind)
    bzl_arr = calculate_倍量柱_arr(ind)
    bzl20 = (np.sum(bzl_arr[-20:]) >= 1) if len(bzl_arr) >= 20 else (np.sum(bzl_arr) >= 1)
    dz30_buy = (
        lkd >= 80 and skd <= 30 and ind["close"] > ind["知行短期趋势线"]
        and trend and bzl20 and check_前20日非阴(ind)
    )

    broken = ind["close"] < ind["知行多空线"]

    # ── serialize indicators for later factor computation ──
    try:
        # Only keep the last value for each indicator (not arrays)
        flat_indicators = {}
        for key, val in ind.items():
            if isinstance(val, (list, np.ndarray)) and len(val) > 0:
                flat_indicators[key] = val[-1]
            elif not isinstance(val, (list, np.ndarray)):
                flat_indicators[key] = val
        indicators_json = json.dumps(flat_indicators, ensure_ascii=False)
    except Exception:
        indicators_json = "{}"

    return {
        "date": group["trade_date"].max(), "code": code, "name": name_map.get(code, code),
        "open": ind["open"], "high": ind["high"], "low": ind["low"],
        "close": ind["close"], "volume": ind["volume"],
        "prev_close": ind["prev_close"], "change_pct": ind["涨幅"],
        "score_b1": b1, "score_b2": b2, "score_blk": 7 if blk_buy else 0,
        "score_dl": 0, "score_dz30": 5 if dz30_buy else 0,
        "score_scb": scb_score, "score_blkB2": 0,
        "signal_buy_b1": b1_buy, "signal_buy_b2": b2_buy,
        "signal_buy_blk": blk_buy, "signal_buy_dl": False,
        "signal_buy_dz30": dz30_buy, "signal_buy_scb": scb_sig,
        "signal_buy_blkB2": blkb2_buy,
        "signal_sell_b1": s1 >= 12 or (8 <= s1 < 12),
        "signal_sell_b2": s1 >= 12 or (8 <= s1 < 12),
        "signal_sell_blk": s1 >= 12 or (8 <= s1 < 12),
        "signal_sell_dl": False,
        "signal_sell_dz30": s1 >= 12 or (8 <= s1 < 12),
        "signal_sell_scb": s1 >= 12 or (8 <= s1 < 12),
        "signal_sell_blkB2": s1 >= 12 or (8 <= s1 < 12),
        "score_s1": s1, "signal_s1_full": s1 >= 12,
        "signal_s1_half": 8 <= s1 < 12,
        "signal_跌破多空线": broken, "signal_止损": False,
        "is_observing": broken,
        "indicators": indicators_json,
    }


def run(target_date: str, batch_size: int = 0) -> dict:
    td = f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:]}"

    db = duckdb.connect(DB_PATH, read_only=True)
    all_codes = [
        r[0] for r in db.execute(
            f"SELECT DISTINCT ts_code FROM daily_bar WHERE trade_date='{td}'"
        ).fetchall()
    ]
    db.close()

    print(f"Scanning {len(all_codes)} stocks for {td}")
    t0 = time.time()

    if not all_codes:
        print(f"No stocks with daily_bar data for {td} — skipping scan.")
        return {
            "date": td, "total_stocks": 0,
            "success_count": 0, "fail_count": 0,
            "signal_stats": {}, "duration": time.time() - t0,
        }

    # 拉取全市场最近 DATA_DAYS 数据一次性
    db = duckdb.connect(DB_PATH, read_only=True)
    df_all = load_stock_data(db, all_codes, td)
    db.close()

    print(f"Loaded {len(df_all)} rows from DuckDB in {time.time()-t0:.1f}s")

    # 加载股票名称映射
    from utils.stock_name import load_name_map
    name_map = load_name_map()
    print(f"Loaded {len(name_map)} stock names from PostgreSQL")
    if not name_map:
        print("WARNING: name map empty — stock names will display as codes")

    results = []
    grouped = df_all.groupby("ts_code")

    for i, (ts_code, group) in enumerate(grouped):
        r = compute_signals_for_code(ts_code, group, name_map)
        if r:
            results.append(r)
        if (i + 1) % 500 == 0:
            elapsed = time.time() - t0
            print(f"[{elapsed:.0f}s] {i+1}/{len(all_codes)} stocks "
                  f"→ {len(results)} signals ({len(results)*100/(i+1):.1f}%)")

    elapsed = time.time() - t0

    # Save
    if results:
        dbw = duckdb.connect(DB_PATH)
        dbw.execute(f"DELETE FROM daily_signals WHERE date = '{td}'")
        df_r = pd.DataFrame(results)
        dbw.execute("INSERT INTO daily_signals BY NAME SELECT * FROM df_r")
        dbw.close()

    # Stats
    stats = {}
    for s in ["b1", "b2", "blk", "blkB2", "scb", "dz30"]:
        stats[f"signal_buy_{s}"] = sum(1 for r in results if r.get(f"signal_buy_{s}"))

    print(f"\nDone in {elapsed:.0f}s: {len(results)} signals from {len(all_codes)} stocks")
    for k, v in stats.items():
        if v > 0:
            print(f"  {k}: {v}")

    return {
        "date": td, "total_stocks": len(all_codes),
        "success_count": len(results),
        "fail_count": len(all_codes) - len(results),
        "signal_stats": stats, "duration": elapsed,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="全市场信号扫描 (批量版)")
    p.add_argument("--date", type=str, required=True, help="YYYYMMDD")
    p.add_argument("--batch-size", type=int, default=0, help="限制股票数")
    result = run(target_date=p.parse_args().date)
    return 0


def run_job(**kwargs: object) -> dict:
    """Scheduler entry point — uses today's date by default."""
    from datetime import date as dt_date
    target = str(kwargs.get("date", dt_date.today().strftime("%Y%m%d")))
    batch = int(kwargs.get("batch_size", 0))
    return run(target_date=target, batch_size=batch)


if __name__ == "__main__":
    sys.exit(main())
