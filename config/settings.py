"""全局配置。从 .env 加载,不允许硬编码任何敏感值。"""
import functools
from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
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
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
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


# ── 交易配置（settings.yaml trading: 段）─────────────────────────

_SETTINGS_YAML = Path(__file__).resolve().parent / "settings.yaml"


class LiveStrategyConfig(BaseModel):
    """JQ 实盘策略条目。"""

    id: str
    module: str
    mode: str = "paper"          # paper | confirm
    initial_cash: float = 100_000.0
    enabled: bool = True


class LiveConfig(BaseModel):
    """JQ 实盘引擎配置。"""

    write_positions_table: bool = True
    fill_fallback: str = "market"    # market | skip
    strategies: list[LiveStrategyConfig] = []


class TradingConfig(BaseModel):
    """交易参数（信号纸面盘 + JQ 引擎共用），缺省与历史硬编码值一致。"""

    initial_cash: float = 500_000.0
    fee_rate: float = 0.0005
    max_positions: int = 10
    fixed_stop_loss_pct: float = 0.05
    strategy_alloc: dict[str, float] = {
        "B1": 0.30, "B2": 0.25, "BLK": 0.15,
        "BLKB2": 0.15, "SCB": 0.10, "DZ30": 0.05,
    }
    max_per_strategy: dict[str, int] = {}
    market_filter_enabled: bool = False
    market_filter_index: str = "000001.SH"
    market_filter_ma_period: int = 20
    commission: float = 0.0003
    stamp_duty: float = 0.001
    min_commission: float = 0.0
    stamp_duty: float = 0.001
    min_commission: float = 0.0
    live: LiveConfig = LiveConfig()
    stamp_duty: float = 0.001
    min_commission: float = 0.0
    live: LiveConfig = LiveConfig()


@functools.cache
def get_trading_config() -> TradingConfig:
    """Load the trading section from settings.yaml (cached)."""
    try:
        raw = yaml.safe_load(_SETTINGS_YAML.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        raw = {}
    trading_raw = raw.get("trading") or {}
    # yaml key market_filter → pydantic market_filter_* 前缀（flat 映射）
    mf = trading_raw.pop("market_filter", None)
    if isinstance(mf, dict):
        trading_raw.setdefault("market_filter_enabled", mf.get("enabled", False))
        trading_raw.setdefault("market_filter_index", mf.get("index_code", "000001.SH"))
        trading_raw.setdefault("market_filter_ma_period", mf.get("ma_period", 20))
    return TradingConfig.model_validate(trading_raw)
