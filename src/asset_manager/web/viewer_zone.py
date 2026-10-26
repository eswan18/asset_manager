"""Today in the viewer's time zone, for pages and API routes alike.

base.html stores the browser's zone in the `tz` cookie on every page load,
so server-rendered pages and plain form posts see it. An API client may name
its zone in an `X-Timezone` header instead; that wins over the cookie, and an
unknown one is a 400 (a client that names a zone means it). A missing or
unknown cookie falls back silently to the TIMEZONE default, as on the first
page load, before the script has set it.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from asset_manager.clock import is_known_zone, today, zone_for

TZ_COOKIE = "tz"
TZ_HEADER = "X-Timezone"


def _today(request: Request, explicit: str | None) -> date:
    if explicit is not None and not is_known_zone(explicit):
        raise HTTPException(
            status_code=400, detail=f"{explicit!r} is not a known time zone"
        )
    return today(zone_for(explicit, request.cookies.get(TZ_COOKIE)))


def today_for(request: Request) -> date:
    """Today for this request, for code that has the request but is not a
    route (helpers shared by several routes)."""
    return _today(request, request.headers.get(TZ_HEADER))


def _today_dependency(
    request: Request,
    x_timezone: Annotated[
        str | None,
        Header(
            alias=TZ_HEADER,
            description=(
                "IANA zone (e.g. America/Los_Angeles) that decides which "
                "calendar day today is. Wins over the browser's `tz` cookie; "
                "without either, the server default is used."
            ),
        ),
    ] = None,
) -> date:
    return _today(request, x_timezone)


Today = Annotated[date, Depends(_today_dependency)]
