# ruff: noqa: E402
"""数据库初始化脚本入口。"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
from argparse import Namespace

from data.bootstrap.schema_initializer import SchemaInitializer
from data.storage.factory import get_market_store, get_meta_store
from utils.logger import get_logger

logger = get_logger("init_db")


def parse_args(argv: list[str] | None = None) -> Namespace:
    """Parse CLI arguments for database initialization."""
    parser = argparse.ArgumentParser(description="Initialize market and metadata storage schemas.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Initialize market and metadata storage schemas."""
    parse_args(argv)
    initializer = SchemaInitializer(
        market_store=get_market_store("duckdb"),
        meta_store=get_meta_store("postgres"),
    )
    logger.info("Initializing database schemas.")
    initializer.run()
    logger.info("Database initialization complete.")


if __name__ == "__main__":
    main()
