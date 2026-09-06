"""Snapshot dates are dated in a configured timezone, not the pod's clock.

Pods run in UTC; if we date snapshots with `date.today()`, an evening Save
(or a Sheets import) in Central time gets tomorrow's date. `today()` instead
converts the current instant into the configured local zone before taking
the date.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from .config import get_settings


def local_date(now: datetime, tz: str) -> date:
    """The calendar date `now` falls on in `tz`. `now` must be timezone-aware."""
    return now.astimezone(ZoneInfo(tz)).date()


def today() -> date:
    return local_date(datetime.now(timezone.utc), get_settings().timezone)
