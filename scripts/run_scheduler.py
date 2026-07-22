"""APScheduler service entrypoint for recurring data jobs.

Loads job definitions from config/scheduler_jobs.yaml and runs them
on a cron schedule via BackgroundScheduler.

Usage:
    .venv/bin/python scripts/run_scheduler.py
    .venv/bin/python scripts/run_scheduler.py --run-now bac_fill_day
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import json
import time
from datetime import date, datetime, timezone

import duckdb
import yaml

try:
    from apscheduler.schedulers.background import BackgroundScheduler
except ImportError:
    from apscheduler.schedulers.blocking import BlockingScheduler as BackgroundScheduler

from utils.logger import get_logger

logger = get_logger("scheduler")

# ── targets ──────────────────────────────────────────────────────
# Each target name maps to a Python module.script:run_function reference.
# The function receives **kwargs and returns a dict.
TARGETS: dict[str, str] = {
    "backfill_day": "scripts.backfill_day:run_job",
    "full_load_all": "scripts.full_load_all:run_job",
    "update_all": "scripts.update_all:run_job",
    "batch_scan": "scripts.batch_scan:run_job",
    "signal_events": "scripts.populate_signal_events:run",
    "update_minute_bar": "scripts.update_minute_bar:run_job",
    "factor_compute": "scripts.run_factor_compute:run_job",
    "risk_check": "scripts.run_risk_check:main",
    "feishu_notify": "scripts.feishu_signal_notify:main",
    "auto_factor_mine": "scripts.auto_factor_mine:main",
    "build_positions": "scripts.build_positions:main",
    "portfolio_daily": "trading.portfolio:run_job",
    "jq_live": "scripts.run_jq_live:run_job",
    "intraday": "scripts.run_intraday_collect:main",
    "agent_analyze": "scripts.run_agent_analyze:main",
}


def _resolve_target(target: str):
    """Import and return a callable from module.target string.

    Uses importlib.reload() if the module is already cached, so script changes
    are picked up without a scheduler restart.
    """
    import importlib
    import sys

    if target not in TARGETS:
        raise ValueError(f"Unknown scheduler target: {target}")
    mod_path, func_name = TARGETS[target].split(":")
    module = importlib.import_module(mod_path)
    # Reload if the module was previously cached (handles hot-fix scenario)
    if mod_path in sys.modules:
        module = importlib.reload(sys.modules[mod_path])
    return getattr(module, func_name)


def _append_job_log(job_id: str, status: str, duration: float, error: str = ""):
    """Write a job execution record to data_update_log in PG."""
    try:
        from config.settings import settings
        import psycopg
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        started = now.replace(second=max(0, now.second - int(duration)))
        conn = psycopg.connect(settings.pg_dsn)
        conn.execute(
            """INSERT INTO data_update_log
               (table_name, source, update_type, start_date, end_date,
                status, error_msg, started_at, finished_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            [job_id, "scheduler", "cron",
             started.date(), started.date(),
             status, error, started, now],
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Failed to write update log: {e}")


def _execute_job(job_id: str, target: str, retry_attempts: int = 2):
    """Execute one scheduled job with retry."""
    func = _resolve_target(target)
    for attempt in range(1, retry_attempts + 1):
        t0 = time.monotonic()
        try:
            logger.info(f"[{job_id}] executing (attempt {attempt}/{retry_attempts})")
            if target == "signal_events":
                result = func()
            else:
                result = func()
            duration = time.monotonic() - t0
            logger.info(f"[{job_id}] done in {duration:.1f}s — {json.dumps(result, default=str)}")
            _append_job_log(job_id, "success", duration)
            return result
        except Exception as e:
            duration = time.monotonic() - t0
            logger.error(f"[{job_id}] attempt {attempt} failed ({duration:.1f}s): {e}")
            if attempt == retry_attempts:
                _append_job_log(job_id, "failed", duration, str(e))
                logger.error(f"[{job_id}] FAILED after {retry_attempts} attempts: {e}")
                raise
            time.sleep(60 * attempt)


def parse_args():
    p = argparse.ArgumentParser(description="Data scheduler service")
    p.add_argument("--config", default="config/scheduler_jobs.yaml",
                   help="Path to jobs YAML config")
    p.add_argument("--run-now", default=None, help="Run one job by ID immediately and exit")
    p.add_argument("--list", action="store_true", help="List configured jobs and exit")
    return p.parse_args()


def main():
    args = parse_args()

    # Load config
    config_path = Path(args.config)
    if not config_path.exists():
        logger.error(f"Config not found: {config_path}")
        return 1

    cfg = yaml.safe_load(config_path.read_text()) or {}
    scheduler_cfg = cfg.get("scheduler", {})
    jobs = cfg.get("jobs", [])

    if args.list:
        print(f"Timezone: {scheduler_cfg.get('timezone', 'Asia/Shanghai')}")
        print(f"Enabled jobs ({sum(1 for j in jobs if j.get('enabled', True))}/{len(jobs)}):")
        for j in jobs:
            enabled = "✅" if j.get("enabled", True) else "❌"
            cron = j.get("cron", {})
            print(f"  {enabled} {j['id']:<30s} target={j.get('target','?'):20s} "
                  f"cron={str(cron.get('day_of_week','*')):>8s} @ {str(cron.get('hour',0)):>5s}:{str(cron.get('minute',0)):0>2s}")
        return 0

    if args.run_now:
        job = next((j for j in jobs if j["id"] == args.run_now), None)
        if not job:
            logger.error(f"Job not found: {args.run_now}")
            return 1
        retry = scheduler_cfg.get("retry_attempts", 2)
        _execute_job(job["id"], job["target"], retry)
        return 0

    # Start background scheduler
    tz = scheduler_cfg.get("timezone", "Asia/Shanghai")
    sched = BackgroundScheduler(timezone=tz)

    for job in jobs:
        if not job.get("enabled", True):
            logger.info(f"Skip disabled: {job['id']}")
            continue
        cron = job["cron"]
        target = job.get("target", job["id"])
        retry = scheduler_cfg.get("retry_attempts", 2)
        sched.add_job(
            _execute_job,
            trigger="cron",
            id=job["id"],
            args=[job["id"], target, retry],
            replace_existing=True,
            day_of_week=cron.get("day_of_week", "*"),
            hour=cron.get("hour", "0"),
            minute=cron.get("minute", "0"),
        )
        logger.info(f"Registered: {job['id']} → {target} "
                     f"@ {cron.get('day_of_week','*')} {cron.get('hour',0):02d}:{cron.get('minute',0):02d}")

    sched.start()
    logger.info(f"Scheduler started ({len(jobs)} jobs, timezone={tz})")

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        sched.shutdown()

    return 0


if __name__ == "__main__":
    sys.exit(main())
