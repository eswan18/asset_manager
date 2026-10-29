"""The React app (frontend/, docs/superpowers/specs/2026-10-28-react-frontend-design.md).

`npm run build` writes it to frontend/dist: index.html and hashed files under
assets/. It is served from the root: `/assets/…` with a year's caching (the
names change with the content; a missing one is a 404, never the app), any
other built file as it is, and index.html, never cached, for every other GET
that no server route claims, so the client-side router answers `/`,
`/welcome`, `/workspaces/…` and its own not-found page. The shell is public:
it holds no data, and the SPA sends anyone without a session to /login when
the API answers 401.

Server-side paths keep winning because this router is the app's last: it is
included after every other route (web/app.py), and it refuses the server's
own prefixes (`/api/`, `/auth/`, `/.well-known/`), so an unknown path there
stays a JSON 404 rather than becoming the app.

`/app/…`, where the app lived while it was built, redirects permanently to
the same path without the prefix, query included, so bookmarks keep working.

The build is found at `SPA_DIST` (the image sets it) or, by default, at
frontend/dist in the checkout. Without one (a fresh clone, or tests that
don't build) the app's paths answer 503 with what to do, rather than failing.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

router = APIRouter(include_in_schema=False)

# src/sensibility/web/spa.py -> the checkout's frontend/dist.
_DEFAULT_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"

IMMUTABLE = "public, max-age=31536000, immutable"
NO_CACHE = "no-cache"

# Where the app lived during the build-out (Vite's base and the router's
# basename were /app/ then).
OLD_PREFIX = "app"
# Paths under these are the server's; an unknown one is a 404, never the app.
SERVER_PREFIXES = ("api/", "auth/", ".well-known/")

_NOT_BUILT = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>Not built · Sensibility</title></head>
<body style="font-family: system-ui, sans-serif; max-width: 40rem; margin: 4rem auto; padding: 0 1rem;">
<h1>The frontend isn't built here</h1>
<p>Build it with <code>cd frontend &amp;&amp; npm ci &amp;&amp; npm run build</code>,
or run <code>npm run dev</code> there and open the Vite server instead.</p>
</body></html>
"""


def dist_dir() -> Path:
    """Where the built SPA is (read per request, so tests can point it)."""
    return Path(os.environ.get("SPA_DIST") or _DEFAULT_DIST)


def _inside(root: Path, relative: str) -> Path | None:
    """`root/relative` if it is a file inside `root`, else None."""
    root = root.resolve()
    candidate = (root / relative).resolve()
    if candidate.is_file() and candidate.is_relative_to(root):
        return candidate
    return None


@router.api_route("/{path:path}", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def spa(request: Request, path: str) -> Response:
    """Any GET (or HEAD) no other route claimed: a built file if `path` names
    one, else index.html."""
    if path == OLD_PREFIX or path.startswith(OLD_PREFIX + "/"):
        target = "/" + path.removeprefix(OLD_PREFIX).lstrip("/")
        query = request.url.query
        return RedirectResponse(target + (f"?{query}" if query else ""), 301)
    if path.startswith(SERVER_PREFIXES):
        raise HTTPException(status_code=404, detail="Not Found")
    return serve(path)


def serve(path: str) -> Response:
    dist = dist_dir()
    index = dist / "index.html"
    if path.startswith("assets/"):
        found = _inside(dist, path)
        if found is None:
            return Response("Not found", status_code=404, media_type="text/plain")
        return FileResponse(found, headers={"Cache-Control": IMMUTABLE})
    if not index.is_file():
        return HTMLResponse(_NOT_BUILT, status_code=503)
    # Anything else Vite copies from public/ (a favicon) is served as is;
    # every other path is a route for the client-side router.
    found = _inside(dist, path) if path else None
    if found is not None and found.name != "index.html":
        return FileResponse(found, headers={"Cache-Control": NO_CACHE})
    return FileResponse(index, headers={"Cache-Control": NO_CACHE})
