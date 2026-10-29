"""Today in the viewer's time zone, for API routes.

The React app names the browser's zone in an `X-Timezone` header on every
request, as any API client may. An unknown zone is a 400 (a client that
names a zone means it); without the header, today is in the TIMEZONE
default.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import Depends, Header, HTTPException

from sensibility.clock import default_timezone, is_known_zone, today

TZ_HEADER = "X-Timezone"


def _today_dependency(
    x_timezone: Annotated[
        str | None,
        Header(
            alias=TZ_HEADER,
            description=(
                "IANA zone (e.g. America/Los_Angeles) that decides which "
                "calendar day today is. Without it, the server default is used."
            ),
        ),
    ] = None,
) -> date:
    if x_timezone is None:
        return today(default_timezone())
    if not is_known_zone(x_timezone):
        raise HTTPException(
            status_code=400, detail=f"{x_timezone!r} is not a known time zone"
        )
    return today(x_timezone)


Today = Annotated[date, Depends(_today_dependency)]
