"""Scheduler service for orchestrating configured data refresh jobs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

try:
    from apscheduler.schedulers.background import BackgroundScheduler
except ModuleNotFoundError:  # pragma: no cover - optional dependency for tests/runtime fallback
    class BackgroundScheduler:  # type: ignore[no-redef]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._started = False

        def add_job(self, *args: Any, **kwargs: Any) -> None:
            return None

        def start(self) -> None:
            self._started = True

        def shutdown(self, *args: Any, **kwargs: Any) -> None:
            self._started = False

from scripts.full_load_all import run_job as full_load_all_run_job
from scripts.update_all import run_job as update_all_run_job
from scripts.update_midnight_market_data import run_job as update_midnight_market_data_run_job
from utils.logger import get_logger
from utils.retry import retry_on

logger = get_logger('scheduler')

JobCallable = Callable[..., dict[str, Any]]
AlerterCallable = Callable[[str], None]


@dataclass(frozen=True)
class SchedulerSettings:
    """Top-level scheduler configuration loaded from YAML."""

    timezone: str
    jobstore: str
    jobs_path: Path
    retry_attempts: int
    retry_min_wait: int
    retry_max_wait: int


@dataclass(frozen=True)
class SchedulerJob:
    """One configured scheduler job definition."""

    job_id: str
    target: str
    trigger: str
    cron: dict[str, Any]
    kwargs: dict[str, Any]
    enabled: bool


def load_scheduler_settings(path: str | Path) -> SchedulerSettings:
    """Load scheduler settings from a YAML file."""
    config_path = Path(path)
    payload = yaml.safe_load(config_path.read_text(encoding='utf-8')) or {}
    scheduler_config = payload.get('scheduler', {})
    jobs_path_value = scheduler_config.get('jobs_path', 'config/scheduler_jobs.yaml')
    jobs_path = Path(jobs_path_value)
    if not jobs_path.is_absolute():
        jobs_path = (config_path.parent.parent / jobs_path).resolve()
    return SchedulerSettings(
        timezone=scheduler_config.get('timezone', 'Asia/Shanghai'),
        jobstore=scheduler_config.get('jobstore', 'memory'),
        jobs_path=jobs_path,
        retry_attempts=scheduler_config.get('retry_attempts', 3),
        retry_min_wait=scheduler_config.get('retry_min_wait', 1),
        retry_max_wait=scheduler_config.get('retry_max_wait', 8),
    )


def load_scheduler_jobs(path: str | Path) -> list[SchedulerJob]:
    """Load scheduler job definitions from a YAML file."""
    payload = yaml.safe_load(Path(path).read_text(encoding='utf-8')) or {}
    return [
        SchedulerJob(
            job_id=item['id'],
            target=item['target'],
            trigger=item.get('trigger', 'cron'),
            cron=dict(item.get('cron', {})),
            kwargs=dict(item.get('kwargs', {})),
            enabled=item.get('enabled', True),
        )
        for item in payload.get('jobs', [])
    ]


class SchedulerService:
    """Register and dispatch cron jobs defined in YAML configuration."""

    def __init__(
        self,
        settings_path: str | Path = 'config/settings.yaml',
        registry: dict[str, JobCallable] | None = None,
        alerter: AlerterCallable | None = None,
    ) -> None:
        self.settings_path = Path(settings_path)
        self.settings = load_scheduler_settings(self.settings_path)
        self.jobs = load_scheduler_jobs(self.settings.jobs_path)
        self.registry = registry or {
            'full_load_all': full_load_all_run_job,
            'update_all': update_all_run_job,
            'update_midnight_market_data': update_midnight_market_data_run_job,
        }
        self.alerter = alerter or self._default_alerter

    def create_scheduler(self) -> BackgroundScheduler:
        """Create a background scheduler using configured timezone."""
        scheduler = BackgroundScheduler(timezone=self.settings.timezone)
        scheduler.start(paused=True)
        return scheduler

    def register_jobs(self, scheduler: BackgroundScheduler) -> None:
        """Register configured jobs with the provided APScheduler instance."""
        for job in self.jobs:
            if not job.enabled:
                logger.info(f'Skipping disabled scheduler job: {job.job_id}')
                continue
            scheduler.add_job(
                self._execute_registered_job,
                trigger=job.trigger,
                id=job.job_id,
                replace_existing=True,
                kwargs={'job_id': job.job_id, **job.kwargs},
                **job.cron,
            )

    def run_job_now(self, job_id: str) -> dict[str, Any]:
        """Execute one configured job immediately by identifier."""
        job = self._get_job(job_id)
        return self._run_job_with_retry(job, job.kwargs)

    def start(self) -> BackgroundScheduler:
        """Create a scheduler, register jobs, and resume job execution."""
        scheduler = self.create_scheduler()
        self.register_jobs(scheduler)
        scheduler.resume()
        enabled_jobs = sum(1 for job in self.jobs if job.enabled)
        logger.info(f'Scheduler started with {enabled_jobs} enabled jobs.')
        return scheduler

    def _execute_registered_job(self, job_id: str, **kwargs: Any) -> dict[str, Any]:
        """Dispatch a scheduled job to the configured target registry."""
        job = self._get_job(job_id)
        logger.info(f'Running scheduler job: {job_id}')
        return self._run_job_with_retry(job, kwargs)

    def _get_job(self, job_id: str) -> SchedulerJob:
        """Return one configured job by identifier."""
        return next(job for job in self.jobs if job.job_id == job_id)

    def _run_job_with_retry(self, job: SchedulerJob, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Execute a configured job with retry and alert handling."""

        @retry_on(
            Exception,
            attempts=self.settings.retry_attempts,
            min_wait=self.settings.retry_min_wait,
            max_wait=self.settings.retry_max_wait,
        )
        def execute() -> dict[str, Any]:
            return self.registry[job.target](**kwargs)

        try:
            return execute()
        except Exception as exc:
            message = (
                f'Scheduler job {job.job_id} failed after '
                f'{self.settings.retry_attempts} attempts: {exc}'
            )
            self.alerter(message)
            raise

    @staticmethod
    def _default_alerter(message: str) -> None:
        """Emit a scheduler alert through the standard logger."""
        logger.error(message)

    @staticmethod
    def shutdown(scheduler: BackgroundScheduler) -> None:
        """Stop the APScheduler instance when it is running."""
        if scheduler.state != STATE_STOPPED:
            scheduler.shutdown(wait=False)
