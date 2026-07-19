"""日志工具。统一使用 loguru,禁止 print。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast

from loguru import logger

from config.settings import settings

if TYPE_CHECKING:
    from loguru import Logger as LoguruLogger
else:
    LoguruLogger = Any

_LOG_FORMAT: Final[str] = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {extra[module]} | {message}"
)
_LOGGER_STATE: Final[dict[str, int | None | dict[str, int]]] = {
    "console_sink_id": None,
    "file_sink_ids": {},
}


def _module_filter(record: Any, module_name: str) -> bool:
    """Return whether the log record belongs to the requested module."""
    extra = cast(dict[str, object], record["extra"])
    module_value = extra.get("module")
    return module_value == module_name


def configure_logger(log_name: str = "app") -> LoguruLogger:
    """Configure and return a module-specific loguru logger."""
    bound_logger = logger.bind(module=log_name)
    console_sink_id = _LOGGER_STATE["console_sink_id"]
    file_sink_ids = _LOGGER_STATE["file_sink_ids"]

    if not isinstance(file_sink_ids, dict):
        raise TypeError("logger file sink state is invalid")

    if console_sink_id is None:
        logger.remove()
        _LOGGER_STATE["console_sink_id"] = logger.add(
            sys.stderr,
            level=settings.log_level,
            format=_LOG_FORMAT,
        )

    if log_name not in file_sink_ids:
        file_path = Path(settings.log_dir_path) / f"{log_name}.log"
        file_sink_ids[log_name] = logger.add(
            file_path,
            level=settings.log_level,
            format=_LOG_FORMAT,
            rotation="10 MB",
            encoding="utf-8",
            filter=lambda record: _module_filter(record, log_name),
        )

    return bound_logger


def get_logger(log_name: str = "app") -> LoguruLogger:
    """Return a configured module-specific logger instance."""
    return configure_logger(log_name=log_name)
