"""DuckDB 连接工具。写锁被占用时等待重试，避免与回测/扫描进程冲突直接失败。"""

from __future__ import annotations

import time

import duckdb

from utils.logger import get_logger

logger = get_logger("utils.db")


def connect_write(
    db_path: str,
    retries: int = 30,
    wait_seconds: float = 10.0,
) -> duckdb.DuckDBPyConnection:
    """获取 DuckDB 写连接。

    DuckDB 同时只允许 1 个写进程。若写锁被其他进程（回测/扫描）占用，
    每 ``wait_seconds`` 秒重试一次，最多 ``retries`` 次（默认约 5 分钟），
    超时后抛出原始 IOException 交由上层（调度器）处理。
    """
    last_exc: duckdb.IOException | None = None
    for attempt in range(1, retries + 1):
        try:
            return duckdb.connect(db_path, read_only=False)
        except duckdb.IOException as exc:
            if "lock" not in str(exc).lower():
                raise
            last_exc = exc
            logger.warning(
                f"DuckDB 写锁被占用，{wait_seconds:.0f}s 后重试 ({attempt}/{retries})"
            )
            time.sleep(wait_seconds)
    assert last_exc is not None
    raise last_exc
