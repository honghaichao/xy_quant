from pathlib import Path

from config.settings import Settings
from utils.calendar import date_range, ensure_date, is_weekday
from utils.rate_limiter import TokenBucketRateLimiter


def test_settings_defaults_and_paths(tmp_path: Path) -> None:
    settings = Settings(log_dir=str(tmp_path / "logs"))
    assert settings.duckdb_path == "./data_store/market.duckdb"
    assert settings.log_dir_path.exists()


def test_rate_limiter_consumes_and_reports_tokens() -> None:
    limiter = TokenBucketRateLimiter(capacity=2, refill_rate=10)
    assert limiter.consume() is True
    assert limiter.consume() is True
    assert limiter.consume() is False
    assert limiter.available_tokens() >= 0


def test_calendar_helpers() -> None:
    start = ensure_date("2024-01-01")
    end = ensure_date("2024-01-03")
    assert len(date_range(start, end)) == 3
    assert is_weekday(start) is True
