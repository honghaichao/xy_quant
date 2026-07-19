"""全局配置。从 .env 加载,不允许硬编码任何敏感值。"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    tushare_token: str = ""
    duckdb_path: str = "./data_store/market.duckdb"
    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_user: str = "quant"
    pg_password: str = ""
    pg_database: str = "quant"
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""
    tushare_rate_limit_per_min: int = 200
    minute_bar_rate_limit_per_min: int = 500
    minute_bar_fetch_workers: int = 10
    minute_bar_stock_workers: int | None = None
    akshare_rate_limit_per_min: int = 300
    log_level: str = "INFO"
    log_dir: str = "./logs"
    primary_data_source: str = "tushare"
    fallback_data_source: str = "akshare"
    notifier_type: str = ""
    email_smtp_host: str = ""
    email_smtp_port: int = 587
    email_username: str = ""
    email_password: str = ""
    email_to: str = ""
    dingtalk_webhook: str = ""
    qmt_path: str = ""
    qmt_account_id: str = ""
    qmt_session_id: str = ""
    llm_provider: str = "local_rule"
    llm_api_key: str = ""
    llm_api_base: str = ""

    @property
    def resolved_minute_bar_stock_workers(self) -> int:
        """Return the stock-level concurrency for minute-bar backfills."""
        configured = self.minute_bar_stock_workers
        if configured is None:
            configured = self.minute_bar_fetch_workers
        return max(1, configured)

    @property
    def pg_dsn(self) -> str:
        """Build PostgreSQL DSN from settings for runtime connections."""
        return (
            f"postgresql://{self.pg_user}:{self.pg_password}@"
            f"{self.pg_host}:{self.pg_port}/{self.pg_database}"
        )

    @property
    def log_dir_path(self) -> Path:
        """Return log directory path and ensure it exists."""
        path = Path(self.log_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()
