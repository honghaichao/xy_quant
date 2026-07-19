"""Shared orchestration definitions for full-load, update, bootstrap, and real-indicator flows."""

from __future__ import annotations

import importlib
from argparse import Namespace
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast


@dataclass(frozen=True)
class JobSpec:
    name: str
    kwargs_builder: Callable[[Namespace], dict[str, object]]


def _minute_bar_kwargs(args: Namespace) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "start_date": args.start_date,
        "end_date": args.end_date,
        "freq": getattr(args, "minute_freq", "5min"),
    }
    minute_ts_code = getattr(args, "minute_ts_code", None)
    if minute_ts_code is not None:
        kwargs["ts_code"] = minute_ts_code
    else:
        kwargs["ts_codes"] = args.ts_codes
    return kwargs


FULL_LOAD_JOB_SPECS: tuple[JobSpec, ...] = (
    JobSpec("basic", lambda args: {}),
    JobSpec("calendar", lambda args: {"start_date": args.start_date, "end_date": args.end_date}),
    JobSpec(
        "daily_bar",
        lambda args: {"ts_codes": args.ts_codes, "start_date": args.start_date, "end_date": args.end_date},
    ),
    JobSpec("minute_bar", _minute_bar_kwargs),
    JobSpec(
        "adj_factor",
        lambda args: {"ts_codes": args.ts_codes, "start_date": args.start_date, "end_date": args.end_date},
    ),
    JobSpec(
        "daily_basic",
        lambda args: {"ts_codes": args.ts_codes, "start_date": args.start_date, "end_date": args.end_date},
    ),
    JobSpec(
        "index_daily",
        lambda args: {"index_codes": args.index_codes, "start_date": args.start_date, "end_date": args.end_date},
    ),
    JobSpec("limit_list", lambda args: {"trade_date": args.trade_date}),
    JobSpec("money_flow", lambda args: {"trade_date": args.trade_date}),
    JobSpec("top_list", lambda args: {"trade_date": args.trade_date}),
    JobSpec("margin", lambda args: {"trade_date": args.trade_date}),
    JobSpec("hk_hold", lambda args: {"trade_date": args.trade_date}),
    JobSpec("suspend", lambda args: {"trade_date": args.trade_date}),
    JobSpec(
        "member",
        lambda args: {
            "concept_codes": args.concept_codes,
            "industry_codes": args.industry_codes,
            "index_codes": args.index_codes,
            "trade_date": args.trade_date,
        },
    ),
    JobSpec(
        "holdertrade",
        lambda args: (
            {"ann_date": getattr(args, "holdertrade_ann_date", None) or args.trade_date}
            | (
                {"ts_code": getattr(args, "holdertrade_ts_code", None)}
                if getattr(args, "holdertrade_ts_code", None) is not None
                else {}
            )
        ),
    ),
    JobSpec(
        "finance",
        lambda args: {"ts_codes": args.ts_codes, "start_date": args.start_date, "end_date": args.end_date},
    ),
)

INCREMENTAL_JOB_SPECS: tuple[JobSpec, ...] = (
    JobSpec("basic", lambda args: {}),
    JobSpec(
        "daily",
        lambda args: {"trade_date": args.trade_date, "ts_codes": args.ts_codes, "index_codes": args.index_codes},
    ),
    JobSpec(
        "member",
        lambda args: {
            "concept_codes": args.concept_codes,
            "industry_codes": args.industry_codes,
            "index_codes": args.index_codes,
            "trade_date": args.trade_date,
        },
    ),
    JobSpec(
        "finance",
        lambda args: {"ts_codes": args.ts_codes, "start_date": args.start_date, "end_date": args.end_date},
    ),
    JobSpec("suspend", lambda args: {"trade_date": args.trade_date}),
)

FOUNDATION_INIT_JOB_SPECS: tuple[JobSpec, ...] = (
    JobSpec("basic", lambda args: {}),
    JobSpec("calendar", lambda args: {"start_date": args.start_date, "end_date": args.end_date}),
)

REAL_INDICATOR_JOB_SPECS: tuple[JobSpec, ...] = (
    JobSpec("daily_bar", lambda args: {"ts_codes": args.ts_codes, "start_date": args.start_date, "end_date": args.end_date}),
    JobSpec("daily_basic", lambda args: {"ts_codes": args.ts_codes, "start_date": args.start_date, "end_date": args.end_date}),
    JobSpec("adj_factor", lambda args: {"ts_codes": args.ts_codes, "start_date": args.start_date, "end_date": args.end_date}),
    JobSpec("index_daily", lambda args: {"index_codes": args.index_codes, "start_date": args.start_date, "end_date": args.end_date}),
)


def run_subjob(job_name: str, *, script_prefix: str, **kwargs: object) -> dict[str, int]:
    module = importlib.import_module(f"scripts.{script_prefix}_{job_name}")
    return cast(dict[str, int], module.run_job(**kwargs))


def run_defined_jobs(*, args: Namespace, jobs: tuple[JobSpec, ...], script_prefix: str) -> dict[str, dict[str, int]]:
    results: dict[str, dict[str, int]] = {}
    for job in jobs:
        results[job.name] = run_subjob(job.name, script_prefix=script_prefix, **job.kwargs_builder(args))
    return results
