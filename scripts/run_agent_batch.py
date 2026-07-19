#!/usr/bin/env python3
"""Agent 批量分析脚本 — 对当天信号的股票逐一执行 Agent 流水线。

用法:
    # 分析当日 B2 策略信号的 Top 10 只股票
    .venv/bin/python scripts/run_agent_batch.py \
      --date 20260717 --strategy B2 --limit 10

    # 分析所有策略信号（不限数）
    .venv/bin/python scripts/run_agent_batch.py --date 20260717 --strategy all --limit 0

    # 预览（不真正调用 LLM，只检查数据可用性）
    .venv/bin/python scripts/run_agent_batch.py --date 20260717 --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    parser = argparse.ArgumentParser(description="Agent 批量分析")
    parser.add_argument("--date", required=True, help="交易日期 YYYYMMDD")
    parser.add_argument("--strategy", default="all", help="策略名称: B1/B2/BLK/BLKB2/SCB/DZ30/all")
    parser.add_argument("--limit", type=int, default=10, help="最大分析数量 (0=不限)")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不调用 LLM")
    parser.add_argument("--debug", action="store_true", help="打印每个 Agent 的输出")
    args = parser.parse_args()

    trade_date = args.date
    if len(trade_date) == 8:
        trade_date_fmt = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
    else:
        trade_date_fmt = trade_date.replace("-", "")
        trade_date_fmt = f"{trade_date_fmt[:4]}-{trade_date_fmt[4:6]}-{trade_date_fmt[6:]}"
        trade_date = trade_date.replace("-", "")

    print(f"\n{'='*60}")
    print(f"  Agent 批量分析 — {trade_date_fmt}  strategy={args.strategy}")
    if args.dry_run:
        print(f"  🧪 DRY RUN 模式 — 仅检查数据，不调用 LLM")
    print(f"{'='*60}\n")

    # ---- 获取当日信号股票列表 ----
    import duckdb
    from config.settings import settings

    conn = duckdb.connect(str(settings.duckdb_path), read_only=True)
    try:
        # daily_signals 表列是 signal_buy_b1, signal_buy_b2, ...
        strategy_col_map = {
            "B1": "signal_buy_b1", "B2": "signal_buy_b2",
            "BLK": "signal_buy_blk", "BLKB2": "signal_buy_blkB2",
            "DZ30": "signal_buy_dz30", "SCB": "signal_buy_scb",
        }
        if args.strategy == "all":
            conditions = " OR ".join(f"{col} = 1" for col in strategy_col_map.values())
        else:
            col = strategy_col_map.get(args.strategy.upper())
            if col is None:
                print(f"  未知策略: {args.strategy}，可选: {list(strategy_col_map)}")
                return 1
            conditions = f"{col} = 1"

        from datetime import date as ddate
        query_date = ddate(int(trade_date[:4]), int(trade_date[4:6]), int(trade_date[6:]))
        df = conn.execute(
            f"SELECT DISTINCT code FROM daily_signals WHERE date = ? AND ({conditions})",
            [query_date],
        ).fetchdf()
        codes = sorted(df["code"].tolist()) if len(df) > 0 else []

        print(f"  当日 {args.strategy} 信号: {len(codes)} 只股票")
        if args.limit > 0 and len(codes) > args.limit:
            codes = codes[: args.limit]
            print(f"  限制分析: {len(codes)} 只")
    finally:
        conn.close()

    if not codes:
        print("\n  ⚠️  没有符合条件的股票，退出。")
        return 0

    # ---- 预览模式 ----
    if args.dry_run:
        from agent.dataflows.stock_adapter import StockDataAdapter
        adapter = StockDataAdapter()
        ok, fail = 0, 0
        for code in codes:
            try:
                data = adapter.get_market_data(code, trade_date, trade_date)
                if data is not None and len(data) > 0:
                    last = data.iloc[-1]
                    print(f"  ✅ {code} {last.get('close','?')} 行数={len(data)}")
                    ok += 1
                else:
                    print(f"  ❌ {code} 行情数据为空")
                    fail += 1
            except Exception as e:
                print(f"  ❌ {code} 数据异常: {e}")
                fail += 1
        print(f"\n  总计: {ok} 可分析, {fail} 失败")
        return 0

    # ---- 真实分析 ----
    from agent.api.analyzer import analyze_stock, get_llm_adapter

    llm = get_llm_adapter()

    results = []
    total_start = time.time()
    for i, code in enumerate(codes, 1):
        print(f"\n  [{i}/{len(codes)}] 分析 {code} ...", end=" ", flush=True)
        t0 = time.time()
        try:
            result = analyze_stock(
                symbol=code,
                trade_date=trade_date_fmt,
                llm=llm,
                debug=args.debug,
                include_memory=False,
            )
            elapsed = time.time() - t0
            dec = result.get("final_decision", "N/A")
            sig = result.get("trading_signal", {}).get("action", "N/A")
            errs = len(result.get("errors", []))
            status = "✅" if result.get("success") else "❌"
            print(f"  {status} [{dec}] [{sig}] {elapsed:.1f}s errs={errs}")
            results.append(result)
        except Exception as e:
            elapsed = time.time() - t0
            print(f"  ❌ 异常: {e} ({elapsed:.1f}s)")
            results.append({"symbol": code, "success": False, "error": str(e)})

    total_elapsed = time.time() - total_start

    # ---- 汇总 ----
    success = sum(1 for r in results if r.get("success"))
    partial = sum(1 for r in results if r.get("partial", False))
    fail = len(results) - success

    print(f"\n{'='*60}")
    print(f"  完成: {len(results)} 只 | 成功={success} 失败={fail} | {total_elapsed:.0f}s")
    print(f"{'='*60}")

    # 按决策分布统计
    decisions: dict[str, int] = {}
    for r in results:
        dec = r.get("final_decision", "error")
        decisions[dec] = decisions.get(dec, 0) + 1
    if decisions:
        print("  决策分布:", ", ".join(f"{k}={v}" for k, v in decisions.items()))
        print()

    # 信号摘要
    buy_signals = [r for r in results
                   if r.get("trading_signal", {}).get("action") == "BUY"]
    if buy_signals:
        print(f"  🟢 买入信号 ({len(buy_signals)} 只):")
        for r in buy_signals:
            sig = r.get("trading_signal", {})
            print(f"     {r['symbol']:>8s}  "
                  f"entry={sig.get('entry_price',0):.2f}  "
                  f"stop={sig.get('stop_loss',0):.2f}  "
                  f"pos={sig.get('position_size',0)*100:.0f}%")

    return 0


if __name__ == "__main__":
    sys.exit(main())
