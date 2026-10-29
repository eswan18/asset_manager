"""FastAPI web application for the asset dashboard."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.routing import Route

from sensibility.db import close_pools
from sensibility.mcp.gate import gate as mcp_gate
from sensibility.mcp.gate import protected_resource_metadata
from sensibility.mcp.server import running as mcp_running
from sensibility.mcp.tokens import mcp_config

from .api_accounts import router as api_accounts_router
from .api_dashboard import router as api_dashboard_router
from .api_cash_flows import router as api_cash_flows_router
from .api_routes import router as api_router
from .api_settings import router as api_settings_router
from .auth import (
    EmailNotAllowed,
    EmailUnverified,
    LoginRequired,
    after_idp_logout,
    clear_session_response,
    get_oauth,
    get_secret_key,
    handle_callback,
    handle_login,
    handle_logout,
    handle_switch,
    idp_host,
)
from .csrf import RequireApiHeader
from .rendering import render
from .spa import router as spa_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    async with mcp_running():
        try:
            yield
        finally:
            close_pools()


# /docs, /redoc and /openapi.json are public: the repo is public, so the
# schema reveals nothing, and every route behind it requires a session.
app = FastAPI(title="Asset Dashboard", lifespan=lifespan)

# Session middleware for the OAuth flow's state
app.add_middleware(
    SessionMiddleware,
    secret_key=get_secret_key(),
    session_cookie="oauth_session",
    max_age=600,  # 10 minutes for OAuth flow
)

# Mutating /api/ requests must carry X-Requested-With: sensibility (web/csrf.py).
app.add_middleware(RequireApiHeader)

app.include_router(api_router)
app.include_router(api_dashboard_router)
app.include_router(api_accounts_router)
app.include_router(api_cash_flows_router)
app.include_router(api_settings_router)

# The MCP endpoint (sensibility.mcp): bearer tokens from identity, not the
# session. The gate answers every method itself, 401s included, so the
# session's LoginRequired handling never sees it. Not in the OpenAPI schema.
# Bearer tokens are not accepted on /api/ yet (MCP spec, plan item 11).
app.router.routes.append(Route("/mcp", endpoint=mcp_gate, include_in_schema=False))


@app.get("/.well-known/oauth-protected-resource/mcp")
async def mcp_resource_metadata() -> JSONResponse:
    """RFC 9728 protected resource metadata for /mcp. Public."""
    config = mcp_config()
    if config is None:
        return JSONResponse({"error": "MCP is not configured here"}, status_code=503)
    return JSONResponse(protected_resource_metadata(config))


# OAuth client (lazy initialization)
_oauth = None


def get_oauth_client():
    """Get or create the OAuth client."""
    global _oauth
    if _oauth is None:
        _oauth = get_oauth()
    return _oauth


@app.exception_handler(LoginRequired)
async def login_required_handler(request: Request, exc: LoginRequired):
    """A 401. Only the API needs a session (the pages are the React app's,
    which sends a 401 on to /login)."""
    return JSONResponse({"error": "Login required"}, status_code=401)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Every error body is {"error": message}, matching the API's own errors."""
    return JSONResponse(
        {"error": exc.detail}, status_code=exc.status_code, headers=exc.headers
    )


@app.get("/login", response_class=HTMLResponse)
async def login(request: Request):
    """Show the login page (board X)."""
    try:
        host = idp_host(get_oauth_client())
    except Exception:
        # Identity unreachable or unconfigured: the page still renders, with
        # a generic footnote; Log in itself will report the problem.
        logger.debug("No identity host for the login page", exc_info=True)
        host = None
    return render(request, "login.html", {"state": "login", "idp_host": host})


@app.get("/auth/start")
async def auth_start(request: Request):
    """Redirect to the IDP for authentication."""
    oauth = get_oauth_client()
    return await handle_login(request, oauth)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    """Handle the OAuth callback."""
    # Back from identity's logout (/logout or /auth/switch), with no code:
    # on to our login page or a fresh login, whichever started the trip.
    after = after_idp_logout(request)
    if after and not {"code", "error"} & request.query_params.keys():
        return RedirectResponse(after, status_code=302)
    oauth = get_oauth_client()
    try:
        return await handle_callback(request, oauth)
    except EmailNotAllowed as exc:
        logger.warning("Login refused: %s", exc)
        state = "unverified" if isinstance(exc, EmailUnverified) else "not_allowed"
        return render(request, "login.html", {"state": state, "email": exc.email}, 403)
    except Exception as e:
        logger.exception("OAuth callback failed: %s", e)
        return HTMLResponse("Authentication failed. Please try again.", status_code=400)


@app.get("/auth/switch")
async def auth_switch(request: Request):
    """Log in with a different account: log out here and at identity."""
    try:
        oauth = get_oauth_client()
    except Exception:
        logger.exception("Identity unavailable for switching accounts")
        return clear_session_response("/login")
    return handle_switch(request, oauth)


@app.get("/logout")
async def logout(request: Request):
    """Log out here and at identity, then land on the login page."""
    try:
        oauth = get_oauth_client()
    except Exception:
        logger.exception("Identity unavailable for logging out")
        return clear_session_response("/login")
    return handle_logout(request, oauth)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return JSONResponse(
        content={"status": "ok"},
        headers={"Access-Control-Allow-Origin": "*"},
    )


# The React app (web/spa.py), public like /login: every GET no route above
# claimed. It must stay the last route, or it would shadow the ones after it.
app.include_router(spa_router)
