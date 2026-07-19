"""重试装饰器。"""

from __future__ import annotations

from collections.abc import Callable
from typing import ParamSpec, TypeVar

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

P = ParamSpec("P")
R = TypeVar("R")


def retry_on(
    exception_types: type[Exception] | tuple[type[Exception], ...],
    attempts: int = 3,
    min_wait: int = 1,
    max_wait: int = 8,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Return a tenacity-based retry decorator."""
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    if min_wait < 1:
        raise ValueError("min_wait must be at least 1")
    if max_wait < min_wait:
        raise ValueError("max_wait must be greater than or equal to min_wait")

    return retry(
        retry=retry_if_exception_type(exception_types),
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
        reraise=True,
    )
