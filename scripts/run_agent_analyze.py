#!/usr/bin/env python3
"""实盘 Agent 批量分析入口 — 被调度器 cron 调用。

由 scheduler_jobs.yaml 的 agent_analyze 调度任务触发：
  周一~五 23:15（jq_live 完成后）

对当天信号中 Top3 策略的股票执行 Agent 分析。
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 确保 .env 加载
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def main():
    parser = argparse.ArgumentParser(description="Agent 分析调度入口")
    parser.add_argument("--date", help="交易日期 YYYYMMDD，默认今天")
    parser.add_argument("--limit", type=int, default=5, help="最大分析数量 (default=5)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from config.settings import settings
    from utils.logger import get_logger
    from utils.db import connect_write
    import duckdb

    logger = get_logger("agent.analyze")

    # 日期
    if args.date:
        trade_date = args.date
    else:
        trade_date = datetime.now().strftime("%Y%m%d")
    trade_date_fmt = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"

    logger.info(f"Agent 批量分析开始: {trade_date_fmt} limit={args.limit}")

    # 获取当天有信号的股票（优先当前有效的策略）
    conn = duckdb.connect(str(settings.duckdb_path), read_only=True)
    try:
        # 优先 B2/BLKB2/DZ30 的信号
        from datetime import date as ddate
        query_date = ddate(int(trade_date[:4]), int(trade_date[4:6]), int(trade_date[6:]))
        df = conn.execute("""
            SELECT DISTINCT code FROM daily_signals
            WHERE date = ? AND (signal_buy_b2 = 1 OR signal_buy_blkB2 = 1 OR signal_buy_dz30 = 1)
        """, [query_date]).fetchdf()

        if len(df) == 0:
            df = conn.execute("""
                SELECT DISTINCT code FROM daily_signals
                WHERE date = ? AND (signal_buy_b1 = 1 OR signal_buy_blk = 1 OR signal_buy_scb = 1
                    OR signal_buy_b2 = 1 OR signal_buy_blkB2 = 1 OR signal_buy_dz30 = 1)
            """, [query_date]).fetchdf()

        codes = sorted(set(df["code"].tolist())) if len(df) > 0 else []
    finally:
        conn.close()

    if not codes:
        logger.info("当日无信号，跳过 Agent 分析")
        return 0

    # 限制数量
    if args.limit > 0 and len(codes) > args.limit:
        codes = codes[: args.limit]

    if args.dry_run:
        logger.info(f"DRY RUN: 将分析 {len(codes)} 只: {codes}")
        return 0

    # 执行分析
    from agent.api.analyzer import analyze_stock, get_llm_adapter

    llm = get_llm_adapter()
    success = 0
    for i, code in enumerate(codes, 1):
        logger.info(f"  [{i}/{len(codes)}] 分析 {code}")
        try:
            result = analyze_stock(
                symbol=code,
                trade_date=trade_date_fmt,
                llm=llm,
                include_memory=False,
                debug=False,
            )
            if result.get("success"):
                success += 1
                logger.info(f"    {code}: {result.get('final_decision', 'N/A')} "
                            f"signal={result.get('trading_signal', {}).get('action', 'N/A')}")
            else:
                logger.warning(f"    {code}: 失败 — {result.get('error', 'unknown')[:100]}")
        except Exception as e:
            logger.error(f"    {code}: 异常 — {e}")

    logger.info(f"Agent 分析完成: {success}/{len(codes)} 成功")
    return 0


if __name__ == "__main__":
    sys.exit(main())
