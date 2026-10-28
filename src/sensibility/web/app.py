"""FastAPI web application for the asset dashboard."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.routing import Route

from sensibility.db import get_connection_context
from sensibility.mcp.gate import gate as mcp_gate
from sensibility.mcp.gate import protected_resource_metadata
from sensibility.mcp.server import running as mcp_running
from sensibility.mcp.tokens import mcp_config
from sensibility.models import Role
from sensibility.repository import get_accounts, get_all_records

from .access import (
    ViewerAccess,
    oldest_workspace_id,
    page_prefix,
    shell_context,
)
from .accounts_routes import router as accounts_router
from .api_accounts import router as api_accounts_router
from .api_dashboard import router as api_dashboard_router
from .api_cash_flows import router as api_cash_flows_router
from .api_routes import router as api_router
from .api_settings import router as api_settings_router
from .auth import (
    CurrentUser,
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
from .cash_flows_routes import router as cash_flows_router
from .csrf import RequireApiHeader
from .charts import COLUMN_LABELS, build_figure
from .dashboard import (
    RANGES,
    cards_view,
    category_bars,
    change_since,
    daily_totals,
    filter_range,
    latest_category_totals,
    long_date,
    money,
    onboarding_context,
    parse_range,
    short_date,
    signed_money,
    signed_percent,
)
from .rendering import render
from .settings_routes import router as settings_router
from .spa import router as spa_router
from .welcome_routes import WELCOME_PATH
from .welcome_routes import router as welcome_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    async with mcp_running():
        yield


# /docs, /redoc and /openapi.json are public: the repo is public, so the
# schema reveals nothing, and every route behind it requires a session.
app = FastAPI(title="Asset Dashboard", lifespan=lifespan)

# Session middleware for OAuth state and flash messages
app.add_middleware(
    SessionMiddleware,
    secret_key=get_secret_key(),
    session_cookie="oauth_session",
    max_age=600,  # 10 minutes for OAuth flow
)

# Mutating /api/ requests must carry X-Requested-With: sensibility (web/csrf.py).
app.add_middleware(RequireApiHeader)

app.include_router(accounts_router)
app.include_router(cash_flows_router)
app.include_router(settings_router)
app.include_router(welcome_router)
app.include_router(api_router)
app.include_router(api_dashboard_router)
app.include_router(api_accounts_router)
app.include_router(api_cash_flows_router)
app.include_router(api_settings_router)
# The React app under /app (web/spa.py); public, like /login.
app.include_router(spa_router)

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
    """Pages redirect to login; JSON clients and /api/ get a 401."""
    if _wants_json(request):
        return JSONResponse({"error": "Login required"}, status_code=401)
    return RedirectResponse(url="/login", status_code=302)


def _wants_json(request: Request) -> bool:
    return request.url.path.startswith(
        "/api/"
    ) or "application/json" in request.headers.get("accept", "")


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Every error body is {"error": message}, matching the API's own errors."""
    return JSONResponse(
        {"error": exc.detail}, status_code=exc.status_code, headers=exc.headers
    )


# Bare paths predate workspaces in the URL. They redirect into your oldest
# workspace so bookmarks keep working, or to the welcome page if you have
# none; only GETs, since a form or a save should never land in a workspace
# it did not name.
def _bare(user: dict, section: str = "") -> RedirectResponse:
    workspace_id = oldest_workspace_id(user)
    if workspace_id is None:
        return RedirectResponse(WELCOME_PATH, status_code=302)
    return RedirectResponse(page_prefix(workspace_id) + section, status_code=302)


@app.get("/")
async def home(user: CurrentUser) -> RedirectResponse:
    return _bare(user)


@app.get("/accounts")
async def bare_accounts(user: CurrentUser) -> RedirectResponse:
    return _bare(user, "/accounts")


@app.get("/workspaces/{workspace_id}", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    access: ViewerAccess,
    range_key: Annotated[str | None, Query(alias="range")] = None,
):
    """Render the main dashboard. ?range= is 6m, 1y (the default) or all."""
    workspace_id = access.workspace.id
    shell = shell_context(request, access)
    selected = parse_range(range_key)
    page = {**shell, "active_tab": "dashboard", "has_data": False}
    try:
        with get_connection_context() as conn:
            records = get_all_records(conn, workspace_id)
            accounts = get_accounts(conn, workspace_id)
    except Exception:
        logger.exception("Database error in dashboard")
        return render(
            request,
            "dashboard.html",
            {
                **page,
                "error": "An error occurred while loading your data. Please try again later.",
            },
        )
    if not records:
        return render(
            request,
            "dashboard.html",
            {
                **page,
                **onboarding_context(accounts, shell["base"]),
                "can_edit": access.role.allows(Role.EDITOR),
            },
        )
    return render(
        request,
        "dashboard.html",
        {**page, **dashboard_context(records, accounts, selected, shell["base"])},
    )


def dashboard_context(records, accounts, selected: str, base: str) -> dict:
    """Template values for a workspace with at least one snapshot."""
    points = daily_totals(records)
    latest = points[-1]
    categories = latest_category_totals(records, accounts)
    change = change_since(points)
    return {
        "has_data": True,
        "net_worth": money(latest.net_worth),
        "last_snapshot": long_date(latest.date),
        "change": None
        if change is None
        else {
            "amount": signed_money(change.amount),
            "percent": None
            if change.percent is None
            else signed_percent(change.percent),
            "since": short_date(change.since, latest.date),
        },
        "figure": build_figure(filter_range(points, selected), categories),
        "ranges": [
            (label, f"{base}?range={key}", key == selected)
            for key, (label, _) in RANGES.items()
        ],
        "category_keys": [
            {
                "title": title,
                "kind": type.value,
                "items": [
                    {"label": c.label, "amount": money(c.amount), "color": c.color}
                    for c in categories[type]
                ],
            }
            for type, title in COLUMN_LABELS.items()
            if categories[type]
        ],
        # Phones only: the columns as two stacked bars above that key.
        "category_bars": [
            {
                "title": COLUMN_LABELS[type],
                "kind": type.value,
                "segments": segments,
            }
            for type, segments in category_bars(categories).items()
            if segments
        ],
        "cards": cards_view(records, accounts),
    }


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
