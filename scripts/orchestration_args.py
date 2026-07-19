"""Argument normalization helpers for scheduler-driven orchestration entrypoints."""

from __future__ import annotations

from argparse import Namespace
from collections.abc import Iterable
from copy import deepcopy
from datetime import date
from typing import Any

_DATE_FIELDS = frozenset({"trade_date", "start_date", "end_date", "holdertrade_ann_date"})
_LIST_FIELDS = frozenset({"ts_codes", "index_codes", "concept_codes", "industry_codes"})


def _parse_date_like(value: object) -> object:
    if isinstance(value, date) or value is None:
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    return value


def _parse_list_like(value: object) -> object:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, dict)):
        return list(value)
    return value


def normalize_orchestration_namespace(args: Namespace) -> Namespace:
    """Return a copy of orchestration args with scheduler-friendly scalar types parsed."""
    values = deepcopy(vars(args))
    for field in _DATE_FIELDS:
        if field in values:
            values[field] = _parse_date_like(values[field])
    for field in _LIST_FIELDS:
        if field in values:
            values[field] = _parse_list_like(values[field])
    return Namespace(**values)


def normalize_orchestration_kwargs(kwargs: dict[str, Any]) -> Namespace:
    """Build a normalized namespace from scheduler-provided kwargs."""
    return normalize_orchestration_namespace(Namespace(**kwargs))
