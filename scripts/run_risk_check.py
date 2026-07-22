"""Daily risk check script entrypoint.

Usage:
    .venv/bin/python scripts/run_risk_check.py --date 20260714
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
from datetime import date, datetime

from risk.monitor import RiskMonitor
from utils.logger import get_logger

logger = get_logger("run_risk_check")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Daily risk check")
    p.add_argument("--date", type=str, default=None, help="Target date YYYYMMDD")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    trade_date = (
        datetime.strptime(args.date, "%Y%m%d").date() if args.date else date.today()
    )

    monitor = RiskMonitor()
    try:
        report = monitor.check_daily(trade_date)
        print(f"\n=== Risk Report: {trade_date} ===")
        print(f"Total Capital: {report.get('total_capital', 0):,.0f}")
        print(f"Positions: {report.get('position_count', 0)}")
        print(f"VaR 95%: {report.get('vaR_95', 'N/A')}")
        print(f"CVaR 95%: {report.get('cvaR_95', 'N/A')}")

        violations = report.get("violations", [])
        if violations:
            print(f"\n⚠️  {len(violations)} Violations:")
            for v in violations:
                print(f"  - {v}")

        stops = report.get("stop_loss_triggers", [])
        if stops:
            print(f"\n🛑 {len(stops)} Stop Loss Triggers:")
            for s in stops:
                print(f"  - {s['code']}: {s['reason']}")

        takes = report.get("take_profit_triggers", [])
        if takes:
            print(f"\n💰 {len(takes)} Take Profit Triggers:")
            for t in takes:
                print(f"  - {t['code']}: {t['reason']}")

        if not violations and not stops and not takes:
            print("\n✅ All within limits")

        return 0
    except Exception:
        logger.exception("run_risk_check failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
