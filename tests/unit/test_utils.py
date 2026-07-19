from datetime import date
from pathlib import Path

import pytest

import utils.logger as logger_module
import utils.rate_limiter as rate_limiter_module
from config.settings import Settings
from utils.calendar import date_range, ensure_date, is_weekday
from utils.exception import (
    ConfigError,
    DataSourceError,
    QuantSystemError,
    StorageError,
    ValidationError,
)
from utils.retry import retry_on


@pytest.mark.parametrize(
    "error_cls",
    [ConfigError, DataSourceError, StorageError, ValidationError],
)
def test_custom_exceptions_inherit_base(error_cls: type[QuantSystemError]) -> None:
    error = error_cls("boom")
    assert isinstance(error, QuantSystemError)
    assert str(error) == "boom"


def test_get_logger_keeps_module_logs_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    test_settings = Settings(log_dir=str(tmp_path), log_level="INFO")
    monkeypatch.setattr(logger_module, "settings", test_settings)

    alpha_logger = logger_module.get_logger("alpha")
    alpha_logger.info("alpha-one")

    beta_logger = logger_module.get_logger("beta")
    beta_logger.info("beta-one")
    alpha_logger.info("alpha-two")

    alpha_contents = (tmp_path / "alpha.log").read_text(encoding="utf-8")
    beta_contents = (tmp_path / "beta.log").read_text(encoding="utf-8")

    assert "alpha-one" in alpha_contents
    assert "alpha-two" in alpha_contents
    assert "beta-one" not in alpha_contents
    assert "beta-one" in beta_contents
    assert "alpha-two" not in beta_contents


def test_token_bucket_refills_without_exceeding_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    ticks = iter([100.0, 100.0, 100.5, 102.5])
    monkeypatch.setattr(rate_limiter_module, "monotonic", lambda: next(ticks))

    limiter = rate_limiter_module.TokenBucketRateLimiter(capacity=3, refill_rate=2.0)

    assert limiter.consume(3) is True
    assert limiter.consume() is True
    assert limiter.available_tokens() == pytest.approx(3.0)


def test_token_bucket_acquire_waits_until_token_available(monkeypatch: pytest.MonkeyPatch) -> None:
    current_time = [100.0]
    sleeps: list[float] = []

    def fake_monotonic() -> float:
        return current_time[0]

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        current_time[0] += seconds

    monkeypatch.setattr(rate_limiter_module, "monotonic", fake_monotonic)
    monkeypatch.setattr(rate_limiter_module, "sleep", fake_sleep)

    limiter = rate_limiter_module.TokenBucketRateLimiter(capacity=1, refill_rate=2.0)

    assert limiter.consume() is True
    assert limiter.acquire() is True
    assert sleeps == [0.5]


@pytest.mark.parametrize(
    ("attempts", "min_wait", "max_wait"),
    [(0, 1, 1), (1, 0, 1), (1, 2, 1)],
)
def test_retry_on_rejects_invalid_configuration(
    attempts: int,
    min_wait: int,
    max_wait: int,
) -> None:
    with pytest.raises(ValueError):
        retry_on(DataSourceError, attempts=attempts, min_wait=min_wait, max_wait=max_wait)


def test_retry_on_retries_matching_exceptions() -> None:
    attempts = 0

    @retry_on(DataSourceError, attempts=3, min_wait=1, max_wait=1)
    def flaky_call() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise DataSourceError("temporary failure")
        return "ok"

    assert flaky_call() == "ok"
    assert attempts == 3


def test_date_range_rejects_inverted_bounds() -> None:
    with pytest.raises(ValueError):
        date_range(date(2024, 1, 3), date(2024, 1, 1))


def test_calendar_helpers_cover_supported_inputs() -> None:
    start = ensure_date("2024-01-01")
    end = ensure_date("2024-01-03")

    assert date_range(start, end) == [
        date(2024, 1, 1),
        date(2024, 1, 2),
        date(2024, 1, 3),
    ]
    assert is_weekday(start) is True
    assert is_weekday(date(2024, 1, 6)) is False
