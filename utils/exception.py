"""项目异常定义。"""


class QuantSystemError(Exception):
    """Base exception for the project."""


class ConfigError(QuantSystemError):
    """Raised when configuration is invalid."""


class DataSourceError(QuantSystemError):
    """Raised when data source operations fail."""


class PartialUpdateError(QuantSystemError):
    """Raised when an updater completes with skipped sub-steps."""

    def __init__(self, message: str, *, counts: dict[str, int] | None = None, failures: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.counts = counts or {}
        self.failures = failures or {}


class StorageError(QuantSystemError):
    """Raised when storage operations fail."""


class ValidationError(QuantSystemError):
    """Raised when validation checks fail."""
