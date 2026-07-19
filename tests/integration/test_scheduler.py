"""Integration tests for scheduler configuration and job wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from scheduler.service import SchedulerService, load_scheduler_jobs, load_scheduler_settings


def test_scheduler_loaders_parse_yaml_files(tmp_path: Path) -> None:
    """Scheduler settings and job definitions should load from YAML files."""
    settings_path = tmp_path / "settings.yaml"
    jobs_path = tmp_path / "scheduler_jobs.yaml"
    settings_path.write_text(
        yaml.safe_dump(
            {
                "scheduler": {
                    "timezone": "Asia/Shanghai",
                    "jobstore": "memory",
                    "jobs_path": str(jobs_path),
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    jobs_path.write_text(
        yaml.safe_dump(
            {
                "jobs": [
                    {
                        "id": "incremental_update",
                        "target": "update_all",
                        "trigger": "cron",
                        "cron": {"day_of_week": "mon-fri", "hour": 18, "minute": 5},
                        "kwargs": {"trade_date": "2024-02-29", "ts_codes": ["000001.SZ"]},
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    settings = load_scheduler_settings(settings_path)
    jobs = load_scheduler_jobs(jobs_path)

    assert settings.timezone == "Asia/Shanghai"
    assert settings.jobs_path == jobs_path
    assert settings.retry_attempts == 3
    assert settings.retry_min_wait == 1
    assert settings.retry_max_wait == 8
    assert jobs[0].job_id == "incremental_update"
    assert jobs[0].enabled is True
    assert jobs[0].target == "update_all"
    assert jobs[0].cron == {"day_of_week": "mon-fri", "hour": 18, "minute": 5}
    assert jobs[0].kwargs == {"trade_date": "2024-02-29", "ts_codes": ["000001.SZ"]}


def test_scheduler_service_registers_jobs_and_runs_selected_job(tmp_path: Path) -> None:
    """Scheduler service should register cron jobs and dispatch them via the target registry."""
    settings_path = tmp_path / "settings.yaml"
    jobs_path = tmp_path / "scheduler_jobs.yaml"
    settings_path.write_text(
        yaml.safe_dump(
            {
                "scheduler": {
                    "timezone": "Asia/Shanghai",
                    "jobstore": "memory",
                    "jobs_path": str(jobs_path),
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    jobs_path.write_text(
        yaml.safe_dump(
            {
                "jobs": [
                    {
                        "id": "incremental_update",
                        "target": "update_all",
                        "trigger": "cron",
                        "cron": {"day_of_week": "mon-fri", "hour": 18, "minute": 5},
                        "kwargs": {"trade_date": "2024-02-29", "ts_codes": ["000001.SZ"]},
                    },
                    {
                        "id": "full_load_weekend",
                        "target": "full_load_all",
                        "trigger": "cron",
                        "cron": {"day_of_week": "sat", "hour": 9, "minute": 0},
                        "kwargs": {"ts_codes": ["000001.SZ"], "minute_ts_code": "000001.SZ"},
                    },
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    calls: list[tuple[str, dict[str, Any]]] = []

    def update_all(**kwargs: Any) -> dict[str, int]:
        calls.append(("update_all", kwargs))
        return {"update": 1}

    def full_load_all(**kwargs: Any) -> dict[str, int]:
        calls.append(("full_load_all", kwargs))
        return {"full": 1}

    service = SchedulerService(
        settings_path=settings_path,
        registry={"update_all": update_all, "full_load_all": full_load_all},
    )

    scheduler = service.create_scheduler()
    service.register_jobs(scheduler)

    jobs = {job.id: job for job in scheduler.get_jobs()}
    assert set(jobs) == {"incremental_update", "full_load_weekend"}
    assert jobs["incremental_update"].kwargs == {
        "job_id": "incremental_update",
        "trade_date": "2024-02-29",
        "ts_codes": ["000001.SZ"],
    }
    assert jobs["full_load_weekend"].kwargs == {
        "job_id": "full_load_weekend",
        "ts_codes": ["000001.SZ"],
        "minute_ts_code": "000001.SZ",
    }

    result = service.run_job_now("incremental_update")
    full_result = service.run_job_now("full_load_weekend")

    assert result == {"update": 1}
    assert full_result == {"full": 1}
    assert calls == [
        (
            "update_all",
            {"trade_date": "2024-02-29", "ts_codes": ["000001.SZ"]},
        ),
        (
            "full_load_all",
            {"ts_codes": ["000001.SZ"], "minute_ts_code": "000001.SZ"},
        ),
    ]
    scheduler.shutdown(wait=False)


def test_scheduler_service_skips_disabled_jobs_and_alerts_after_retries(tmp_path: Path) -> None:
    """Disabled jobs should not be registered, and failing jobs should retry then alert."""
    settings_path = tmp_path / "settings.yaml"
    jobs_path = tmp_path / "scheduler_jobs.yaml"
    settings_path.write_text(
        yaml.safe_dump(
            {
                "scheduler": {
                    "timezone": "Asia/Shanghai",
                    "jobstore": "memory",
                    "jobs_path": str(jobs_path),
                    "retry_attempts": 2,
                    "retry_min_wait": 1,
                    "retry_max_wait": 1,
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    jobs_path.write_text(
        yaml.safe_dump(
            {
                "jobs": [
                    {
                        "id": "enabled_job",
                        "target": "update_all",
                        "trigger": "cron",
                        "cron": {"day_of_week": "mon-fri", "hour": 18, "minute": 5},
                        "kwargs": {"trade_date": "2024-02-29"},
                        "enabled": True,
                    },
                    {
                        "id": "disabled_job",
                        "target": "full_load_all",
                        "trigger": "cron",
                        "cron": {"day_of_week": "sat", "hour": 9, "minute": 0},
                        "kwargs": {"ts_codes": ["000001.SZ"], "minute_ts_code": "000001.SZ"},
                        "enabled": False,
                    },
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    attempts = 0
    alerts: list[str] = []

    def failing_job(**kwargs: Any) -> dict[str, int]:
        nonlocal attempts
        attempts += 1
        raise RuntimeError(f"boom {kwargs['trade_date']}")

    service = SchedulerService(
        settings_path=settings_path,
        registry={"update_all": failing_job, "full_load_all": lambda **_: {"full": 1}},
        alerter=alerts.append,
    )

    scheduler = service.create_scheduler()
    service.register_jobs(scheduler)

    jobs = {job.id: job for job in scheduler.get_jobs()}
    assert set(jobs) == {"enabled_job"}

    with pytest.raises(RuntimeError, match="boom 2024-02-29"):
        service.run_job_now("enabled_job")

    assert attempts == 2
    assert alerts == ["Scheduler job enabled_job failed after 2 attempts: boom 2024-02-29"]

    scheduler.shutdown(wait=False)
