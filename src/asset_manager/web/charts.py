"""Plotly chart HTML for the dashboard."""

from __future__ import annotations

from asset_manager.models import Account, Record, RecordType
from asset_manager.report import _transform_data


def build_chart_html(
    records: list[Record],
    accounts: list[Account],
) -> tuple[dict[str, str], dict[str, float], dict[str, float], dict[str, float]]:
    """Build Plotly chart HTML snippets for embedding.

    Returns:
        Tuple of (charts dict, totals dict, assets_breakdown dict, liabilities_breakdown dict)
        - charts: HTML snippets for each chart
        - totals: current net_worth, assets, liabilities
        - assets_breakdown: description -> latest amount for each active asset
        - liabilities_breakdown: description -> latest amount for each active liability
    """
    import plotly.graph_objects as go

    assets_data, liabilities_data, summary_data = _transform_data(records)
    retired = {(a.type, a.name) for a in accounts if not a.is_active}

    charts = {}
    totals = {"net_worth": 0.0, "assets": 0.0, "liabilities": 0.0}

    # Dark theme layout defaults
    dark_layout = {
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {"color": "#918c86", "family": "DM Sans, sans-serif"},
        "title_font": {
            "color": "#e8e4df",
            "family": "DM Serif Display, Georgia, serif",
            "size": 16,
        },
        "xaxis": {
            "gridcolor": "rgba(46,51,64,0.6)",
            "linecolor": "#2e3340",
            "tickfont": {"color": "#5f5b56"},
            "title_font": {"color": "#918c86"},
        },
        "yaxis": {
            "gridcolor": "rgba(46,51,64,0.6)",
            "linecolor": "#2e3340",
            "tickfont": {"color": "#5f5b56", "family": "JetBrains Mono, monospace"},
            "title_font": {"color": "#918c86"},
        },
        "hoverlabel": {
            "bgcolor": "#22262e",
            "bordercolor": "#3a3f4a",
            "font": {"color": "#e8e4df", "family": "DM Sans, sans-serif"},
        },
    }

    # Extract latest value for each active asset/liability for breakdown display
    assets_breakdown = {}
    for description, series in sorted(assets_data.items()):
        if series and (RecordType.ASSET, description) not in retired:
            # Series is sorted by date, last entry is most recent
            assets_breakdown[description] = float(series[-1][1])

    liabilities_breakdown = {}
    for description, series in sorted(liabilities_data.items()):
        if series and (RecordType.LIABILITY, description) not in retired:
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
        **dark_layout,
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
        **dark_layout,
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
                line={"color": "rgba(106, 173, 122, 0.5)"},
            )
        )
        fig_summary.add_trace(
            go.Scatter(
                x=dates,
                y=total_liabilities,
                name="Total Liabilities",
                mode="lines",
                line={"color": "rgba(199, 92, 92, 0.5)"},
            )
        )
        fig_summary.add_trace(
            go.Scatter(
                x=dates,
                y=net_worth,
                name="Net Worth",
                mode="lines",
                line={"color": "#c9a55a", "width": 3},
            )
        )
    fig_summary.update_layout(
        **dark_layout,
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
