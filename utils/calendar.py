"""交易日历通用工具。"""

from datetime import date, datetime, timedelta

WEEKDAY_COUNT = 5


def ensure_date(value: str | date | datetime) -> date:
    """Convert supported input types to a date object."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(value, "%Y-%m-%d").date()


def date_range(start_date: date, end_date: date) -> list[date]:
    """Return an inclusive date range."""
    if end_date < start_date:
        raise ValueError("end_date must be greater than or equal to start_date")

    total_days = (end_date - start_date).days
    return [start_date + timedelta(days=offset) for offset in range(total_days + 1)]


def is_weekday(trade_date: date) -> bool:
    """Return whether a date falls on a weekday."""
    return trade_date.weekday() < WEEKDAY_COUNT
