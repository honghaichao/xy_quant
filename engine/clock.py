"""时间槽与成交价语义 — 回测撮合规则的唯一权威定义（实盘 settle 重放同一套）。

映射：
  - < 09:30（'before_open'、'9:05'）：盘前批，函数产生的订单排队到开盘批成交
  - 09:30-09:35、'open'：开盘批，成交价 = 9:31 首根分钟 close → 回落日线 open
  - 09:36-14:54：盘中批，成交价 = 该时点分钟 close → 回落日线 close
  - >= 14:55、'close'：收盘批，成交价 = 日线 close
  - 'after_close'：只跑函数，下单被拒绝
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

# fill_kind 枚举
FILL_QUEUE_TO_OPEN = "queue_to_open"   # 盘前：订单排队
FILL_OPEN = "open"                     # 开盘价（分钟 9:31 → 日线 open）
FILL_MINUTE = "minute"                 # 盘中分钟价（→ 日线 close 回落）
FILL_CLOSE = "close"                   # 收盘价
FILL_REJECT = "reject"                 # 收盘后拒单

_NAMED = {
    "before_open": 9 * 60 + 5,     # 09:05
    "open": 9 * 60 + 30,           # 09:30
    "close": 15 * 60 + 0,          # 15:00
    "after_close": 15 * 60 + 30,   # 15:30
}


@dataclass
class Slot:
    """一个调度时间槽。"""

    raw: str
    minutes: int                   # 从 0:00 起的分钟数，排序键
    fill_kind: str
    hhmm: str = ""                 # 盘中槽的 "HH:MM"（供 load_minute_bar_at）


@dataclass
class ScheduledTask:
    """run_daily/run_weekly/run_monthly 注册的任务。"""

    func: Callable
    slot: Slot
    freq: str = "daily"            # daily | weekly | monthly
    weekday: int | None = None     # weekly: 0=周一
    monthday: int | None = None    # monthly: 1-31
    seq: int = field(default=0)    # 注册顺序（同刻稳定排序）


def parse_time(raw: str | None) -> Slot:
    """解析聚宽时间串为 Slot。None 等价 'open'。"""
    if raw is None:
        raw = "open"
    raw = str(raw).strip()

    if raw in _NAMED:
        minutes = _NAMED[raw]
    else:
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", raw)
        if not m:
            raise ValueError(f"无法解析 run_daily 时间: {raw!r}"
                             "（支持 'HH:MM'/'open'/'close'/'before_open'/'after_close'）")
        minutes = int(m.group(1)) * 60 + int(m.group(2))

    hhmm = f"{minutes // 60:02d}:{minutes % 60:02d}"
    if raw == "after_close" or minutes > 15 * 60:
        kind = FILL_REJECT
    elif minutes < 9 * 60 + 30:
        kind = FILL_QUEUE_TO_OPEN
    elif minutes <= 9 * 60 + 35:
        kind = FILL_OPEN
    elif minutes < 14 * 60 + 55:
        kind = FILL_MINUTE
    else:
        kind = FILL_CLOSE
    return Slot(raw=raw, minutes=minutes, fill_kind=kind, hhmm=hhmm)


def sort_tasks(tasks: list[ScheduledTask]) -> list[ScheduledTask]:
    """按 (时间, 注册序) 稳定排序。"""
    return sorted(tasks, key=lambda t: (t.slot.minutes, t.seq))
