#!/usr/bin/env python3
"""全市场信号扫描入口 (单进程版，绕过 multiprocessing fork 问题)。

用法:
    python scripts/run_signal_scan.py --date 2026-07-11
    python scripts/run_signal_scan.py --date 2026-07-11 --limit 100  # 测试前100只
"""
import argparse
import sys

import duckdb
import numpy as np
import pandas as pd

from config.settings import settings
from utils.log_utils import setup_logger

DB_PATH = settings.duckdb_path
logger = setup_logger("run_signal_scan", "pipeline")

DATA_DAYS = 150


def code_to_ts_code(code: str) -> str:
    code = str(code)
    return f"{code}.SH" if code.startswith("6") else f"{code}.SZ"


def get_db():
    return duckdb.connect(DB_PATH, read_only=False)


def get_trading_date(date_str: str | None = None) -> str:
    if date_str:
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    conn = get_db()
    try:
        latest = conn.execute("SELECT MAX(trade_date) FROM daily_bar").fetchone()[0]
        return str(latest)
    finally:
        conn.close()


def get_stock_list() -> list[dict]:
    """从 DuckDB 获取活跃股票列表。"""
    conn = get_db()
    try:
        df = conn.execute("""
            SELECT DISTINCT ts_code
            FROM daily_bar
            WHERE trade_date >= '2025-01-01'
            ORDER BY ts_code
        """).fetchdf()
        if len(df) == 0:
            return []
        result = []
        for _, row in df.iterrows():
            ts_code = row["ts_code"]
            code = ts_code[:6]
            result.append({"code": code, "ts_code": ts_code})
        return result
    finally:
        conn.close()


def get_stock_data(ts_code: str, trading_date: str, days: int = DATA_DAYS) -> pd.DataFrame | None:
    conn = get_db()
    try:
        df = conn.execute(
            """SELECT ts_code, trade_date, open, high, low, close, vol
               FROM daily_bar WHERE ts_code = ? AND trade_date <= ?
               ORDER BY trade_date DESC LIMIT ?""",
            [ts_code, trading_date, days],
        ).fetchdf()
        if df is None or len(df) < 60:
            return None
        df = df.rename(columns={"ts_code": "code", "trade_date": "date", "vol": "volume"})
        return df.sort_values("date").reset_index(drop=True)
    except Exception as e:
        logger.error(f"get_stock_data {ts_code}: {e}")
        return None
    finally:
        conn.close()


