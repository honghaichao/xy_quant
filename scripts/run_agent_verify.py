#!/usr/bin/env python3
"""Agent 端到端验证脚本 — 对单只股票跑完整 Agent 分析流水线。

用法:
    .venv/bin/python scripts/run_agent_verify.py --symbol 600519 --date 20260717
    .venv/bin/python scripts/run_agent_verify.py --symbol 600000 --date 20260717 --debug
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    parser = argparse.ArgumentParser(description="Agent 端到端验证")
    parser.add_argument("--symbol", required=True, help="股票代码，如 600519")
    parser.add_argument("--date", required=True, help="交易日期 YYYYMMDD 或 YYYY-MM-DD")
    parser.add_argument("--debug", action="store_true", help="开启调试输出")
    args = parser.parse_args()

    # 标准化日期
    trade_date = args.date.replace("-", "") if "-" in args.date else args.date
    trade_date_fmt = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"

    print(f"\n{'='*60}")
    print(f"  Agent 端到端验证 — {args.symbol} @ {trade_date_fmt}")
    print(f"{'='*60}\n")

    # 1) 数据检查
    print("[1/4] 检查数据...")
    from agent.dataflows.stock_adapter import StockDataAdapter
    adapter = StockDataAdapter()

    t0 = time.time()
    price_data = adapter.get_market_data(args.symbol, trade_date, trade_date)
    data_latency = time.time() - t0
    if price_data is None or len(price_data) == 0:
        print(f"  ❌ 行情数据为空！请确认 {args.symbol} 在 {trade_date_fmt} 有日线数据")
        return 1
    print(f"  ✅ 行情: {len(price_data)} 行 K 线 ({data_latency:.1f}s)")
    last = price_data.iloc[-1]
    print(f"     最后一条: {last.get('date','?')} close={last.get('close','?')}")

    # 基本面
    try:
        fundamentals = adapter.get_fundamentals(args.symbol)
        pe = fundamentals.get("valuation", {}).get("pe_ttm", "N/A")
        print(f"  ✅ 基本面: PE_TTM={pe}")
    except Exception as e:
        print(f"  ⚠️  基本面获取失败: {e}")

    # 新闻
    try:
        from agent.dataflows.news.aggregator import NewsAggregator
        agg = NewsAggregator()
        news = agg.get_stock_news(args.symbol, limit=10)
        count = len(news.news_list) if hasattr(news, "news_list") else 0
        print(f"  ✅ 新闻: {count} 条")
    except Exception as e:
        print(f"  ⚠️  新闻获取失败: {e}")

    # 2) LLM 检查
    print("\n[2/4] 检查 LLM 连接...")
    t0 = time.time()
    from agent.api.analyzer import get_llm_adapter
    llm = get_llm_adapter()
    llm_latency = time.time() - t0
    has_key = getattr(llm, "api_key", None) is not None
    if has_key:
        print(f"  ✅ DeepSeek 就绪 ({llm_latency:.1f}s)")
    else:
        print(f"  ⚠️  LLM 降级模式 — 分析将返回占位文本")
        print(f"     检查 DEEPSEEK_API_KEY 环境变量是否设置")
        # 降级模式不阻断，继续跑

    # 3) 执行 Agent 分析
    print(f"\n[3/4] 执行 Agent 分析流水线...")
    print(f"  3 分析师(市场/新闻/基本面) → 牛熊辩论 → 研究经理 → 风控 → 交易信号")

    t0 = time.time()
    from agent.api.analyzer import analyze_stock

    result = analyze_stock(
        symbol=args.symbol,
        trade_date=trade_date_fmt,
        include_memory=False,
        llm=llm,
        debug=args.debug,
    )
    elapsed = time.time() - t0

    # 4) 打印结果
    print(f"\n[4/4] 分析完成 ({elapsed:.1f}s)\n")
    print(f"{'─'*60}")
    print(f"  股票:     {result.get('symbol')}")
    print(f"  日期:     {result.get('trade_date')}")
    print(f"  Run ID:   {result.get('run_id')}")
    print(f"  Success:  {result.get('success')}")
    print(f"  Partial:  {result.get('partial', False)}")
    print(f"  决策:     {result.get('final_decision', 'N/A')}")
    print(f"  置信度:   {result.get('confidence', 'N/A')}")
    trading_sig = result.get("trading_signal", {})
    print(f"  交易信号: {trading_sig.get('action', 'N/A')} "
          f"stop_loss={trading_sig.get('stop_loss', 'N/A')} "
          f"position={trading_sig.get('position_size', 'N/A')}")
    print(f"  错误数:   {len(result.get('errors', []))}")

    # 报告摘要
    reports = result.get("reports", {})
    if reports:
        print(f"\n  分析报告:")
        for key, text in reports.items():
            preview = text[:120].replace("\n", " ") if isinstance(text, str) else str(text)[:120]
            print(f"    [{key}] {preview}...")

    # 研究结果
    research = result.get("research", {})
    if research:
        print(f"\n  研究结论: {research.get('recommendation', 'N/A')} "
              f"(confidence={research.get('confidence', 'N/A')})")

    # 风控
    risk = result.get("risk", {})
    if risk:
        print(f"  风控:     level={risk.get('risk_level', 'N/A')} "
              f"score={risk.get('risk_score', 'N/A')}")

    # 错误详情
    errors = result.get("errors", [])
    if errors:
        print(f"\n  ⚠️  产生 {len(errors)} 个错误:")
        for e in errors:
            print(f"    - {e}")

    # 最终判断
    print(f"\n{'─'*60}")
    if result.get("success") and result.get("run_id"):
        print(f"  ✅ 验证通过 — Agent 分析完整跑通！")
        print(f"  Run ID: {result['run_id']}")
    elif result.get("partial"):
        print(f"  🟡 部分通过 — 有几处降级但不影响主流程")
    else:
        print(f"  ❌ 验证失败 — 请检查上述错误")
    print(f"{'─'*60}\n")

    return 0 if result.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
