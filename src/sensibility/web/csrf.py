"""CSRF defense for the JSON API.

The browser authenticates to /api/ with the session cookie, so another site
could try to make a visitor's browser send a write. Every mutating /api/
request (POST, PUT, PATCH, DELETE) must carry `X-Requested-With: sensibility`:
a cross-site form cannot set a header, and a cross-site fetch cannot send a
custom one without a CORS preflight, which this app never allows. Requests
without it get 403 `{"error": …}` before any route runs.

Reads are unaffected, as are the login flow's routes (outside /api/) and
/mcp, which takes bearer tokens, not cookies.
"""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Receive, Scope, Send

HEADER = "x-requested-with"
VALUE = "sensibility"
MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
MESSAGE = "Missing the X-Requested-With: sensibility header"


def refuses(method: str, path: str, headers: dict[str, str]) -> bool:
    """Whether the rule turns this request away."""
    return (
        method in MUTATING and path.startswith("/api/") and headers.get(HEADER) != VALUE
    )


class RequireApiHeader:
    """ASGI middleware applying the rule to every request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = {
                key.decode("latin-1").lower(): value.decode("latin-1")
                for key, value in scope["headers"]
            }
            if refuses(scope["method"], scope["path"], headers):
                body = json.dumps({"error": MESSAGE}).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 403,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)
