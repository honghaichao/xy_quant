"""
结果适配器 — 将 Agent 分析结果保存到 DuckDB。

注意: DuckDB 单写锁限制，每次操作独立 open/close 连接，避免长连接冲突。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any


TABLE_NAME = "agent_analysis_results"


class ResultAdapter:
    """分析结果持久化适配器。"""

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            from config.settings import settings
            self._db_path = str(settings.duckdb_path)
        else:
            self._db_path = db_path
        self._ensure_table()

    # ═══════════════════════════════════════════════════════════
    # 内部 helper
    # ═══════════════════════════════════════════════════════════

    def _get_db(self):
        """获取一个新的 DuckDB 连接（每次调用创建新连接）。"""
        import duckdb
        try:
            return duckdb.connect(self._db_path, read_only=False)
        except Exception as e:
            print(f"[ResultAdapter] 数据库连接失败: {e}")
            return None

    def _get_ro_db(self):
        """获取一个只读 DuckDB 连接。"""
        import duckdb
        try:
            return duckdb.connect(self._db_path, read_only=True)
        except Exception as e:
            print(f"[ResultAdapter] 数据库连接失败: {e}")
            return None

    def _ensure_table(self):
        """幂等建表。"""
        db = self._get_db()
        if db is None:
            return
        try:
            db.execute(f"""
                CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                    run_id     VARCHAR PRIMARY KEY,
                    symbol     VARCHAR,
                    trade_date VARCHAR,
                    result_json JSON,
                    created_at TIMESTAMP
                )
            """)
        except Exception as e:
            print(f"[ResultAdapter] 建表失败: {e}")
        finally:
            db.close()

    # ═══════════════════════════════════════════════════════════
    # CRUD
    # ═══════════════════════════════════════════════════════════

    def save_analysis_result(self, symbol: str, trade_date: str,
                             result: dict[str, Any]) -> str:
        """保存分析结果，返回 run_id。"""
        run_id = (
            f"ANA_{symbol}_"
            f"{datetime.now().strftime('%Y%m%d%H%M%S')}_"
            f"{uuid.uuid4().hex[:8]}"
        )
        db = self._get_db()
        if db is None:
            return run_id
        try:
            result_json = json.dumps(result, ensure_ascii=False, indent=2)
            db.execute(
                f"INSERT INTO {TABLE_NAME} (run_id, symbol, trade_date, result_json, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                [run_id, symbol, trade_date, result_json, datetime.now()],
            )
        except Exception as e:
            print(f"[ResultAdapter] 保存失败: {e}")
        finally:
            db.close()
        return run_id

    def load_analysis_result(self, run_id: str) -> dict[str, Any] | None:
        """加载单个分析结果。"""
        db = self._get_ro_db()
        if db is None:
            return None
        try:
            row = db.execute(
                f"SELECT result_json FROM {TABLE_NAME} WHERE run_id = ?",
                [run_id],
            ).fetchone()
            if row:
                return json.loads(row[0])
        except Exception as e:
            print(f"[ResultAdapter] 加载失败: {e}")
        finally:
            db.close()
        return None

    def get_analysis_history(
        self,
        symbol: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        offset: int = 0,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """分页获取历史分析记录。"""
        db = self._get_ro_db()
        if db is None:
            return []
        try:
            conditions: list[str] = []
            params: list[Any] = []

            if symbol:
                conditions.append("symbol = ?")
                params.append(symbol)
            if start_date:
                conditions.append("created_at >= ?")
                params.append(start_date)
            if end_date:
                conditions.append("created_at <= ?")
                params.append(end_date)

            where = " AND ".join(conditions) if conditions else "1=1"
            params.extend([limit, offset])

            df = db.execute(
                f"SELECT run_id, symbol, trade_date, created_at, result_json "
                f"FROM {TABLE_NAME} WHERE {where} "
                "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params,
            ).fetchdf()

            results: list[dict[str, Any]] = []
            for _, row in df.iterrows():
                try:
                    data = json.loads(row["result_json"])
                except Exception:
                    data = {}
                results.append({
                    "run_id":     row["run_id"],
                    "symbol":     row["symbol"],
                    "trade_date": str(row["trade_date"]),
                    "created_at": str(row["created_at"]),
                    "result":     data,
                })
            return results
        except Exception as e:
            print(f"[ResultAdapter] 历史查询失败: {e}")
            return []
        finally:
            db.close()

    def delete_analysis_result(self, run_id: str) -> bool:
        """删除一个分析结果。"""
        db = self._get_db()
        if db is None:
            return False
        try:
            db.execute(f"DELETE FROM {TABLE_NAME} WHERE run_id = ?", [run_id])
            return True
        except Exception as e:
            print(f"[ResultAdapter] 删除失败: {e}")
            return False
        finally:
            db.close()

    def get_latest_for_symbol(self, symbol: str) -> dict[str, Any] | None:
        """获取某只股票的最新分析结果。"""
        db = self._get_ro_db()
        if db is None:
            return None
        try:
            row = db.execute(
                f"SELECT result_json FROM {TABLE_NAME} "
                "WHERE symbol = ? ORDER BY created_at DESC LIMIT 1",
                [symbol],
            ).fetchone()
            if row:
                return json.loads(row[0])
        except Exception as e:
            print(f"[ResultAdapter] 最新查询失败: {e}")
        finally:
            db.close()
        return None


def get_result_adapter(db_path: str | None = None) -> ResultAdapter:
    """工厂函数。"""
    return ResultAdapter(db_path)