def process_one_stock(stock: dict, trading_date: str) -> dict | None:
    """处理单只股票 — 单进程版。"""
    from signals.signal_cal.basic_module import calculate_indicators
    from signals.signal_cal.B1_module import calculate_b1_score
    from signals.signal_cal.B2_module import calculate_b2_score
    from signals.signal_cal.S1_module import calculate_s1_score
    from signals.signal_cal.BLKB2_module import check_暴力K, check_倍量柱, check_J拐头向上
    from signals.signal_cal.SCB_module import (
        check_dl_basic_condition, calculate_blk_signal, calculate_scb_signal,
    )
    from signals.signal_cal.DZ30_module import check_长短期KD, check_前20日非阴, calculate_倍量柱_arr

    code = stock["code"]
    ts_code = stock["ts_code"]

    df = get_stock_data(ts_code, trading_date)
    if df is None:
        return None

    indicators = calculate_indicators(df)

    b1_threshold = 8
    b2_threshold = 8

    try:
        # Buy signals
        b1_score = calculate_b1_score(indicators)
        b1_buy = (indicators['j'] < 13 and indicators['dif'] >= 0
                  and indicators['知行短期趋势线'] > indicators['知行多空线']
                  and b1_score >= b1_threshold)

        b2_score = calculate_b2_score(indicators)
        b2_buy = (indicators['dif'] >= 0
                  and indicators['知行短期趋势线'] > indicators['知行多空线']
                  and b2_score >= b2_threshold)

        暴力K = check_暴力K(indicators)
        趋势条件 = indicators['知行短期趋势线'] > indicators['知行多空线']
        blk_buy = 趋势条件 and 暴力K
        blk_score = 7 if blk_buy else 0

        倍量柱 = check_倍量柱(indicators)
        J拐头 = check_J拐头向上(indicators)
        macd条件 = indicators['dif'] >= 0
        blkb2_buy = macd条件 and 趋势条件 and b2_score >= b2_threshold and 暴力K and 倍量柱 and J拐头
        blkb2_score = (7 * 0.5 + b2_score * 0.6) if blkb2_buy else 0

        dl_hist = []
        for offset in range(1, 6):
            hi = {
                'code': indicators['code'],
                'close': indicators['close_arr'][-offset-1],
                'prev_close': indicators['close_arr'][-offset-2],
                'open': indicators['open_arr'][-offset-1],
                'high': indicators['high_arr'][-offset-1],
                'low': indicators['low_arr'][-offset-1],
                'volume': indicators['volume_arr'][-offset-1],
                'close_arr': indicators['close_arr'][:-(offset+1)],
                'open_arr': indicators['open_arr'][:-(offset+1)],
                'high_arr': indicators['high_arr'][:-(offset+1)],
                'low_arr': indicators['low_arr'][:-(offset+1)],
                'volume_arr': indicators['volume_arr'][:-(offset+1)],
            }
            dl_hist.append(check_dl_basic_condition(hi))
        blk_sig = calculate_blk_signal(indicators)
        scb_sig, scb_score = calculate_scb_signal(indicators, blk_sig, dl_hist)

        短期KD, 长期KD = check_长短期KD(indicators)
        dz30_cond = (长期KD >= 80 and 短期KD <= 30 and
                     indicators['close'] > indicators['知行短期趋势线'] and 趋势条件 and
                     np.sum(calculate_倍量柱_arr(indicators)[-20:]) >= 1 and
                     check_前20日非阴(indicators))
        dz30_score = 5 if dz30_cond else 0

        # S1 sell
        s1 = calculate_s1_score(indicators)
        s1_full = s1 >= 10
        s1_half = 5 <= s1 < 10
        broken = indicators['close'] < indicators['知行多空线']

        result = {
            'date': trading_date, 'code': code, 'name': code,
            'open': indicators['open'], 'high': indicators['high'],
            'low': indicators['low'], 'close': indicators['close'],
            'volume': indicators['volume'], 'prev_close': indicators['prev_close'],
            'change_pct': indicators['涨幅'],
            'score_b1': b1_score, 'score_b2': b2_score,
            'score_blk': blk_score, 'score_dl': 0,
            'score_dz30': dz30_score, 'score_scb': scb_score,
            'score_blkB2': blkb2_score,
            'signal_buy_b1': b1_buy, 'signal_buy_b2': b2_buy,
            'signal_buy_blk': blk_buy, 'signal_buy_dl': False,
            'signal_buy_dz30': dz30_cond, 'signal_buy_scb': scb_sig,
            'signal_buy_blkB2': blkb2_buy,
            'signal_sell_b1': False, 'signal_sell_b2': False,
            'signal_sell_blk': False, 'signal_sell_dl': False,
            'signal_sell_dz30': False, 'signal_sell_scb': False,
            'signal_sell_blkB2': False,
            'score_s1': s1, 'signal_s1_full': s1_full,
            'signal_s1_half': s1_half,
            'signal_跌破多空线': broken, 'signal_止损': False,
            'is_observing': broken,
            'indicators': '{}',
        }
        return result
    except Exception as e:
        logger.error(f"process {code}: {e}")
        return None


def save_results(results: list[dict]) -> None:
    if not results:
        return
    conn = get_db()
    try:
        df = pd.DataFrame(results)
        date_val = results[0]['date']
        conn.execute("DELETE FROM daily_signals WHERE date = ?", [date_val])
        conn.execute("INSERT INTO daily_signals BY NAME SELECT * FROM df")
        logger.info(f"Saved {len(results)} signals to DB")
    except Exception as e:
        logger.error(f"Save failed: {e}")
        raise
    finally:
        conn.close()


def run(target_date: str | None = None, limit: int = 0, workers: int = 1) -> dict:
    trading_date = get_trading_date(target_date)
    stocks = get_stock_list()
    logger.info(f"Scanning {len(stocks)} stocks for {trading_date}")

    if limit > 0:
        stocks = stocks[:limit]
        logger.info(f"Limited to {limit} stocks")

    results = []
    for i, stock in enumerate(stocks):
        r = process_one_stock(stock, trading_date)
        if r:
            results.append(r)
        if (i + 1) % 500 == 0:
            logger.info(f"Progress: {i+1}/{len(stocks)}")

    save_results(results)

    stats = {
        f"signal_buy_{s}": sum(1 for r in results if r.get(f"signal_buy_{s}"))
        for s in ['b1', 'b2', 'blk', 'dl', 'dz30', 'scb', 'blkB2']
    }
    return {
        'date': trading_date, 'total_stocks': len(stocks),
        'success_count': len(results), 'fail_count': len(stocks) - len(results),
        'signal_stats': stats, 'duration': 0,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="全市场信号扫描 (单进程)")
    p.add_argument("--date", type=str, default=None, help="YYYYMMDD")
    p.add_argument("--limit", type=int, default=0, help="限制股票数 (测试用)")
    result = run(target_date=p.parse_args().date, limit=p.parse_args().limit)
    logger.info(f"Done: {result['success_count']} signals")
    return 0


if __name__ == "__main__":
    sys.exit(main())
