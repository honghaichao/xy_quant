"""PostgreSQL metadata storage implementation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

import pandas as pd
import psycopg
from psycopg import Connection
from psycopg.types.json import Jsonb

from config.settings import settings
from interfaces.meta_store import IMetaStore
from utils.exception import StorageError
from utils.logger import get_logger

logger = get_logger("pg_store")

POSTGRES_SCHEMA_SQL: Final[tuple[str, ...]] = (
    """
    CREATE TABLE IF NOT EXISTS stock_basic (
        ts_code        VARCHAR(20) PRIMARY KEY,
        symbol         VARCHAR(10) NOT NULL,
        name           VARCHAR(50) NOT NULL,
        area           VARCHAR(20),
        industry       VARCHAR(50),
        fullname       VARCHAR(100),
        cnspell        VARCHAR(50),
        market         VARCHAR(20),
        exchange       VARCHAR(10),
        list_status    VARCHAR(2),
        list_date      DATE,
        delist_date    DATE,
        is_hs          VARCHAR(2),
        act_name       VARCHAR(200),
        act_ent_type   VARCHAR(50),
        updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "ALTER TABLE stock_basic ADD COLUMN IF NOT EXISTS cnspell VARCHAR(50)",
    "ALTER TABLE stock_basic ADD COLUMN IF NOT EXISTS act_name VARCHAR(200)",
    "ALTER TABLE stock_basic ADD COLUMN IF NOT EXISTS act_ent_type VARCHAR(50)",
    "ALTER TABLE dividend ADD COLUMN IF NOT EXISTS div_listdate DATE",
    "ALTER TABLE dividend ADD COLUMN IF NOT EXISTS imp_ann_date DATE",
    "CREATE INDEX IF NOT EXISTS idx_stock_basic_industry ON stock_basic(industry)",
    "CREATE INDEX IF NOT EXISTS idx_stock_basic_market ON stock_basic(market)",
    """
    CREATE TABLE IF NOT EXISTS trade_calendar (
        exchange       VARCHAR(10) NOT NULL,
        cal_date       DATE NOT NULL,
        is_open        SMALLINT NOT NULL,
        pretrade_date  DATE,
        updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (exchange, cal_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS stock_suspend (
        ts_code        VARCHAR(20) NOT NULL,
        trade_date     DATE NOT NULL,
        suspend_type   VARCHAR(2) NOT NULL,
        suspend_timing VARCHAR(50),
        updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ts_code, trade_date, suspend_type)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS income (
        ts_code            VARCHAR(20) NOT NULL,
        end_date           DATE NOT NULL,
        ann_date           DATE,
        f_ann_date         DATE,
        report_type        VARCHAR(10) NOT NULL,
        comp_type          VARCHAR(10),
        basic_eps          DOUBLE PRECISION,
        diluted_eps        DOUBLE PRECISION,
        total_revenue      DOUBLE PRECISION,
        revenue            DOUBLE PRECISION,
        operate_profit     DOUBLE PRECISION,
        total_profit       DOUBLE PRECISION,
        n_income           DOUBLE PRECISION,
        n_income_attr_p    DOUBLE PRECISION,
        raw                JSONB,
        updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ts_code, end_date, report_type)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_income_end ON income(end_date)",
    """
    CREATE TABLE IF NOT EXISTS balancesheet (
        ts_code             VARCHAR(20) NOT NULL,
        end_date            DATE NOT NULL,
        ann_date            DATE,
        f_ann_date          DATE,
        report_type         VARCHAR(10) NOT NULL,
        total_assets        DOUBLE PRECISION,
        total_liab          DOUBLE PRECISION,
        total_hldr_eqy_inc_min_int DOUBLE PRECISION,
        total_cur_assets    DOUBLE PRECISION,
        total_cur_liab      DOUBLE PRECISION,
        inventories         DOUBLE PRECISION,
        accounts_receiv     DOUBLE PRECISION,
        money_cap           DOUBLE PRECISION,
        raw                 JSONB,
        updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ts_code, end_date, report_type)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cashflow (
        ts_code              VARCHAR(20) NOT NULL,
        end_date             DATE NOT NULL,
        ann_date             DATE,
        f_ann_date           DATE,
        report_type          VARCHAR(10) NOT NULL,
        n_cashflow_act       DOUBLE PRECISION,
        n_cashflow_inv_act   DOUBLE PRECISION,
        n_cash_flows_fnc_act DOUBLE PRECISION,
        c_inf_fr_operate_a   DOUBLE PRECISION,
        c_paid_goods_s       DOUBLE PRECISION,
        free_cashflow        DOUBLE PRECISION,
        raw                  JSONB,
        updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ts_code, end_date, report_type)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fina_indicator (
        ts_code           VARCHAR(20) NOT NULL,
        end_date          DATE NOT NULL,
        ann_date          DATE,
        roe               DOUBLE PRECISION,
        roa               DOUBLE PRECISION,
        gross_margin      DOUBLE PRECISION,
        op_of_gr          DOUBLE PRECISION,
        netprofit_margin  DOUBLE PRECISION,
        debt_to_assets    DOUBLE PRECISION,
        current_ratio     DOUBLE PRECISION,
        quick_ratio       DOUBLE PRECISION,
        raw               JSONB,
        updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ts_code, end_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dividend (
        ts_code        VARCHAR(20) NOT NULL,
        end_date       DATE NOT NULL,
        ann_date       DATE,
        div_proc       VARCHAR(20) NOT NULL,
        stk_div        DOUBLE PRECISION,
        stk_bo_rate    DOUBLE PRECISION,
        stk_co_rate    DOUBLE PRECISION,
        cash_div       DOUBLE PRECISION,
        cash_div_tax   DOUBLE PRECISION,
        record_date    DATE,
        ex_date        DATE,
        pay_date       DATE,
        div_listdate   DATE,
        imp_ann_date   DATE,
        updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ts_code, end_date, div_proc)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS top_list (
        trade_date     DATE NOT NULL,
        ts_code        VARCHAR(20) NOT NULL,
        name           VARCHAR(50),
        close          DOUBLE PRECISION,
        pct_change     DOUBLE PRECISION,
        turnover_rate  DOUBLE PRECISION,
        amount         DOUBLE PRECISION,
        l_sell         DOUBLE PRECISION,
        l_buy          DOUBLE PRECISION,
        l_amount       DOUBLE PRECISION,
        net_amount     DOUBLE PRECISION,
        net_rate       DOUBLE PRECISION,
        amount_rate    DOUBLE PRECISION,
        float_values   DOUBLE PRECISION,
        reason         VARCHAR(200) NOT NULL,
        updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (trade_date, ts_code, reason)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS margin_detail (
        trade_date     DATE NOT NULL,
        ts_code        VARCHAR(20) NOT NULL,
        name           VARCHAR(50),
        rzye           DOUBLE PRECISION,
        rqye           DOUBLE PRECISION,
        rzmre          DOUBLE PRECISION,
        rqyl           DOUBLE PRECISION,
        rzche          DOUBLE PRECISION,
        rqchl          DOUBLE PRECISION,
        rqmcl          DOUBLE PRECISION,
        rzrqye         DOUBLE PRECISION,
        updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (trade_date, ts_code)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS stk_holdertrade (
        ts_code        VARCHAR(20) NOT NULL,
        ann_date       DATE NOT NULL,
        holder_name    VARCHAR(200) NOT NULL,
        holder_type    VARCHAR(10),
        in_de          VARCHAR(10) NOT NULL,
        change_vol     DOUBLE PRECISION,
        change_ratio   DOUBLE PRECISION,
        after_share    DOUBLE PRECISION,
        after_ratio    DOUBLE PRECISION,
        avg_price      DOUBLE PRECISION,
        total_share    DOUBLE PRECISION,
        begin_date     DATE,
        close_date     DATE,
        updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ts_code, ann_date, holder_name, in_de)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS hk_hold (
        trade_date     DATE NOT NULL,
        ts_code        VARCHAR(20) NOT NULL,
        name           VARCHAR(50),
        vol            DOUBLE PRECISION,
        ratio          DOUBLE PRECISION,
        exchange       VARCHAR(10) NOT NULL,
        updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (trade_date, ts_code, exchange)
    )
    """,
    "ALTER TABLE hk_hold ALTER COLUMN name TYPE VARCHAR(200)",
    """
    CREATE TABLE IF NOT EXISTS concept_member (
        concept_code   VARCHAR(20) NOT NULL,
        concept_name   VARCHAR(100) NOT NULL,
        ts_code        VARCHAR(20) NOT NULL,
        in_date        DATE NOT NULL,
        out_date       DATE,
        is_active      SMALLINT DEFAULT 1,
        updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (concept_code, ts_code, in_date)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_concept_member_ts ON concept_member(ts_code)",
    """
    CREATE TABLE IF NOT EXISTS concept_list (
        code           VARCHAR(20) PRIMARY KEY,
        name           VARCHAR(100) NOT NULL,
        src            VARCHAR(20),
        updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS industry_list (
        index_code     VARCHAR(20) PRIMARY KEY,
        industry_name  VARCHAR(100) NOT NULL,
        level          VARCHAR(10),
        industry_code  VARCHAR(20),
        is_pub         VARCHAR(10),
        parent_code    VARCHAR(20),
        src            VARCHAR(20),
        updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_industry_list_code ON industry_list(industry_code)",
    """
    CREATE TABLE IF NOT EXISTS industry_member (
        industry_code  VARCHAR(20) NOT NULL,
        industry_name  VARCHAR(100) NOT NULL,
        ts_code        VARCHAR(20) NOT NULL,
        in_date        DATE NOT NULL,
        out_date       DATE,
        updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (industry_code, ts_code, in_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS index_weight (
        index_code     VARCHAR(20) NOT NULL,
        ts_code        VARCHAR(20) NOT NULL,
        trade_date     DATE NOT NULL,
        weight         DOUBLE PRECISION,
        updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (index_code, ts_code, trade_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS concept_money_flow (
        trade_date       DATE NOT NULL,
        concept_code     VARCHAR(20) NOT NULL,
        concept_name     VARCHAR(100) NOT NULL,
        pct_chg          DOUBLE PRECISION,
        main_inflow      DOUBLE PRECISION,
        main_inflow_pct  DOUBLE PRECISION,
        super_inflow     DOUBLE PRECISION,
        big_inflow       DOUBLE PRECISION,
        mid_inflow       DOUBLE PRECISION,
        small_inflow     DOUBLE PRECISION,
        updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (trade_date, concept_code)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_concept_mf_date ON concept_money_flow(trade_date)",
    """
    CREATE TABLE IF NOT EXISTS industry_money_flow (
        trade_date       DATE NOT NULL,
        industry_code    VARCHAR(20) NOT NULL,
        industry_name    VARCHAR(100) NOT NULL,
        pct_chg          DOUBLE PRECISION,
        main_inflow      DOUBLE PRECISION,
        main_inflow_pct  DOUBLE PRECISION,
        super_inflow     DOUBLE PRECISION,
        big_inflow       DOUBLE PRECISION,
        mid_inflow       DOUBLE PRECISION,
        small_inflow     DOUBLE PRECISION,
        updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (trade_date, industry_code)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_industry_mf_date ON industry_money_flow(trade_date)",
    """
    CREATE TABLE IF NOT EXISTS stock_money_flow (
        trade_date       DATE NOT NULL,
        ts_code          VARCHAR(20) NOT NULL,
        name             VARCHAR(50),
        pct_chg          DOUBLE PRECISION,
        main_inflow      DOUBLE PRECISION,
        main_inflow_pct  DOUBLE PRECISION,
        super_inflow     DOUBLE PRECISION,
        big_inflow       DOUBLE PRECISION,
        mid_inflow       DOUBLE PRECISION,
        small_inflow     DOUBLE PRECISION,
        updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (trade_date, ts_code)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_stock_mf_date ON stock_money_flow(trade_date)",
    """
    CREATE TABLE IF NOT EXISTS data_update_log (
        id             BIGSERIAL PRIMARY KEY,
        log_key        VARCHAR(64) UNIQUE,
        table_name     VARCHAR(100) NOT NULL,
        source         VARCHAR(50) NOT NULL,
        update_type    VARCHAR(20) NOT NULL,
        start_date     DATE,
        end_date       DATE,
        rows_affected  INTEGER,
        status         VARCHAR(20) NOT NULL,
        error_msg      TEXT,
        context        JSONB,
        started_at     TIMESTAMP NOT NULL,
        finished_at    TIMESTAMP
    )
    """,
    "ALTER TABLE data_update_log ADD COLUMN IF NOT EXISTS log_key VARCHAR(64)",
    "ALTER TABLE data_update_log ADD COLUMN IF NOT EXISTS context JSONB",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_data_update_log_log_key ON data_update_log(log_key)",
    "CREATE INDEX IF NOT EXISTS idx_update_log_table ON data_update_log(table_name, started_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS data_quality_report (
        id             BIGSERIAL PRIMARY KEY,
        report_key     VARCHAR(64) UNIQUE,
        report_date    DATE NOT NULL,
        table_name     VARCHAR(100) NOT NULL,
        check_type     VARCHAR(50) NOT NULL,
        check_result   VARCHAR(20) NOT NULL,
        details        JSONB,
        created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "ALTER TABLE data_quality_report ADD COLUMN IF NOT EXISTS report_key VARCHAR(64)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_data_quality_report_report_key ON data_quality_report(report_key)",
    "CREATE INDEX IF NOT EXISTS idx_quality_report ON data_quality_report(report_date, table_name)",
)
POSTGRES_META_TABLES: Final[tuple[str, ...]] = (
    "balancesheet",
    "cashflow",
    "concept_list",
    "concept_member",
    "concept_money_flow",
    "data_quality_report",
    "data_update_log",
    "dividend",
    "fina_indicator",
    "hk_hold",
    "income",
    "index_weight",
    "industry_list",
    "industry_member",
    "industry_money_flow",
    "margin_detail",
    "stock_basic",
    "stock_money_flow",
    "stock_suspend",
    "stk_holdertrade",
    "top_list",
    "trade_calendar",
)
_POSTGRES_PRIMARY_KEYS: Final[dict[str, tuple[str, ...]]] = {
    "balancesheet": ("ts_code", "end_date", "report_type"),
    "cashflow": ("ts_code", "end_date", "report_type"),
    "concept_list": ("code",),
    "concept_member": ("concept_code", "ts_code", "in_date"),
    "concept_money_flow": ("trade_date", "concept_code"),
    "data_quality_report": ("report_key",),
    "data_update_log": ("log_key",),
    "dividend": ("ts_code", "end_date", "div_proc"),
    "fina_indicator": ("ts_code", "end_date"),
    "hk_hold": ("trade_date", "ts_code", "exchange"),
    "income": ("ts_code", "end_date", "report_type"),
    "index_weight": ("index_code", "ts_code", "trade_date"),
    "industry_list": ("index_code",),
    "industry_member": ("industry_code", "ts_code", "in_date"),
    "industry_money_flow": ("trade_date", "industry_code"),
    "margin_detail": ("trade_date", "ts_code"),
    "stock_basic": ("ts_code",),
    "stock_money_flow": ("trade_date", "ts_code"),
    "stock_suspend": ("ts_code", "trade_date", "suspend_type"),
    "stk_holdertrade": ("ts_code", "ann_date", "holder_name", "in_de"),
    "top_list": ("trade_date", "ts_code", "reason"),
    "trade_calendar": ("exchange", "cal_date"),
}


class PostgresMetaStore(IMetaStore):
    """PostgreSQL-backed implementation of the metadata store interface."""

    def __init__(self, dsn: str | None = None, connection: Connection[Any] | Any | None = None) -> None:
        """Initialize the metadata store with optional injected connection."""
        self._dsn = dsn or _build_pg_dsn()
        self._connection: Connection[Any] | Any | None = connection
        self._table_columns_cache: dict[str, set[str]] = {}

    @property
    def connection(self) -> Connection[Any] | Any:
        """Return an active PostgreSQL connection, connecting lazily when needed."""
        if self._connection is None:
            self._connection = psycopg.connect(self._dsn)
        return self._connection

    def init_schema(self) -> None:
        """Create all metadata tables and indexes."""
        with self.connection.cursor() as cursor:
            for statement in POSTGRES_SCHEMA_SQL:
                cursor.execute(statement)
        self.connection.commit()
        logger.info("PostgreSQL metadata schema initialized.")

    def _get_table_columns(self, table: str) -> set[str]:
        cached = self._table_columns_cache.get(table)
        if cached is not None:
            return cached

        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                """,
                (table,),
            )
            columns = {row[0] for row in cursor.fetchall()}
        self._table_columns_cache[table] = columns
        return columns

    @staticmethod
    def _normalize_row_for_table(table: str, row: dict[str, Any], available_columns: set[str]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        extra: dict[str, Any] = {}
        for key, value in row.items():
            if key in available_columns:
                normalized[key] = value
            else:
                extra[key] = value

        if 'raw' in available_columns:
            existing_raw = normalized.get('raw')
            merged_raw = dict(existing_raw) if isinstance(existing_raw, dict) else {}
            merged_raw.update(extra)
            normalized['raw'] = merged_raw

        return normalized

    def upsert(self, table: str, df: pd.DataFrame) -> int:
        """Upsert DataFrame rows into the validated metadata table."""
        validated_table = _validate_meta_table(table)
        if df.empty:
            return 0

        available_columns = self._get_table_columns(validated_table)
        rows = [self._normalize_row_for_table(validated_table, row, available_columns) for row in df.to_dict(orient="records")]
        prepared_rows = [_prepare_row(row) for row in rows]
        columns = list(prepared_rows[0].keys())
        column_sql = ", ".join(_quote_identifier(column) for column in columns)
        placeholder_names = [f"p{index}" for index, _ in enumerate(columns)]
        value_sql = ", ".join(f"%({name})s" for name in placeholder_names)
        key_columns = _POSTGRES_PRIMARY_KEYS[validated_table]
        update_columns = [column for column in columns if column not in key_columns]
        conflict_sql = ", ".join(_quote_identifier(column) for column in key_columns)
        if update_columns:
            update_sql = ", ".join(
                f"{_quote_identifier(column)} = EXCLUDED.{_quote_identifier(column)}"
                for column in update_columns
            )
            sql = (
                f"INSERT INTO {_quote_identifier(validated_table)} ({column_sql}) VALUES ({value_sql}) "
                f"ON CONFLICT ({conflict_sql}) DO UPDATE SET {update_sql}"
            )
        else:
            sql = (
                f"INSERT INTO {_quote_identifier(validated_table)} ({column_sql}) VALUES ({value_sql}) "
                f"ON CONFLICT ({conflict_sql}) DO NOTHING"
            )

        with self.connection.cursor() as cursor:
            cursor.executemany(
                sql,
                [
                    {name: row[column] for name, column in zip(placeholder_names, columns, strict=True)}
                    for row in prepared_rows
                ],
                returning=False,
            )
        self.connection.commit()
        return len(prepared_rows)

    def query(self, sql: str, params: Mapping[str, Any] | None = None) -> pd.DataFrame:
        """Execute a query and return the result as a DataFrame."""
        with self.connection.cursor() as cursor:
            cursor.execute(sql, dict(params) if params is not None else None)
            rows = cursor.fetchall()
            description = cursor.description or []
            columns = [column.name for column in description]
        return pd.DataFrame(rows, columns=columns)

    def execute(self, sql: str, params: Mapping[str, Any] | None = None) -> int:
        """Execute a statement and return affected row count."""
        with self.connection.cursor() as cursor:
            cursor.execute(sql, dict(params) if params is not None else None)
            rowcount = cursor.rowcount
        self.connection.commit()
        return rowcount if rowcount >= 0 else 0

    def close(self) -> None:
        """Close the PostgreSQL connection when present."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None


def _build_pg_dsn() -> str:
    """Build PostgreSQL DSN from live settings for psycopg connections."""
    return (
        f"postgresql://{settings.pg_user}:{settings.pg_password}@"
        f"{settings.pg_host}:{settings.pg_port}/{settings.pg_database}"
    )


def _validate_meta_table(table: str) -> str:
    if table not in POSTGRES_META_TABLES:
        raise StorageError(f"Unsupported meta table: {table}")
    return table


def _quote_identifier(identifier: str) -> str:
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


def _prepare_row(row: dict[str, Any]) -> dict[str, Any]:
    prepared: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, dict | list):
            prepared[key] = Jsonb(_sanitize_json_value(value))
        elif pd.isna(value):
            prepared[key] = None
        else:
            prepared[key] = value
    return prepared


def _sanitize_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_json_value(item) for item in value]
    if pd.isna(value):
        return None
    return value
