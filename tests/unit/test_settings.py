"""Unit tests for configuration settings."""

from __future__ import annotations

from config.settings import Settings


def test_minute_bar_rate_limit_has_its_own_setting() -> None:
    """minute bar should use a dedicated rate limit setting."""
    settings = Settings.model_construct(
        tushare_rate_limit_per_min=200,
        minute_bar_rate_limit_per_min=500,
    )

    assert settings.tushare_rate_limit_per_min == 200
    assert settings.minute_bar_rate_limit_per_min == 500


def test_pg_dsn_uses_real_configured_password() -> None:
    """pg_dsn should preserve the configured password for runtime connections."""
    settings = Settings.model_construct(
        pg_user="quant_user",
        pg_password="secret-pass",
        pg_host="db.local",
        pg_port=5433,
        pg_database="xy_quant",
    )

    assert settings.pg_dsn == "postgresql://quant_user:secret-pass@db.local:5433/xy_quant"
