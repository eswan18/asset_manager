"""The React app (frontend/, docs/superpowers/specs/2026-10-28-react-frontend-design.md).

`npm run build` writes it to frontend/dist: index.html and hashed files under
assets/. During the build-out it is served under /app (Vite's `base` and the
router's basename): `/app/assets/…` with a year's caching (the names change
with the content), and index.html, never cached, for every other `/app/…`
path, so the client-side router answers deep links. The shell is public: it
holds no data, and the SPA sends anyone without a session to /login when the
API answers 401.

The build is found at `SPA_DIST` (the image sets it) or, by default, at
frontend/dist in the checkout. Without one (a fresh clone, or tests that
don't build) /app answers 503 with what to do, rather than failing.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, Response

router = APIRouter()

PREFIX = "/app"
# src/sensibility/web/spa.py -> the checkout's frontend/dist.
_DEFAULT_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"

IMMUTABLE = "public, max-age=31536000, immutable"
NO_CACHE = "no-cache"

_NOT_BUILT = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>Not built · Sensibility</title></head>
<body style="font-family: system-ui, sans-serif; max-width: 40rem; margin: 4rem auto; padding: 0 1rem;">
<h1>The new frontend isn't built here</h1>
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


@router.get(PREFIX, response_class=HTMLResponse)
async def spa_root() -> Response:
    """The SPA's entry: its router sends you on to your workspace."""
    return serve("")


@router.get(PREFIX + "/{path:path}", response_class=HTMLResponse)
async def spa(path: str) -> Response:
    """Any path under /app: a built file if `path` names one, else index.html."""
    return serve(path)


def serve(path: str) -> Response:
    dist = dist_dir()
    index = dist / "index.html"
    if not index.is_file():
        return HTMLResponse(_NOT_BUILT, status_code=503)
    if path.startswith("assets/"):
        found = _inside(dist, path)
        if found is None:
            return Response("Not found", status_code=404, media_type="text/plain")
        return FileResponse(found, headers={"Cache-Control": IMMUTABLE})
    # Anything else Vite copies from public/ (a favicon) is served as is;
    # every other path is a route for the client-side router.
    found = _inside(dist, path) if path else None
    if found is not None and found.name != "index.html":
        return FileResponse(found, headers={"Cache-Control": NO_CACHE})
    return FileResponse(index, headers={"Cache-Control": NO_CACHE})
