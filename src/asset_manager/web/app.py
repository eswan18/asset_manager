"""FastAPI web application for the asset dashboard."""

from __future__ import annotations

import logging
from importlib import resources

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from asset_manager.db import get_connection_context
from asset_manager.report import _transform_data
from asset_manager.repository import get_all_records

from .auth import (
    get_oauth,
    get_secret_key,
    get_session_user,
    handle_callback,
    handle_login,
    handle_logout,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="Asset Dashboard", docs_url=None, redoc_url=None)

# Add session middleware for OAuth state
app.add_middleware(
    SessionMiddleware,  # ty: ignore[invalid-argument-type]
    secret_key=get_secret_key(),
    session_cookie="oauth_session",
    max_age=600,  # 10 minutes for OAuth flow
)

# Set up templates
templates_path = resources.files("asset_manager.web").joinpath("templates")
templates = Jinja2Templates(directory=str(templates_path))

# OAuth client (lazy initialization)
_oauth = None


def get_oauth_client():
    """Get or create the OAuth client."""
    global _oauth
    if _oauth is None:
        _oauth = get_oauth()
    return _oauth


def _build_chart_html(records) -> dict[str, str]:
    """Build Plotly chart HTML snippets for embedding."""
    import plotly.graph_objects as go

    assets_data, liabilities_data, summary_data = _transform_data(records)

    charts = {}

    # Assets chart
    fig_assets = go.Figure()
    for description, series in sorted(assets_data.items()):
        dates = [point[0] for point in series]
        amounts = [float(point[1]) for point in series]
        fig_assets.add_trace(
            go.Scatter(x=dates, y=amounts, name=description, mode="lines+markers")
        )
    fig_assets.update_layout(
        title="Assets by Item",
        xaxis_title="Date",
        yaxis_title="Amount ($)",
        yaxis_tickprefix="$",
        yaxis_tickformat=",.0f",
        hovermode="x unified",
        height=350,
        margin={"t": 40, "b": 40, "l": 60, "r": 20},
    )
    charts["assets"] = fig_assets.to_html(full_html=False, include_plotlyjs=False)

    # Liabilities chart
    fig_liabilities = go.Figure()
    for description, series in sorted(liabilities_data.items()):
        dates = [point[0] for point in series]
        amounts = [float(point[1]) for point in series]
        fig_liabilities.add_trace(
            go.Scatter(x=dates, y=amounts, name=description, mode="lines+markers")
        )
    fig_liabilities.update_layout(
        title="Liabilities by Item",
        xaxis_title="Date",
        yaxis_title="Amount ($)",
        yaxis_tickprefix="$",
        yaxis_tickformat=",.0f",
        hovermode="x unified",
        height=350,
        margin={"t": 40, "b": 40, "l": 60, "r": 20},
    )
    charts["liabilities"] = fig_liabilities.to_html(
        full_html=False, include_plotlyjs=False
    )

    # Summary chart
    fig_summary = go.Figure()
    if summary_data:
        dates = [point[0] for point in summary_data]
        total_assets = [float(point[1]) for point in summary_data]
        total_liabilities = [float(point[2]) for point in summary_data]
        net_worth = [float(point[3]) for point in summary_data]

        fig_summary.add_trace(
            go.Scatter(
                x=dates,
                y=total_assets,
                name="Total Assets",
                mode="lines+markers",
                line={"color": "green"},
            )
        )
        fig_summary.add_trace(
            go.Scatter(
                x=dates,
                y=total_liabilities,
                name="Total Liabilities",
                mode="lines+markers",
                line={"color": "red"},
            )
        )
        fig_summary.add_trace(
            go.Scatter(
                x=dates,
                y=net_worth,
                name="Net Worth",
                mode="lines+markers",
                line={"color": "blue", "width": 3},
            )
        )
    fig_summary.update_layout(
        title="Net Worth Summary",
        xaxis_title="Date",
        yaxis_title="Amount ($)",
        yaxis_tickprefix="$",
        yaxis_tickformat=",.0f",
        hovermode="x unified",
        height=350,
        margin={"t": 40, "b": 40, "l": 60, "r": 20},
    )
    charts["summary"] = fig_summary.to_html(full_html=False, include_plotlyjs=False)

    return charts


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Render the main dashboard."""
    user = get_session_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    # Fetch data and build charts
    try:
        with get_connection_context() as conn:
            records = get_all_records(conn)
    except Exception as e:
        logger.exception("Database error in dashboard: %s", e)
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "user": user,
                "error": "An error occurred while loading your data. Please try again later.",
                "charts": {},
            },
        )

    charts = _build_chart_html(records) if records else {}

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "charts": charts,
            "record_count": len(records),
        },
    )


@app.get("/login", response_class=HTMLResponse)
async def login(request: Request):
    """Show the login page."""
    return templates.TemplateResponse("login.html", {"request": request})


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
    return {"status": "ok"}
