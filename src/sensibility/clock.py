"""Which calendar day "today" is: the day in the viewer's time zone.

Pods run in UTC; if we date snapshots with `date.today()`, an evening Save
in Central time gets tomorrow's date. `today(tz)` instead converts the
current instant into the viewer's zone before taking the date. The zone only
ever chooses which day a save or a retirement is dated, so it belongs to the
person acting, not the workspace: the browser reports it in a cookie, an API
client may name it, and `zone_for` picks one, falling back to TIMEZONE.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from functools import cache
from zoneinfo import ZoneInfo, available_timezones

from .config import get_settings


def now() -> datetime:
    """The current instant, in UTC. Tests replace this to freeze the clock."""
    return datetime.now(timezone.utc)


def local_date(instant: datetime, tz: str) -> date:
    """The calendar date `instant` falls on in `tz`. It must be timezone-aware."""
    return instant.astimezone(ZoneInfo(tz)).date()


def today(tz: str) -> date:
    return local_date(now(), tz)


def default_timezone() -> str:
    """The zone used when the viewer's is unknown (the TIMEZONE setting)."""
    return get_settings().timezone


@cache
def _known_zones() -> frozenset[str]:
    return frozenset(available_timezones())


def is_known_zone(tz: str) -> bool:
    """An IANA zone name ZoneInfo can load. Checked against the list rather
    than by loading it, so a value like `../etc/passwd` never reaches the
    file system."""
    return tz in _known_zones()


def zone_for(explicit: str | None, cookie: str | None) -> str:
    """The zone a request's "today" is in: `explicit` (already validated by
    the caller), else the browser's cookie if it names a known zone, else the
    default. A bad or missing cookie falls back silently."""
    if explicit is not None:
        return explicit
    if cookie and is_known_zone(cookie):
        return cookie
    return default_timezone()
