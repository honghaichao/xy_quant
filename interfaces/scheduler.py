"""任务调度接口。"""
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime


class IScheduler(ABC):
    """Scheduler interface."""

    @abstractmethod
    def add_cron_job(
        self,
        func: Callable[..., object],
        cron_expr: str,
        job_id: str,
        **kwargs: object,
    ) -> None:
        """Add cron job."""

    @abstractmethod
    def add_date_job(
        self,
        func: Callable[..., object],
        run_date: datetime,
        job_id: str,
        **kwargs: object,
    ) -> None:
        """Add date job."""

    @abstractmethod
    def remove_job(self, job_id: str) -> None:
        """Remove job."""

    @abstractmethod
    def start(self) -> None:
        """Start scheduler."""

    @abstractmethod
    def shutdown(self) -> None:
        """Shutdown scheduler."""
