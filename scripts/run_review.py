"""复盘脚本入口。"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date

from review.main import run_daily_review
from utils.logger import get_logger

logger = get_logger("run_review")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run retrospective review collection.")
    parser.add_argument(
        "--trade-date",
        dest="trade_date",
        type=_parse_date,
        help="指定复盘日期,默认使用市场库最新交易日",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run review entrypoint."""
    args = parse_args(argv)
    output_path = run_daily_review(trade_date=args.trade_date)
    logger.info("Review collection finished: %s", output_path)
    return 0


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


if __name__ == "__main__":
    raise SystemExit(main())
