"""因子注册表 — 参考 strategies/registry.py 的单例 + DB 模式。"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent
FACTOR_DIR = PROJECT_ROOT / "factor"

# ── DuckDB helper ──────────────────────────────────────────────────
_DB_PATH: Path | None = None


def _get_db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        from config.settings import settings

        _DB_PATH = Path(settings.duckdb_path)
    return _DB_PATH


def _db_connect(read_only: bool = False):
    import duckdb

    return duckdb.connect(str(_get_db_path()), read_only=read_only)


# ── Metadata ───────────────────────────────────────────────────────


@dataclass
class FactorMetadata:
    """Factor metadata stored in the registry."""

    name: str
    category: str = "technical"  # technical / fundamental / custom
    description: str = ""
    version: str = "1.0.0"


# ── Registry ───────────────────────────────────────────────────────


class FactorRegistry:
    """Singleton registry of all factors, backed by DuckDB."""

    _instance: FactorRegistry | None = None
    _initialized: bool = False

    @classmethod
    def clear(cls) -> None:
        if cls._instance is not None:
            cls._instance._metadata.clear()
            cls._instance._factors.clear()
        cls._initialized = False

    def __new__(cls) -> FactorRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if FactorRegistry._initialized:
            return
        self._metadata: dict[str, FactorMetadata] = {}
        self._factors: dict[str, Any] = {}
        self._load_from_db()
        FactorRegistry._initialized = True

    # ── DB ──────────────────────────────────────────────────────

    def _load_from_db(self) -> None:
        try:
            conn = _db_connect(read_only=True)
            try:
                rows = conn.execute(
                    "SELECT name, category, description FROM factor_registry "
                    "WHERE status = 'active' ORDER BY name"
                ).fetchall()
            finally:
                conn.close()
            for row in rows:
                self._metadata[row[0]] = FactorMetadata(
                    name=row[0], category=row[1] or "technical", description=row[2] or ""
                )
        except Exception:
            pass

    def _ensure_table(self) -> None:
        conn = _db_connect()
        try:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS factor_registry (
                    name        VARCHAR PRIMARY KEY,
                    category    VARCHAR DEFAULT 'technical',
                    description TEXT DEFAULT '',
                    version     VARCHAR DEFAULT '1.0.0',
                    status      VARCHAR DEFAULT 'active',
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )"""
            )
        finally:
            conn.close()

    # ── CRUD ────────────────────────────────────────────────────

    def register(self, name: str, category: str = "technical", description: str = "") -> None:
        self._ensure_table()
        self._metadata[name] = FactorMetadata(name=name, category=category, description=description)
        conn = _db_connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO factor_registry (name, category, description) "
                "VALUES (?, ?, ?)",
                [name, category, description],
            )
        finally:
            conn.close()

    def get(self, name: str) -> Any:
        if name in self._factors:
            return self._factors[name]
        return None

    def set_factor(self, name: str, factor: Any) -> None:
        self._factors[name] = factor

    def list(self, category: str | None = None) -> list[str]:
        names = list(self._metadata.keys())
        if category:
            names = [n for n, m in self._metadata.items() if m.category == category]
        return sorted(names)

    def get_metadata(self, name: str) -> FactorMetadata | None:
        return self._metadata.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._metadata

    def __len__(self) -> int:
        return len(self._metadata)

    def __iter__(self):
        return iter(self._metadata.keys())


# ── Decorator ──────────────────────────────────────────────────────


def register_factor(
    name: str,
    category: str = "technical",
    description: str = "",
):
    """Register a factor class/function in the runtime registry."""

    def decorator(fn):
        registry = FactorRegistry()
        registry.register(name, category, description)
        registry.set_factor(name, fn)
        return fn

    return decorator
