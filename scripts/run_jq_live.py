#!/usr/bin/env python3
"""
JQ 实盘引擎夜间入口 — 结算 + 预演。

用法：
    .venv/bin/python scripts/run_jq_live.py                       # 全部 enabled 策略
    .venv/bin/python scripts/run_jq_live.py --strategy caimadama  # 指定策略
    .venv/bin/python scripts/run_jq_live.py --dry-run             # 只预览不写库
    .venv/bin/python scripts/run_jq_live.py --settle-only         # 只结算不预演
    .venv/bin/python scripts/run_jq_live.py --date 20260717       # 指定数据截至日
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import get_trading_config
from utils.logger import get_logger

logger = get_logger("run_jq_live")


def run(strategy_id: str | None = None, asof: date | None = None,
        dry_run: bool = False, settle_only: bool = False,
        preview_only: bool = False) -> dict:
    """跑一个或全部 enabled 的 JQ 实盘策略。"""
    from engine.live_engine import LiveEngine

    cfg = get_trading_config()
    results = {}
    for sc in cfg.live.strategies:
        if not sc.enabled:
            continue
        if strategy_id and sc.id != strategy_id:
            continue
        eng = LiveEngine(
            strategy_id=sc.id,
            module=sc.module,
            mode=sc.mode,
            initial_cash=sc.initial_cash,
            write_positions=cfg.live.write_positions_table,
            fill_fallback=cfg.live.fill_fallback,
        )
        try:
            results[sc.id] = eng.run_nightly(
                asof=asof, dry_run=dry_run,
                settle_only=settle_only, preview_only=preview_only,
            )
        except Exception as exc:
            logger.exception(f"策略 {sc.id} nightly 失败")
            results[sc.id] = {"error": str(exc)}
    if not results:
        logger.warning("无 enabled 的 JQ 实盘策略（config/settings.yaml trading.live.strategies）")
    return results


def run_job(**kwargs: object) -> dict:
    """APScheduler 入口（23:05 jq_live job）。"""
    return run()


def main() -> int:
    parser = argparse.ArgumentParser(description="JQ 实盘引擎夜间结算+预演")
    parser.add_argument("--strategy", type=str, default=None, help="只跑指定策略 id")
    parser.add_argument("--date", type=str, default=None, help="数据截至日 YYYYMMDD（默认自动）")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不写库不推送")
    parser.add_argument("--settle-only", action="store_true", help="只结算，不做次日预演")
    parser.add_argument("--preview-only", action="store_true", help="只预演，不结算")
    args = parser.parse_args()

    asof = datetime.strptime(args.date, "%Y%m%d").date() if args.date else None
    results = run(strategy_id=args.strategy, asof=asof, dry_run=args.dry_run,
                  settle_only=args.settle_only, preview_only=args.preview_only)
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    return 0 if results and all("error" not in r for r in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
