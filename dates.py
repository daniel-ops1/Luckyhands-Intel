"""Shared date helpers.

The Intel Daily brief is for US stakeholders, so all date keys, file names,
and brief headers use US Eastern time (America/New_York), not UTC.

A pipeline run kicked off at 9pm Pacific writes a brief stamped with the
Eastern date for that same business day. Cache keys also use Eastern time
so the daily refresh aligns with the brief publish day.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

US_TZ = ZoneInfo("America/New_York")


def us_date() -> str:
    """YYYY-MM-DD in US Eastern. Used as the day key for caches."""
    return datetime.now(tz=US_TZ).strftime("%Y-%m-%d")


def us_date_long() -> str:
    """Pretty long form for brief headers, e.g. June 29, 2026."""
    return datetime.now(tz=US_TZ).strftime("%B %d, %Y")


def us_date_slug() -> str:
    """Underscored slug for file names, e.g. 2026_06_29."""
    return datetime.now(tz=US_TZ).strftime("%Y_%m_%d")


def us_year() -> int:
    return datetime.now(tz=US_TZ).year


def us_weekday() -> int:
    """Monday is 0, Sunday is 6."""
    return datetime.now(tz=US_TZ).weekday()


def us_date_iso_minus(days: int) -> str:
    """ISO date in US Eastern, N days back."""
    from datetime import timedelta
    return (datetime.now(tz=US_TZ) - timedelta(days=days)).strftime("%Y-%m-%d")
