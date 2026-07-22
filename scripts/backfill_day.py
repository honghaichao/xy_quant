"""Backfill all P0 data for a single specified trading day."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import json
from argparse import Namespace
from datetime import date
from pathlib import Path

from data.source.factory import get_data_source
from data.source.strategy import SourceSelectionPolicy
from scripts.orchestration import INCREMENTAL_JOB_SPECS, run_subjob as orchestration_run_subjob
from scripts.orchestration_args import normalize_orchestration_namespace
from scripts.update_helpers import (
    add_concept_codes_argument,
    add_index_codes_argument,
    add_industry_codes_argument,
    add_progress_file_argument,
    add_trade_date_argument,
    add_ts_codes_argument,
    build_logger,
)
from utils.exception import PartialUpdateError

logger = build_logger('backfill_day')
DEFAULT_PROGRESS_FILE = PROJECT_ROOT / 'logs' / 'backfill_day_progress.jsonl'
DEFAULT_INDEX_CODES = ['000001.SH', '399001.SZ', '399006.SZ', '000300.SH', '000905.SH']


def _default_ts_codes() -> list[str]:
    return []


def _default_index_codes() -> list[str]:
    return list(DEFAULT_INDEX_CODES)


def _latest_trade_date_from_remote_tushare() -> date | None:
    policy = SourceSelectionPolicy(factory=get_data_source)
    source = policy.resolve('trade_calendar')
    frame = source.fetch_trade_calendar(start_date=date(1900, 1, 1), end_date=date(2100, 12, 31))
    if getattr(frame, 'empty', True):
        return None
    if 'is_open' in frame.columns:
        frame = frame.loc[frame['is_open'].astype(str) == '1']
    if getattr(frame, 'empty', True):
        return None
    if 'cal_date' not in frame.columns:
        return None
    raw = frame.iloc[-1]['cal_date']
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw
    text = str(raw)
    if len(text) == 8 and text.isdigit():
        return date.fromisoformat(f'{text[:4]}-{text[4:6]}-{text[6:8]}')
    return date.fromisoformat(text)


def _normalize_args(args: Namespace) -> Namespace:
    normalized = normalize_orchestration_namespace(args)
    if getattr(normalized, 'trade_date', None) is None:
        normalized.trade_date = _latest_trade_date_from_remote_tushare()
    if getattr(normalized, 'trade_date', None) is None:
        raise ValueError('Unable to determine latest trade date from remote Tushare trade calendar.')
    if getattr(normalized, 'start_date', None) is None:
        normalized.start_date = normalized.trade_date
    if getattr(normalized, 'end_date', None) is None:
        normalized.end_date = normalized.trade_date
    if not getattr(normalized, 'ts_codes', None):
        normalized.ts_codes = _default_ts_codes()
    if not getattr(normalized, 'index_codes', None):
        normalized.index_codes = _default_index_codes()
    if not getattr(normalized, 'concept_codes', None):
        normalized.concept_codes = []
    if not getattr(normalized, 'industry_codes', None):
        normalized.industry_codes = []
    return normalized


def parse_args(argv: list[str] | None = None) -> Namespace:
    parser = argparse.ArgumentParser(description='Backfill all P0 data for one trading day.')
    add_trade_date_argument(parser, required=False)
    parser.add_argument('--start-date', dest='start_date', type=date.fromisoformat, required=False)
    parser.add_argument('--end-date', dest='end_date', type=date.fromisoformat, required=False)
    add_ts_codes_argument(parser, required=False)
    add_index_codes_argument(parser, required=False)
    add_concept_codes_argument(parser, required=False)
    add_industry_codes_argument(parser, required=False)
    add_progress_file_argument(parser, default=str(DEFAULT_PROGRESS_FILE))
    return parser.parse_args(argv)


def run_subjob(job_name: str, **kwargs: object) -> dict[str, int]:
    return orchestration_run_subjob(job_name, script_prefix='update', **kwargs)


def _append_progress_record(progress_file: str | Path | None, record: dict[str, object]) -> None:
    if not progress_file:
        return
    path = Path(progress_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + '\n')


def run_defined_jobs(args: Namespace) -> dict[str, dict[str, int]]:
    results: dict[str, dict[str, int]] = {}
    failures: dict[str, dict[str, object]] = {}
    progress_file = getattr(args, 'progress_file', None)

    for job in INCREMENTAL_JOB_SPECS:
        try:
            job_result = run_subjob(job.name, **job.kwargs_builder(args))
            results[job.name] = job_result
        except PartialUpdateError as exc:
            results[job.name] = exc.counts
            failures[job.name] = {'type': 'partial', 'message': str(exc), 'failures': exc.failures}
            logger.warning(f'Job {job.name} completed partially: {exc.failures}')
        except Exception as exc:  # noqa: BLE001
            results[job.name] = {}
            failures[job.name] = {'type': 'fatal', 'message': str(exc)}
            logger.exception(f'Job {job.name} failed during single-day backfill.')
        _append_progress_record(
            progress_file,
            {
                'job': job.name,
                'trade_date': getattr(args, 'trade_date', None).isoformat() if getattr(args, 'trade_date', None) else None,
                'result': results[job.name],
                'failure': failures.get(job.name),
            },
        )

    if failures:
        results['_failures'] = {name: 0 for name in failures}
    return results


def _run_from_args(args: Namespace) -> dict[str, dict[str, int]]:
    logger.info('Starting single-day backfill.')
    results = run_defined_jobs(_normalize_args(args))
    logger.info('Single-day backfill complete.')
    return results


def main(argv: list[str] | None = None) -> dict[str, dict[str, int]]:
    return _run_from_args(parse_args(argv))


def run_job(**kwargs: object) -> dict[str, dict[str, int]]:
    """调度器入口 — 带日线数据到达检测。

    问题：Tushare 日线通常在收盘后 17:30-20:00 到位，周一常延迟到 20:30+。
    调度器虽设了 20:30/20:45/21:00 三道路障，但若三次独立触发都撞上数据未到位，
    则当天全链路（信号→事件→因子→推送）全部落空，且无人工感知。

    修复：run_job 内对 daily 子任务做轮询重试，直到 daily_bar 拉回有效行数。
    只重跑 daily 子任务（不重复 basic/finance/member/suspend），间隔 120s，
    最多 12 次（合计 ~24 分钟），不会与下一次 cron 触发重叠。
    """
    import time as _time

    _MAX_DAILY_RETRIES = 12
    _DAILY_RETRY_WAIT = 120  # 秒

    args = Namespace(**kwargs)

    # ── 首次完整补数 ──
    result = _run_from_args(args)

    # ── 如果 daily_bar 为空，只对 daily 子任务做轮询重试 ──
    daily_count = result.get("daily", {}).get("daily_bar", 0)
    if daily_count and daily_count >= 100:
        return result

    trade_date = getattr(args, "trade_date", None)
    td_str = trade_date.isoformat() if trade_date else "today"
    logger.warning(
        f"daily_bar 仅 {daily_count} 行（{td_str}），Tushare 数据可能尚未到位，"
        f"开始轮询重试（最多 {_MAX_DAILY_RETRIES} 次，间隔 {_DAILY_RETRY_WAIT}s）"
    )

    from scripts.orchestration import INCREMENTAL_JOB_SPECS, run_subjob

    daily_spec = next((j for j in INCREMENTAL_JOB_SPECS if j.name == "daily"), None)
    if daily_spec is None:
        logger.error("INCREMENTAL_JOB_SPECS 中找不到 'daily' job，无法重试")
        return result

    for attempt in range(1, _MAX_DAILY_RETRIES + 1):
        _time.sleep(_DAILY_RETRY_WAIT)
        try:
            daily_result = run_subjob(daily_spec.name, **daily_spec.kwargs_builder(args))
            daily_count = daily_result.get("daily_bar", 0)
            result["daily"] = daily_result
        except Exception as exc:
            logger.warning(f"daily 子任务第 {attempt} 次重试异常: {exc}")
            continue

        if daily_count and daily_count >= 100:
            logger.info(f"daily_bar 数据第 {attempt} 次重试后到达 ({td_str}，{daily_count} 行)")
            return result
        logger.info(
            f"daily_bar 第 {attempt}/{_MAX_DAILY_RETRIES} 次重试仍为 {daily_count} 行，"
            f"{_DAILY_RETRY_WAIT}s 后重试..."
        )

    # 全部重试失败
    logger.error(
        f"daily_bar 重试 {_MAX_DAILY_RETRIES} 次后仍为 {daily_count} 行（{td_str}），"
        f"放弃。可能是非交易日或 Tushare 接口异常。信号扫描将跳过今日。"
    )
    return result


if __name__ == '__main__':
    main()
