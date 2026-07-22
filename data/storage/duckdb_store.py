"""DuckDB market storage implementation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from numbers import Integral
from pathlib import Path
from typing import Any, Final
import re

import duckdb
import pandas as pd
from duckdb import DuckDBPyConnection

from config.settings import settings
from interfaces.market_store import IMarketStore
from utils.exception import StorageError
from utils.logger import get_logger

logger = get_logger("duckdb_store")

DUCKDB_SCHEMA_SQL: Final[tuple[str, ...]] = (
    """
    CREATE TABLE IF NOT EXISTS daily_bar (
        ts_code        VARCHAR  NOT NULL,
        trade_date     DATE     NOT NULL,
        open           DOUBLE,
        high           DOUBLE,
        low            DOUBLE,
        close          DOUBLE,
        pre_close      DOUBLE,
        change         DOUBLE,
        pct_chg        DOUBLE,
        vol            DOUBLE,
        amount         DOUBLE,
        updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ts_code, trade_date)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_daily_bar_date ON daily_bar(trade_date)",
    """
    CREATE TABLE IF NOT EXISTS adj_factor (
        ts_code     VARCHAR NOT NULL,
        trade_date  DATE    NOT NULL,
        adj_factor  DOUBLE  NOT NULL,
        updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ts_code, trade_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS daily_basic (
        ts_code            VARCHAR NOT NULL,
        trade_date         DATE    NOT NULL,
        close              DOUBLE,
        turnover_rate      DOUBLE,
        turnover_rate_f    DOUBLE,
        volume_ratio       DOUBLE,
        pe                 DOUBLE,
        pe_ttm             DOUBLE,
        pb                 DOUBLE,
        ps                 DOUBLE,
        ps_ttm             DOUBLE,
        dv_ratio           DOUBLE,
        dv_ttm             DOUBLE,
        total_share        DOUBLE,
        float_share        DOUBLE,
        free_share         DOUBLE,
        total_mv           DOUBLE,
        circ_mv            DOUBLE,
        updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ts_code, trade_date)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_daily_basic_date ON daily_basic(trade_date)",
    """
    CREATE TABLE IF NOT EXISTS index_daily (
        ts_code     VARCHAR NOT NULL,
        trade_date  DATE    NOT NULL,
        open        DOUBLE,
        high        DOUBLE,
        low         DOUBLE,
        close       DOUBLE,
        pre_close   DOUBLE,
        change      DOUBLE,
        pct_chg     DOUBLE,
        vol         DOUBLE,
        amount      DOUBLE,
        updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ts_code, trade_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS limit_list (
        trade_date     DATE    NOT NULL,
        ts_code        VARCHAR NOT NULL,
        name           VARCHAR,
        close          DOUBLE,
        pct_chg        DOUBLE,
        amount         DOUBLE,
        limit_amount   DOUBLE,
        float_mv       DOUBLE,
        total_mv       DOUBLE,
        turnover_ratio DOUBLE,
        fd_amount      DOUBLE,
        first_time     VARCHAR,
        last_time      VARCHAR,
        open_times     INTEGER,
        up_stat        VARCHAR,
        limit_times    INTEGER,
        "limit"       VARCHAR,
        updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (trade_date, ts_code)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_limit_list_date ON limit_list(trade_date)",
    # ── Intraday tables ────────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS intraday_spot (
        fetch_time   TIMESTAMP NOT NULL,
        ts_code      VARCHAR NOT NULL,
        name         VARCHAR,
        close        DOUBLE,
        pct_chg      DOUBLE,
        volume       DOUBLE,
        amount       DOUBLE,
        turnover_rate DOUBLE,
        pe           DOUBLE,
        pb           DOUBLE,
        high         DOUBLE,
        low          DOUBLE,
        open         DOUBLE,
        pre_close    DOUBLE,
        PRIMARY KEY (ts_code, fetch_time)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_intraday_spot_time ON intraday_spot(fetch_time)",
    """CREATE TABLE IF NOT EXISTS intraday_fund_flow (
        fetch_time   TIMESTAMP NOT NULL,
        ts_code      VARCHAR NOT NULL,
        name         VARCHAR,
        close        DOUBLE,
        pct_chg      DOUBLE,
        main_inflow  DOUBLE,
        main_inflow_pct DOUBLE,
        super_inflow DOUBLE,
        big_inflow   DOUBLE,
        mid_inflow   DOUBLE,
        small_inflow DOUBLE,
        PRIMARY KEY (ts_code, fetch_time)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_intraday_flow_time ON intraday_fund_flow(fetch_time)",
    """CREATE TABLE IF NOT EXISTS intraday_sector_flow (
        fetch_time    TIMESTAMP NOT NULL,
        sector_name   VARCHAR NOT NULL,
        sector_type   VARCHAR NOT NULL,
        trade_date    DATE NOT NULL,
        pct_chg       DOUBLE,
        main_inflow   DOUBLE,
        main_inflow_pct DOUBLE,
        super_inflow  DOUBLE,
        big_inflow    DOUBLE,
        mid_inflow    DOUBLE,
        small_inflow  DOUBLE,
        top_stock     VARCHAR,
        sector_code   VARCHAR,
        PRIMARY KEY (sector_name, sector_type, trade_date, fetch_time)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_intraday_sector_time ON intraday_sector_flow(fetch_time)",
    # ── Factor tables ────────────────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS factor_data (
        date             DATE    NOT NULL,
        code             VARCHAR NOT NULL,
        -- 估值因子
        pe_ttm           DOUBLE,
        pb               DOUBLE,
        ps_ttm           DOUBLE,
        pcf_ttm          DOUBLE,
        dividend_yield   DOUBLE,
        -- 质量因子
        roe              DOUBLE,
        roa              DOUBLE,
        gross_margin     DOUBLE,
        net_margin       DOUBLE,
        debt_to_asset    DOUBLE,
        -- 成长因子
        revenue_growth_yoy  DOUBLE,
        profit_growth_yoy   DOUBLE,
        -- 技术因子
        macd_dif         DOUBLE,
        macd_dea         DOUBLE,
        macd_histogram   DOUBLE,
        kdj_k            DOUBLE,
        kdj_d            DOUBLE,
        kdj_j            DOUBLE,
        rsi_6            DOUBLE,
        rsi_12           DOUBLE,
        rsi_24           DOUBLE,
        boll_upper       DOUBLE,
        boll_mid         DOUBLE,
        boll_lower       DOUBLE,
        ma_5             DOUBLE,
        ma_10            DOUBLE,
        ma_20            DOUBLE,
        ma_60            DOUBLE,
        volatility_20d   DOUBLE,
        turnover_20d     DOUBLE,
        -- 情绪因子
        volume_ratio     DOUBLE,
        price_momentum_20d  DOUBLE,
        price_momentum_60d  DOUBLE,
        updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (date, code)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_factor_data_date ON factor_data(date)",
    "CREATE INDEX IF NOT EXISTS idx_factor_data_code ON factor_data(code)",
    """CREATE TABLE IF NOT EXISTS factor_ic (
        date               DATE    NOT NULL,
        factor_name        VARCHAR NOT NULL,
        ic                 DOUBLE,
        ic_rank            DOUBLE,
        ir                 DOUBLE,
        ic_positive_ratio  DOUBLE,
        updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (date, factor_name)
    )""",
    """CREATE TABLE IF NOT EXISTS factor_return (
        date                DATE    NOT NULL,
        factor_name         VARCHAR NOT NULL,
        long_return         DOUBLE,
        short_return        DOUBLE,
        long_short_return   DOUBLE,
        quantile_returns    JSON,
        updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (date, factor_name)
    )""",
)
DUCKDB_MARKET_TABLES: Final[tuple[str, ...]] = (
    "adj_factor",
    "daily_bar",
    "daily_basic",
    "factor_data",
    "factor_ic",
    "factor_return",
    "index_daily",
    "intraday_fund_flow",
    "intraday_sector_flow",
    "intraday_spot",
    "limit_list",
    "minute_bar",
)
_MINUTE_BAR_PARTITION_TABLE_RE: Final[re.Pattern[str]] = re.compile(r"^minute_bar_(\d{4})_(\d{2})$")
_MINUTE_BAR_COLUMNS: Final[tuple[tuple[str, str], ...]] = (
    ("ts_code", "VARCHAR"),
    ("datetime", "TIMESTAMP"),
    ("freq", "VARCHAR"),
    ("open", "DOUBLE"),
    ("high", "DOUBLE"),
    ("low", "DOUBLE"),
    ("close", "DOUBLE"),
    ("vol", "DOUBLE"),
    ("amount", "DOUBLE"),
    ("updated_at", "TIMESTAMP"),
)
_MINUTE_BAR_COLUMN_NAMES: Final[tuple[str, ...]] = tuple(column for column, _ in _MINUTE_BAR_COLUMNS)
_DUCKDB_DATE_COLUMNS: Final[dict[str, str]] = {
    "adj_factor": "trade_date",
    "daily_bar": "trade_date",
    "daily_basic": "trade_date",
    "factor_data": "date",
    "factor_ic": "date",
    "factor_return": "date",
    "index_daily": "trade_date",
    "limit_list": "trade_date",
    "minute_bar": "datetime",
}


class DuckDBMarketStore(IMarketStore):
    """DuckDB-backed implementation of the market store interface."""

    def __init__(self, db_path: str | None = None, *, read_only: bool = False) -> None:
        """Initialize the DuckDB market store."""
        self.db_path = db_path or settings.duckdb_path
        path = Path(self.db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection: DuckDBPyConnection = duckdb.connect(str(path), read_only=read_only)
        self.read_only = read_only

    def init_schema(self) -> None:
        """Create all market tables and indexes."""
        for statement in DUCKDB_SCHEMA_SQL:
            self.connection.execute(statement)
        self._bootstrap_minute_bar_storage()
        logger.info("DuckDB market schema initialized.")

    def upsert(self, table: str, df: pd.DataFrame) -> int:
        """Upsert rows into the validated market table."""
        validated_table = _validate_market_table(table)
        if df.empty:
            return 0

        if validated_table == "minute_bar":
            return self._upsert_partitioned_minute_bar(df)

        table_columns = self._table_columns(validated_table)
        columns = [column for column in table_columns if column in df.columns]
        if not columns:
            return 0
        frame = df.loc[:, columns].copy()
        column_list = ", ".join(_quote_identifier(column) for column in columns)
        select_list = ", ".join(_quote_identifier(column) for column in columns)
        rows = len(frame.index)
        self.connection.register("upsert_frame", frame)
        self.connection.execute(
            f"INSERT OR REPLACE INTO {validated_table} ({column_list}) "
            f"SELECT {select_list} FROM upsert_frame"
        )
        self.connection.unregister("upsert_frame")
        return rows

    def _bootstrap_minute_bar_storage(self) -> None:
        """Migrate legacy minute_bar storage and ensure the compatibility view exists."""
        relation = self._relation_type("minute_bar")
        if relation == "BASE TABLE":
            if self.count("minute_bar") > 0:
                self._migrate_legacy_minute_bar_table()
            else:
                self.connection.execute("DROP TABLE minute_bar")
                self._refresh_minute_bar_view()
            return
        self._refresh_minute_bar_view()

    def _migrate_legacy_minute_bar_table(self) -> None:
        """Split the legacy monolithic minute_bar table into month partitions."""
        month_rows = self.connection.execute(
            """
            SELECT DISTINCT
                EXTRACT(YEAR FROM datetime)::INTEGER AS year,
                EXTRACT(MONTH FROM datetime)::INTEGER AS month
            FROM minute_bar
            ORDER BY year, month
            """
        ).fetchall()
        for year, month in month_rows:
            partition_table = self._minute_bar_partition_table_name(int(year), int(month))
            self._ensure_minute_bar_partition(partition_table)
            self.connection.execute(
                f"""
                INSERT OR REPLACE INTO {_quote_identifier(partition_table)}
                SELECT *
                FROM minute_bar
                WHERE EXTRACT(YEAR FROM datetime) = {int(year)}
                  AND EXTRACT(MONTH FROM datetime) = {int(month)}
                """
            )
        self.connection.execute("DROP TABLE minute_bar")
        self._refresh_minute_bar_view()

    def _upsert_partitioned_minute_bar(self, df: pd.DataFrame) -> int:
        """Upsert minute-bar rows into month-sized physical partitions."""
        columns = [column for column in _MINUTE_BAR_COLUMN_NAMES if column in df.columns]
        if not columns:
            return 0

        frame = df.loc[:, columns].copy()
        if "datetime" not in frame.columns:
            return 0
        frame["datetime"] = pd.to_datetime(frame["datetime"], errors="coerce")
        frame = frame.dropna(subset=["datetime"])
        if frame.empty:
            return 0

        rows = len(frame.index)
        column_list = ", ".join(_quote_identifier(column) for column in columns)
        select_list = ", ".join(_quote_identifier(column) for column in columns)

        try:
            for period, partition_frame in frame.groupby(frame["datetime"].dt.to_period("M"), sort=True):
                partition_table = self._minute_bar_partition_table_name(period.year, period.month)
                self._ensure_minute_bar_partition(partition_table)
                self.connection.register("upsert_frame", partition_frame)
                try:
                    self.connection.execute(
                        f"INSERT OR REPLACE INTO {_quote_identifier(partition_table)} ({column_list}) "
                        f"SELECT {select_list} FROM upsert_frame"
                    )
                finally:
                    self.connection.unregister("upsert_frame")
        finally:
            self._refresh_minute_bar_view()

        return rows

    def _ensure_minute_bar_partition(self, table_name: str) -> None:
        """Create a month partition for minute_bar if missing."""
        if not _MINUTE_BAR_PARTITION_TABLE_RE.fullmatch(table_name):
            raise StorageError(f"Invalid minute_bar partition table name: {table_name}")
        self.connection.execute(self._minute_bar_partition_table_sql(table_name))

    def _refresh_minute_bar_view(self) -> None:
        """Refresh the compatibility view that exposes all minute-bar partitions."""
        partition_rows = self.connection.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'main'
              AND table_type = 'BASE TABLE'
              AND table_name LIKE 'minute_bar\\_%' ESCAPE '\\'
            ORDER BY table_name
            """
        ).fetchall()
        partition_tables = [
            str(row[0]) for row in partition_rows if _MINUTE_BAR_PARTITION_TABLE_RE.fullmatch(str(row[0]))
        ]
        if partition_tables:
            union_sql = " UNION ALL ".join(f"SELECT * FROM {_quote_identifier(table_name)}" for table_name in partition_tables)
            view_sql = f"CREATE OR REPLACE VIEW minute_bar AS {union_sql}"
        else:
            view_sql = self._minute_bar_empty_view_sql()
        self.connection.execute(view_sql)

    @staticmethod
    def _minute_bar_partition_table_name(year: int, month: int) -> str:
        """Return the physical table name for a minute-bar month partition."""
        return f"minute_bar_{year:04d}_{month:02d}"

    @staticmethod
    def _minute_bar_partition_table_sql(table_name: str) -> str:
        """Build the CREATE TABLE statement for a minute-bar partition."""
        if not _MINUTE_BAR_PARTITION_TABLE_RE.fullmatch(table_name):
            raise StorageError(f"Invalid minute_bar partition table name: {table_name}")
        column_sql = ",\n            ".join(f"{name:<10} {dtype}" for name, dtype in _MINUTE_BAR_COLUMNS)
        return f"""
        CREATE TABLE IF NOT EXISTS {_quote_identifier(table_name)} (
            {column_sql},
            PRIMARY KEY (ts_code, datetime, freq)
        )
        """

    @staticmethod
    def _minute_bar_empty_view_sql() -> str:
        """Build an empty compatibility view for minute_bar."""
        return """
        CREATE OR REPLACE VIEW minute_bar AS
        SELECT
            CAST(NULL AS VARCHAR) AS ts_code,
            CAST(NULL AS TIMESTAMP) AS datetime,
            CAST(NULL AS VARCHAR) AS freq,
            CAST(NULL AS DOUBLE) AS open,
            CAST(NULL AS DOUBLE) AS high,
            CAST(NULL AS DOUBLE) AS low,
            CAST(NULL AS DOUBLE) AS close,
            CAST(NULL AS DOUBLE) AS vol,
            CAST(NULL AS DOUBLE) AS amount,
            CAST(NULL AS TIMESTAMP) AS updated_at
        WHERE FALSE
        """

    def _table_columns(self, table: str) -> list[str]:
        """Return ordered columns for a validated DuckDB market table."""
        if table == "minute_bar":
            return list(_MINUTE_BAR_COLUMN_NAMES)
        result = self.connection.execute(f"PRAGMA table_info({_quote_identifier(table)})")
        rows = result.fetchall()
        return [str(row[1]) for row in rows]

    def query(self, sql: str, params: Mapping[str, Any] | None = None) -> pd.DataFrame:
        """Execute a query and return a DataFrame."""
        # Use DuckDB native .df() for direct zero-copy conversion,
        # skipping the O(n*m) per-column type inference path.
        try:
            frame = self.connection.execute(sql, params).df()
        except (AttributeError, TypeError):
            # Fallback for very old DuckDB versions
            cursor = self.connection.execute(sql, params)
            rows = cursor.fetchall()
            columns = [description[0] for description in cursor.description]
            frame = pd.DataFrame(rows, columns=columns)
        return _normalize_duckdb_frame(frame)

    def execute(self, sql: str, params: Mapping[str, Any] | None = None) -> int:
        """Execute a statement and return affected row count."""
        cursor = self.connection.execute(sql, params)
        result = cursor.fetchone()
        if result is None:
            return 0
        affected = result[0]
        if not isinstance(affected, int):
            raise StorageError("DuckDB execute did not return an integer row count")
        return affected

    def get_last_date(self, table: str, ts_code: str | None = None) -> date | None:
        """Return the latest date-like value from a validated market table."""
        validated_table = _validate_market_table(table)
        date_column = _DUCKDB_DATE_COLUMNS[validated_table]
        sql = f"SELECT MAX({_quote_identifier(date_column)}) AS last_value FROM {validated_table}"
        params: dict[str, Any] | None = None
        if ts_code is not None:
            sql += " WHERE ts_code = $ts_code"
            params = {"ts_code": ts_code}
        result = self.query(sql, params)
        if result.empty:
            return None
        value: object = result.iloc[0]["last_value"]
        if pd.isna(value):
            return None
        if isinstance(value, pd.Timestamp):
            return date(value.year, value.month, value.day)
        if isinstance(value, date):
            return value
        raise StorageError(f"Unsupported date value returned for table {validated_table}")

    def count(self, table: str, where: str | None = None) -> int:
        """Count rows in a validated market table."""
        validated_table = _validate_market_table(table)
        sql = f"SELECT COUNT(*) AS row_count FROM {validated_table}"
        if where is not None:
            sql = f"{sql} WHERE {where}"
        result = self.query(sql)
        value = result.iloc[0]["row_count"]
        if isinstance(value, Integral):
            return int(value)
        raise StorageError(f"Unexpected count result for table {validated_table}")

    def close(self) -> None:
        """Close the DuckDB connection."""
        self.connection.close()

    def _relation_type(self, name: str) -> str | None:
        """Return the DuckDB relation type for a table or view name."""
        result = self.connection.execute(
            """
            SELECT table_type
            FROM information_schema.tables
            WHERE table_schema = 'main'
              AND table_name = $name
            LIMIT 1
            """,
            {"name": name},
        ).fetchall()
        if not result:
            return None
        return str(result[0][0])


def _validate_market_table(table: str) -> str:
    if table not in DUCKDB_MARKET_TABLES:
        raise StorageError(f"Unsupported market table: {table}")
    return table


def _quote_identifier(identifier: str) -> str:
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


def _normalize_duckdb_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize DuckDB query results for stable downstream assertions."""
    if frame.empty:
        return frame

    normalized = frame.copy()
    for column in normalized.columns:
        series = normalized[column]
        if pd.api.types.is_datetime64_any_dtype(series):
            continue
        if series.dtype == 'object':
            non_null = series.dropna()
            if non_null.empty:
                continue
            # Vectorized check: try to parse as date; if all non-null match, convert
            try:
                as_dt = pd.to_datetime(non_null, errors='coerce')
                if as_dt.notna().all():
                    normalized[column] = pd.to_datetime(series)
            except Exception:
                pass
    return normalized
