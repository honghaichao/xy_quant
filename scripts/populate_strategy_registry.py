"""Register all 7+1 strategies into strategy_registry table.

All strategy metadata from SilverM-quant-main's signals and strategy definitions.

Usage:
    .venv/bin/python scripts/populate_strategy_registry.py
    .venv/bin/python scripts/populate_strategy_registry.py --dry-run
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import json
import uuid

import duckdb

from config.settings import settings
from utils.logger import get_logger

logger = get_logger("populate_strategy_registry")

DB_PATH = str(Path(settings.duckdb_path))

# ── Strategy definitions ──────────────────────────────────────────
# Each entry maps to the original SilverM signal modules + strategy classes.
STRATEGIES: list[dict] = [
    {
        "id": "strategy_b1",
        "name": "天宫B1策略v1",
        "display_name": "B1 天宫买入",
        "class_path": "signals.signal_cal.B1_module",
        "source_file": "signals/signal_cal/B1_module.py",
        "description": (
            "基于 KDJ_J低 + MACD多头 + 趋势线条件 的买入信号。"
            "B1 是主力日线级买入策略，信号数量少但质量较高。"
        ),
        "version": "1.0.0",
        "author": "SilverM",
        "status": "active",
        "strategy_type": "buy",
        "threshold_required": True,
        "min_data_days": 120,
    },
    {
        "id": "strategy_b2",
        "name": "天宫B2策略v1",
        "display_name": "B2 天宫买入",
        "class_path": "signals.signal_cal.B2_module",
        "source_file": "signals/signal_cal/B2_module.py",
        "description": (
            "基于 MACD多头 + 趋势线条件 + B2阈值 的买入信号。"
            "B2 比 B1 更激进，信号数量更多。"
        ),
        "version": "1.0.0",
        "author": "SilverM",
        "status": "active",
        "strategy_type": "buy",
        "threshold_required": True,
        "min_data_days": 120,
    },
    {
        "id": "strategy_blk",
        "name": "暴力K策略v1",
        "display_name": "BLK 暴力K",
        "class_path": "signals.signal_cal.BLKB2_module",
        "source_file": "signals/signal_cal/BLKB2_module.py",
        "description": (
            "检测暴力K线 (大阳线+倍量柱+J拐头向上) 的强势突破信号。"
            "BLK 捕捉极端动量，适合追涨。"
        ),
        "version": "1.0.0",
        "author": "SilverM",
        "status": "active",
        "strategy_type": "buy",
        "threshold_required": True,
        "min_data_days": 60,
    },
    {
        "id": "strategy_blkb2",
        "name": "BLKB2组合策略v1",
        "display_name": "BLK+B2 组合",
        "class_path": "signals.signal_cal.BLKB2_module",
        "source_file": "signals/signal_cal/BLKB2_module.py",
        "description": (
            "暴力K确认 + B2 阈值共振策略。"
            "BLK 信号配合 B2 指标过滤，降低假突破。"
        ),
        "version": "1.0.0",
        "author": "SilverM",
        "status": "active",
        "strategy_type": "buy",
        "threshold_required": True,
        "min_data_days": 120,
    },
    {
        "id": "strategy_scb",
        "name": "沙尘暴策略v1",
        "display_name": "SCB 沙尘暴",
        "class_path": "signals.signal_cal.SCB_module",
        "source_file": "signals/signal_cal/SCB_module.py",
        "description": (
            "沙尘暴 (SCB) 组合策略：结合 DL 基本条件 + BLK 信号 + SCB 信号，"
            "多维度确认底部反转机会。"
        ),
        "version": "1.0.0",
        "author": "SilverM",
        "status": "active",
        "strategy_type": "buy",
        "threshold_required": True,
        "min_data_days": 120,
    },
    {
        "id": "strategy_dz30",
        "name": "单针30策略v1",
        "display_name": "DZ30 单针30",
        "class_path": "signals.signal_cal.DZ30_module",
        "source_file": "signals/signal_cal/DZ30_module.py",
        "description": (
            "单针探底+30日线支撑确认策略。"
            "基于倍量柱数组 + 前20日非阴 + 长短期KD确认。"
        ),
        "version": "1.0.0",
        "author": "SilverM",
        "status": "active",
        "strategy_type": "buy",
        "threshold_required": True,
        "min_data_days": 60,
    },
    {
        "id": "strategy_s1",
        "name": "S1卖出策略v1",
        "display_name": "S1 卖出信号",
        "class_path": "signals.signal_cal.S1_module",
        "source_file": "signals/signal_cal/S1_module.py",
        "description": (
            "S1 卖出策略：全量 S1_FULL 和半仓 S1_HALF 卖出信号。"
            "结合跌破多空线 + 止损信号，控制回撤风险。"
        ),
        "version": "1.0.0",
        "author": "SilverM",
        "status": "active",
        "strategy_type": "sell",
        "threshold_required": False,
        "min_data_days": 60,
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Populate strategy_registry table"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print strategies without writing"
    )
    return parser.parse_args()


def run(dry_run: bool = False) -> dict[str, int]:
    logger.info(f"Registering {len(STRATEGIES)} strategies")

    for s in STRATEGIES:
        logger.info(f"  {s['id']:20s} {s['name']:25s} [{s['strategy_type']}]")
        logger.info(f"    -> {s['class_path']}")

    if dry_run:
        logger.info("[DRY RUN] No data written.")
        return {"strategies": len(STRATEGIES)}

    conn = duckdb.connect(DB_PATH, read_only=False)
    try:
        inserted = 0
        updated = 0
        for s in STRATEGIES:
            # Check if exists
            existing = conn.execute(
                "SELECT id FROM strategy_registry WHERE id = ?", [s["id"]]
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE strategy_registry SET
                       name = ?, display_name = ?, class_path = ?, source_file = ?,
                       description = ?, version = ?, author = ?, status = ?,
                       strategy_type = ?, threshold_required = ?, min_data_days = ?,
                       updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    [
                        s["name"], s["display_name"], s["class_path"],
                        s["source_file"], s["description"], s["version"],
                        s["author"], s["status"], s["strategy_type"],
                        s["threshold_required"], s["min_data_days"], s["id"],
                    ],
                )
                updated += 1
            else:
                conn.execute(
                    """INSERT INTO strategy_registry
                       (id, name, display_name, class_path, source_file,
                        description, version, author, status, strategy_type,
                        threshold_required, min_data_days)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        s["id"], s["name"], s["display_name"], s["class_path"],
                        s["source_file"], s["description"], s["version"],
                        s["author"], s["status"], s["strategy_type"],
                        s["threshold_required"], s["min_data_days"],
                    ],
                )
                inserted += 1

        logger.info(f"Inserted {inserted}, updated {updated}")
    finally:
        conn.close()

    return {"inserted": inserted, "updated": updated, "total": len(STRATEGIES)}


def main() -> int:
    args = parse_args()
    try:
        result = run(dry_run=args.dry_run)
        logger.info(f"Done: {json.dumps(result)}")
        return 0
    except Exception:
        logger.exception("populate_strategy_registry failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
