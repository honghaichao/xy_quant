#!/usr/bin/env python3
"""遗传算法因子挖掘 — 结合 Expression DSL 的自动 alpha 生成。

用法:
    # 快速运行 5 代，评估 Top 20
    .venv/bin/python scripts/run_factor_ga_mine.py --generations 5 --top 20 --dry-run

    # 正式运行：10 代，Top 50 个，产出入库
    .venv/bin/python scripts/run_factor_ga_mine.py --generations 10 --top 50

关联:
    - factor.expression: Expression DSL (因子公式描述)
    - factor.ga_miner:   GA 进化引擎 (变异/交叉/选择)
    - factor.registry:   因子注册表 (入库)
    - scripts/auto_factor_mine.py: 日常 IC 扫描 (互补, 不冲突)
"""

from __future__ import annotations

import argparse
import sys
import os
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import duckdb
import pandas as pd

from config.settings import settings
from utils.logger import get_logger

logger = get_logger("factor.ga_mine")

DB_PATH = str(settings.duckdb_path)


def _load_training_data(lookback_days: int = 60) -> tuple[pd.DataFrame, pd.Series]:
    """从 DuckDB 加载因子数据 + 前向收益作为训练集。"""
    end = date.today()
    start = end - timedelta(days=lookback_days + 10)

    conn = duckdb.connect(DB_PATH, read_only=True)
    try:
        # 最新一天的 factor_data（横截面）
        df = conn.execute(
            "SELECT * FROM factor_data WHERE date = (SELECT MAX(date) FROM factor_data)"
        ).fetchdf()
        if df.empty:
            raise RuntimeError("factor_data 为空，请先跑 factor_compute")

        # 前向收益：T+1 close pct
        ret_df = conn.execute(
            """SELECT ts_code, trade_date, close FROM daily_bar
               WHERE trade_date >= ? AND trade_date <= ?
               ORDER BY ts_code, trade_date""",
            [start.isoformat(), end.isoformat()],
        ).fetchdf()

    finally:
        conn.close()

    ret_df["code"] = ret_df["ts_code"].str[:6]

    # T+1 收益
    rets = []
    for _, g in ret_df.groupby("code"):
        g = g.sort_values("trade_date")
        closes = g["close"].values
        if len(closes) < 2:
            continue
        rets.append({"code": g.iloc[0]["code"], "ret_fwd": (closes[-1] - closes[0]) / closes[0]})

    fwd = pd.DataFrame(rets).set_index("code")["ret_fwd"]

    df = df.set_index("code")

    # 只保留纯数值列
    numeric_cols = [c for c in df.columns
                    if c not in ("date", "trade_date", "ts_code") and
                    pd.api.types.is_numeric_dtype(df[c])]
    df = df[numeric_cols].fillna(0)

    logger.info(f"训练数据: {len(df)} stocks x {len(df.columns)} cols, "
                f"forward rets: {len(fwd)}")

    return df, fwd


def main() -> int:
    p = argparse.ArgumentParser(description="GA Factor Mining")
    p.add_argument("--generations", type=int, default=10)
    p.add_argument("--population", type=int, default=30)
    p.add_argument("--top", type=int, default=20)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--lookback", type=int, default=60)
    args = p.parse_args()

    logger.info("加载训练数据...")
    try:
        factor_df, fwd_rets = _load_training_data(args.lookback)
    except RuntimeError as e:
        logger.error(str(e))
        return 1

    from factor.ga_miner import FactorMiner, Individual
    from factor.expression import FactorExpr

    logger.info(f"启动 GA: {args.generations} gens × {args.population} pop")
    miner = FactorMiner(factor_df, fwd_rets)
    pop = miner.evolve(
        generations=args.generations,
        population_size=args.population,
        elite_size=max(3, args.population // 6),
        verbose=True,
    )

    # Top N
    from factor.registry import FactorRegistry
    reg = FactorRegistry()
    existing = set(reg.list())

    new_count = 0
    for ind in pop[:args.top]:
        if ind.fitness is None or ind.fitness < 0.02:
            continue  # 跳过弱因子

        fe = FactorExpr(
            source=ind.source,
            name=ind.name or f"ga_{ind.source[:30]}",
            category="technical",
            description=f"GA auto-generated |IC|={ind.fitness:.4f}",
        )

        if fe.name in existing:
            continue

        if args.dry_run:
            print(f"  [DRY] {fe.name:30s} |IC|={ind.fitness:.4f}  {fe.source[:60]}")
        else:
            try:
                reg.register(fe.name, fe.category, fe.description or fe.source)
                reg.set_factor(fe.name, fe)
                new_count += 1
                logger.info(f"Registered: {fe.name}  |IC|={ind.fitness:.4f}")
            except Exception as e:
                logger.warning(f"注册失败 {fe.name}: {e}")

    if args.dry_run:
        print(f"\n  DRY RUN: {min(args.top, len(pop))} factors would be registered")
    else:
        print(f"\n  新增注册因子: {new_count}")
        print(f"  因子注册表: {len(reg)} total")

    return 0


if __name__ == "__main__":
    sys.exit(main())
