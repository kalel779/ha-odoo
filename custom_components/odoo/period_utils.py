"""Compute date boundaries for each period, in Home Assistant's local time."""
from __future__ import annotations

from datetime import datetime, timedelta

import homeassistant.util.dt as dt_util

from .const import (
    PERIOD_MONTH,
    PERIOD_QUARTER,
    PERIOD_TODAY,
    PERIOD_WEEK,
    PERIOD_YEAR,
    PERIOD_YESTERDAY,
)

ODOO_DT_FORMAT = "%Y-%m-%d %H:%M:%S"


def _start_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def get_period_bounds(period: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return (start, end) in local time for a given period.

    'end' is exclusive (upper bound = now, or next midnight for 'yesterday').
    """
    now = now or dt_util.now()
    today_start = _start_of_day(now)

    if period == PERIOD_TODAY:
        return today_start, now

    if period == PERIOD_YESTERDAY:
        yesterday_start = today_start - timedelta(days=1)
        return yesterday_start, today_start

    if period == PERIOD_WEEK:
        week_start = today_start - timedelta(days=today_start.weekday())
        return week_start, now

    if period == PERIOD_MONTH:
        month_start = today_start.replace(day=1)
        return month_start, now

    if period == PERIOD_QUARTER:
        quarter = (now.month - 1) // 3
        quarter_first_month = quarter * 3 + 1
        quarter_start = today_start.replace(month=quarter_first_month, day=1)
        return quarter_start, now

    if period == PERIOD_YEAR:
        year_start = today_start.replace(month=1, day=1)
        return year_start, now

    raise ValueError(f"Unknown period: {period}")


def to_odoo_utc(dt: datetime) -> str:
    """Convert a local HA datetime to the naive UTC format expected by Odoo."""
    utc_dt = dt_util.as_utc(dt)
    return utc_dt.strftime(ODOO_DT_FORMAT)


def period_domain(period: str, date_field: str, now: datetime | None = None) -> list:
    """Build an Odoo domain [(date_field, '>=', ...), (date_field, '<', ...)]."""
    start, end = get_period_bounds(period, now)
    return [
        (date_field, ">=", to_odoo_utc(start)),
        (date_field, "<", to_odoo_utc(end)),
    ]
