"""FastAPI web application for the asset dashboard."""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from asset_manager.db import get_connection_context
from asset_manager.repository import get_accounts, get_all_records

from .access import NoWorkspace, PageViewer
from .accounts_routes import router as accounts_router
from .api_routes import router as api_router
from .auth import (
    EmailNotAllowed,
    LoginRequired,
    get_oauth,
    get_secret_key,
    handle_callback,
    handle_login,
    handle_logout,
)
from .charts import build_chart_html
from .rendering import render, templates

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


@app.exception_handler(NoWorkspace)
async def no_workspace_handler(request: Request, exc: NoWorkspace):
    message = "You are not a member of any workspace yet."
    if _wants_json(request):
        return JSONResponse({"error": message}, status_code=403)
    return HTMLResponse(message, status_code=403)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, access: PageViewer):
    """Render the main dashboard."""
    user, workspace_id = access.user, access.workspace.id
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
                "user": user,
                "active_tab": "dashboard",
                "error": "An error occurred while loading your data. Please try again later.",
                "charts": {},
            },
        )

    if records:
        charts, totals, assets_breakdown, liabilities_breakdown = build_chart_html(
            records, accounts
        )
    else:
        charts, totals = {}, {"net_worth": 0.0, "assets": 0.0, "liabilities": 0.0}
        assets_breakdown, liabilities_breakdown = {}, {}

    return render(
        request,
        "dashboard.html",
        {
            "user": user,
            "active_tab": "dashboard",
            "charts": charts,
            "totals": totals,
            "assets_breakdown": assets_breakdown,
            "liabilities_breakdown": liabilities_breakdown,
            "record_count": len(records),
        },
    )


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
