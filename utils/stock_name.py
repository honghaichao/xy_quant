"""Shared stock-name lookup from PostgreSQL stock_basic.

Usage:
    from utils.stock_name import load_name_map, resolve_name

    name_map = load_name_map()
    name = resolve_name("000001", name_map)  # → "平安银行"
"""

from __future__ import annotations

_cache: dict[str, str] | None = None


def load_name_map() -> dict[str, str]:
    """Load ts_code→name from PG, stripping suffix; cached in memory."""
    global _cache
    if _cache is not None:
        return _cache
    try:
        import psycopg
        from config.settings import settings

        pg = psycopg.connect(settings.pg_dsn)
        rows = pg.execute("SELECT ts_code, name FROM stock_basic").fetchall()
        pg.close()
        _cache = {r[0].split(".")[0]: r[1] for r in rows}
    except Exception:
        _cache = {}
    return _cache


def resolve_name(code: str, name_map: dict[str, str] | None = None, *,
                 fallback: str | None = None) -> str:
    """Return stock name for code; falls back to code if unknown."""
    if name_map is None:
        name_map = load_name_map()
    code = str(code)
    result = name_map.get(code, fallback or code)
    return result if result else code
