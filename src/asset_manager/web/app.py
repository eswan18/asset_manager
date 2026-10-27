"""FastAPI web application for the asset dashboard."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from asset_manager.db import get_connection_context
from asset_manager.repository import get_accounts, get_all_records

from .access import (
    ViewerAccess,
    oldest_workspace_id,
    page_prefix,
    shell_context,
)
from .accounts_routes import router as accounts_router
from .api_routes import router as api_router
from .auth import (
    CurrentUser,
    EmailNotAllowed,
    LoginRequired,
    get_oauth,
    get_secret_key,
    handle_callback,
    handle_login,
    handle_logout,
)
from .cash_flows_routes import router as cash_flows_router
from .charts import COLUMN_LABELS, build_figure
from .dashboard import (
    RANGES,
    account_cards,
    change_since,
    daily_totals,
    filter_range,
    latest_category_totals,
    long_date,
    money,
    parse_range,
    short_date,
    signed_money,
    signed_percent,
)
from .rendering import render, templates
from .settings_routes import router as settings_router
from .welcome_routes import WELCOME_PATH
from .welcome_routes import router as welcome_router

logger = logging.getLogger(__name__)

# /docs, /redoc and /openapi.json are public: the repo is public, so the
# schema reveals nothing, and every route behind it requires a session.
app = FastAPI(title="Asset Dashboard")

# Session middleware for OAuth state and flash messages
app.add_middleware(
    SessionMiddleware,
    secret_key=get_secret_key(),
    session_cookie="oauth_session",
    max_age=600,  # 10 minutes for OAuth flow
)

app.include_router(accounts_router)
app.include_router(cash_flows_router)
app.include_router(settings_router)
app.include_router(welcome_router)
app.include_router(api_router)

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
    shell = shell_context(access, request.url.path)
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
        return render(request, "dashboard.html", page)
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
    cards = account_cards(records, accounts)
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
                "items": [
                    {"label": c.label, "amount": money(c.amount), "color": c.color}
                    for c in categories[type]
                ],
            }
            for type, title in COLUMN_LABELS.items()
            if categories[type]
        ],
        "cards": [
            {
                "title": title,
                "kind": type.value,
                "total": money(cards[type]["total"]),
                "groups": [
                    {
                        "label": g["label"],
                        "total": money(g["total"]),
                        "rows": [
                            {
                                "name": r["name"],
                                "amount": "—"
                                if r["amount"] is None
                                else money(r["amount"]),
                                "computed": r["computed"],
                            }
                            for r in g["rows"]
                        ],
                    }
                    for g in cards[type]["groups"]
                ],
            }
            for type, title in COLUMN_LABELS.items()
        ],
    }


@app.get("/login", response_class=HTMLResponse)
async def login(request: Request):
    """Show the login page."""
    return templates.TemplateResponse(request, "login.html")


@app.get("/auth/start")
async def auth_start(request: Request):
    """Redirect to the IDP for authentication."""
    oauth = get_oauth_client()
    return await handle_login(request, oauth)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    """Handle the OAuth callback."""
    oauth = get_oauth_client()
    try:
        return await handle_callback(request, oauth)
    except EmailNotAllowed as exc:
        logger.warning("Login refused: %s", exc)
        return HTMLResponse(
            "Your account is not authorized to use this app.", status_code=403
        )
    except Exception as e:
        logger.exception("OAuth callback failed: %s", e)
        return HTMLResponse("Authentication failed. Please try again.", status_code=400)


@app.get("/logout")
async def logout():
    """Log out and clear the session."""
    return handle_logout()


@app.get("/health")
async def health():
    """Health check endpoint."""
    return JSONResponse(
        content={"status": "ok"},
        headers={"Access-Control-Allow-Origin": "*"},
    )
