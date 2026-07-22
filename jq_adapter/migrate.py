#!/usr/bin/env python3
# coding=utf-8
"""
migrate.py — 聚宽策略迁移工具
================================
将聚宽（JoinQuant）原始策略文件转换为 jq_adapter 兼容的本地策略。

用法：
    python -m jq_adapter.migrate 原始策略.py -o 迁移后策略.py
    python -m jq_adapter.migrate 原始策略.py -o 迁移后策略.py -r

自动转换：
    def initialize(context):        → class XxxStrategy(JQStrategy):
                                         def initialize(self, context):
    g.xxx                           → self.g.xxx
    context.portfolio.positions[X]  → self.get_position(X)
    attribute_history(...)          → self.history(...)
    order(...)                      → self.order(...)
"""

import argparse
import os
import re
import sys
from pathlib import Path

# ---- Rules: (pattern, replacement, description) ----
REPLACEMENT_RULES: list[tuple[str, str, str]] = [
    # Function → class method
    (r"^def initialize\(context\):",
     r"def initialize(self, context):",
     "initialize → self method"),

    (r"^def handle_data\(context,\s*data\):",
     r"def handle_data(self, context, data):",
     "handle_data → self method"),

    (r"^def before_trading_start\(context\):",
     r"def before_trading_start(self, context):",
     "before_trading_start → self method"),

    (r"^def after_trading_end\(context\):",
     r"def after_trading_end(self, context):",
     "after_trading_end → self method"),

    # g → self.g
    (r"(?<!\wself\.)(?<!\w)\.g\.", r"self.g.", "g.xxx → self.g.xxx"),
    (r"\bg\.(\w+)", r"self.g.\1", "g.xxx → self.g.xxx"),

    # context.portfolio.positions[xxx] → self.get_position(xxx)
    (r"context\.portfolio\.positions\[([^\]]+)\]\.amount",
     r"self.get_position(\1)[\"amount\"]",
     "context.portfolio.positions[X].amount → self.get_position(X)['amount']"),
    (r"context\.portfolio\.positions\[([^\]]+)\]\.\b",
     r"self.get_position(\1)[\"",
     "context.portfolio.positions[X].attr → self.get_position(X)['attr']"),

    # attribute_history → self.history
    (r"attribute_history\(([^,]+),\s*([^,]+),",
     r"self.history(\2,",
     "attribute_history(X, count, ...) → self.history(count, ...)"),

    # order → self.order
    (r"(?<!\wself\.)(?<!\w)order\(", r"self.order(", "order() → self.order()"),
    (r"(?<!\wself\.)(?<!\w)order_target\(", r"self.order_target(", "order_target() → self.order_target()"),
    (r"(?<!\wself\.)(?<!\w)order_value\(", r"self.order_value(", "order_value() → self.order_value()"),
    (r"(?<!\wself\.)(?<!\w)order_target_value\(", r"self.order_target_value(", "order_target_value() → self.order_target_value()"),

    # log → self.log
    (r"(?<!\wself\.)(?<!\w)log\.(?!\w*\.)", r"self.log", "log.info() → 保留"),
]


def _guess_strategy_name(filepath: str) -> str:
    """Guess strategy class name from file name."""
    base = Path(filepath).stem
    # CamelCase from snake_case or kebab-case
    parts = re.split(r"[-_\s]+", base)
    return "".join(p.capitalize() for p in parts) + "Strategy"


def migrate_source(source: str, strategy_name: str) -> str:
    """Apply all migration rules to source code."""
    result = source
    for pattern, replacement, desc in REPLACEMENT_RULES:
        new = re.sub(pattern, replacement, result, flags=re.MULTILINE)
        if new != result:
            print(f"  [migrate] {desc}")
            result = new
    return result


def wrap_in_class(source: str, strategy_name: str) -> str:
    """Wrap top-level functions into a JQStrategy class."""
    header = f'''# coding=utf-8
"""
迁移后的聚宽策略 — 由 jq_adapter.migrate 自动生成。
在 xy_quant + jq_adapter 环境本地运行。
"""
from jq_adapter import JQStrategy, Backtester, run_daily, run_weekly, run_monthly


class {strategy_name}(JQStrategy):
'''

    # Indent all lines by 4 spaces
    lines = source.split("\n")
    indented = "\n".join("    " + line if line.strip() else "" for line in lines)

    # Remove leading whitespace lines
    indented = indented.strip()

    return header + indented + "\n"


def add_runner_code(source: str, strategy_name: str, stock: str,
                    start_date: str, end_date: str, initial_cash: float) -> str:
    """Append Backtester runner code at the end."""
    runner = f'''

# ================================================================
# 自动生成的回测运行代码
# ================================================================
if __name__ == "__main__":
    bt = Backtester(
        strategy={strategy_name},
        stock="{stock}",
        start_date="{start_date}",
        end_date="{end_date}",
        initial_cash={initial_cash:.0f},
    )
    bt.run()
'''
    return source + runner


def migrate_file(
    input_path: str,
    output_path: str,
    add_runner: bool = False,
    stock: str = "000001.SZ",
    start_date: str = "20260101",
    end_date: str = "20260716",
    initial_cash: float = 1000000.0,
) -> None:
    """Migrate a single file."""
    with open(input_path, "r", encoding="utf-8") as f:
        source = f.read()

    strategy_name = _guess_strategy_name(input_path)
    print(f"[migrate] 输入: {input_path}")
    print(f"[migrate] 策略类名: {strategy_name}")
    print(f"[migrate] 开始转换...")

    # Step 1: Apply pattern replacements
    migrated = migrate_source(source, strategy_name)

    # Step 2: Wrap in class
    full_source = wrap_in_class(migrated, strategy_name)

    # Step 3: Add runner code
    if add_runner:
        full_source = add_runner_code(full_source, strategy_name, stock,
                                      start_date, end_date, initial_cash)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(full_source)

    print(f"[migrate] 输出: {output_path}")
    print(f"[migrate] 迁移完成 ✓")


# ================================================================
# CLI
# ================================================================
def main():
    parser = argparse.ArgumentParser(
        description="聚宽策略迁移工具 — 将聚宽策略转为 jq_adapter 可运行的本地策略",
    )
    parser.add_argument("input", help="输入的聚宽策略 .py 文件")
    parser.add_argument("-o", "--output", required=True, help="输出文件路径")
    parser.add_argument("-r", "--add-runner", action="store_true",
                        help="自动添加 Backtester 运行代码")
    parser.add_argument("--stock", default="000001.SZ", help="回测股票代码（默认 000001.SZ）")
    parser.add_argument("--start-date", default="20260101", help="回测起始日期")
    parser.add_argument("--end-date", default="20260716", help="回测结束日期")
    parser.add_argument("--initial-cash", type=float, default=1000000.0, help="初始资金")

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"错误: 输入文件不存在: {args.input}")
        sys.exit(1)

    migrate_file(
        input_path=args.input,
        output_path=args.output,
        add_runner=args.add_runner,
        stock=args.stock,
        start_date=args.start_date,
        end_date=args.end_date,
        initial_cash=args.initial_cash,
    )


if __name__ == "__main__":
    main()
