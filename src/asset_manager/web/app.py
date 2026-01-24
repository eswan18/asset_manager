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


def _build_chart_html(
    records,
) -> tuple[dict[str, str], dict[str, float], dict[str, float], dict[str, float]]:
    """Build Plotly chart HTML snippets for embedding.

    Returns:
        Tuple of (charts dict, totals dict, assets_breakdown dict, liabilities_breakdown dict)
        - charts: HTML snippets for each chart
        - totals: current net_worth, assets, liabilities
        - assets_breakdown: description -> latest amount for each asset
        - liabilities_breakdown: description -> latest amount for each liability
    """
    import plotly.graph_objects as go

    assets_data, liabilities_data, summary_data = _transform_data(records)

    charts = {}
    totals = {"net_worth": 0.0, "assets": 0.0, "liabilities": 0.0}

    # Extract latest value for each asset/liability for breakdown display
    assets_breakdown = {}
    for description, series in sorted(assets_data.items()):
        if series:
            # Series is sorted by date, last entry is most recent
            assets_breakdown[description] = float(series[-1][1])

    liabilities_breakdown = {}
    for description, series in sorted(liabilities_data.items()):
        if series:
            liabilities_breakdown[description] = float(series[-1][1])

    # Assets chart
    fig_assets = go.Figure()
    for description, series in sorted(assets_data.items()):
        dates = [point[0] for point in series]
        amounts = [float(point[1]) for point in series]
        fig_assets.add_trace(
            go.Scatter(x=dates, y=amounts, name=description, mode="lines")
        )
    fig_assets.update_layout(
        title="Assets over Time",
        xaxis_title="Date",
        yaxis_title="Amount ($)",
        yaxis_tickprefix="$",
        yaxis_tickformat=",.0f",
        hovermode="x unified",
        showlegend=False,
        height=300,
        margin={"t": 40, "b": 40, "l": 60, "r": 20},
    )
    charts["assets"] = fig_assets.to_html(full_html=False, include_plotlyjs=False)

    # Liabilities chart
    fig_liabilities = go.Figure()
    for description, series in sorted(liabilities_data.items()):
        dates = [point[0] for point in series]
        amounts = [float(point[1]) for point in series]
        fig_liabilities.add_trace(
            go.Scatter(x=dates, y=amounts, name=description, mode="lines")
        )
    fig_liabilities.update_layout(
        title="Liabilities over Time",
        xaxis_title="Date",
        yaxis_title="Amount ($)",
        yaxis_tickprefix="$",
        yaxis_tickformat=",.0f",
        hovermode="x unified",
        showlegend=False,
        height=300,
        margin={"t": 40, "b": 40, "l": 60, "r": 20},
    )
    charts["liabilities"] = fig_liabilities.to_html(
        full_html=False, include_plotlyjs=False
    )

    # Summary chart (Net Worth over Time)
    fig_summary = go.Figure()
    if summary_data:
        dates = [point[0] for point in summary_data]
        total_assets = [float(point[1]) for point in summary_data]
        total_liabilities = [float(point[2]) for point in summary_data]
        net_worth = [float(point[3]) for point in summary_data]

        # Get latest totals for summary cards
        totals["assets"] = total_assets[-1] if total_assets else 0.0
        totals["liabilities"] = total_liabilities[-1] if total_liabilities else 0.0
        totals["net_worth"] = net_worth[-1] if net_worth else 0.0

        fig_summary.add_trace(
            go.Scatter(
                x=dates,
                y=total_assets,
                name="Total Assets",
                mode="lines",
                line={"color": "rgba(34, 139, 34, 0.4)"},
            )
        )
        fig_summary.add_trace(
            go.Scatter(
                x=dates,
                y=total_liabilities,
                name="Total Liabilities",
                mode="lines",
                line={"color": "rgba(220, 20, 60, 0.4)"},
            )
        )
        fig_summary.add_trace(
            go.Scatter(
                x=dates,
                y=net_worth,
                name="Net Worth",
                mode="lines",
                line={"color": "#0066cc", "width": 3},
            )
        )
    fig_summary.update_layout(
        title="Net Worth over Time",
        xaxis_title="Date",
        yaxis_title="Amount ($)",
        yaxis_tickprefix="$",
        yaxis_tickformat=",.0f",
        hovermode="x unified",
        showlegend=False,
        height=400,
        margin={"t": 40, "b": 40, "l": 60, "r": 20},
    )
    charts["summary"] = fig_summary.to_html(full_html=False, include_plotlyjs=False)

    return charts, totals, assets_breakdown, liabilities_breakdown


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

    if records:
        charts, totals, assets_breakdown, liabilities_breakdown = _build_chart_html(
            records
        )
    else:
        charts, totals = {}, {"net_worth": 0.0, "assets": 0.0, "liabilities": 0.0}
        assets_breakdown, liabilities_breakdown = {}, {}

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
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
    from fastapi.responses import JSONResponse

    return JSONResponse(
        content={"status": "ok"},
        headers={"Access-Control-Allow-Origin": "*"},
    )
