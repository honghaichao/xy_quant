# ruff: noqa: E402
"""Scheduler process entrypoint for P0.10 orchestration."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import time
from argparse import Namespace

from scheduler import SchedulerService
from utils.logger import get_logger

logger = get_logger('run_scheduler')


def parse_args() -> Namespace:
    """Parse CLI arguments for the scheduler runner."""
    parser = argparse.ArgumentParser(description='Run the P0.10 scheduler service.')
    parser.add_argument('--settings-path', default='config/settings.yaml')
    return parser.parse_args()


def wait_for_shutdown(_scheduler: object) -> None:
    """Keep the process alive until interrupted by the user or supervisor."""
    while True:
        time.sleep(3600)


def main() -> object:
    """Start the scheduler service and keep the process alive until interrupted."""
    args = parse_args()
    logger.info('Starting scheduler service.')
    service = SchedulerService(settings_path=args.settings_path)
    scheduler = service.start()
    try:
        wait_for_shutdown(scheduler)
    except KeyboardInterrupt:
        logger.info('Scheduler service stopped by user interrupt.')
    finally:
        service.shutdown(scheduler)
        logger.info('Scheduler service shutdown complete.')
    return scheduler


if __name__ == '__main__':
    main()
