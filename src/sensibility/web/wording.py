"""Small pieces of page text shared by settings, welcome and the shell."""

from __future__ import annotations

from datetime import datetime

from sensibility.clock import local_date
from sensibility.models import Role


def a_role(role: Role) -> str:
    """ "an owner", "an editor", "a viewer"."""
    return ("an " if role.value[0] in "aeiou" else "a ") + role.value


def day_text(instant: datetime, zone: str) -> str:
    """ "Oct 20": the day `instant` falls on in the viewer's zone."""
    day = local_date(instant, zone)
    return f"{day:%b} {day.day}"
