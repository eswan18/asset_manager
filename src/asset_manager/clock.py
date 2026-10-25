"""Snapshots are dated in their workspace's time zone, not the pod's clock.

Pods run in UTC; if we date snapshots with `date.today()`, an evening Save
in Central time gets tomorrow's date. `today(tz)` instead converts the
current instant into the workspace's zone before taking the date. The zone
belongs to the workspace, not the person, so members in different zones
saving at the same moment get the same date.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from .config import get_settings


def local_date(now: datetime, tz: str) -> date:
    """The calendar date `now` falls on in `tz`. `now` must be timezone-aware."""
    return now.astimezone(ZoneInfo(tz)).date()


def today(tz: str) -> date:
    return local_date(datetime.now(timezone.utc), tz)


def default_timezone() -> str:
    """The zone a new workspace gets when none is given."""
    return get_settings().timezone
