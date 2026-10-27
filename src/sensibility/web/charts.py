"""The dashboard's Plotly figure: lines over time beside today's columns.

One figure, two x domains sharing one y-axis, so the columns sit on the same
dollar scale as the lines and each column's top meets its line's end.

Colors are tokens, not values: each trace and shape carries the CSS color it
should be in `meta`, and the page's script resolves those for the current
theme before plotting (and again when the theme changes). The values below
are only the light theme's, so the figure is readable if no script runs.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from sensibility.models import RecordType

from .dashboard import CategoryTotal, Point

# Where the lines end and the columns begin, as fractions of the plot width.
LINES_DOMAIN = [0.0, 0.8]
COLUMNS_DOMAIN = [0.86, 1.0]
DIVIDER_X = 0.83
# On a phone the columns need a larger share to stay legible.
NARROW = {"lines": [0.0, 0.62], "columns": [0.72, 1.0], "divider": 0.67}
NARROW_BELOW_PX = 600
# On a phone (the page's one breakpoint) the columns leave the figure for
# the stacked bars under it, and the lines take the whole width.
PHONE = {"query": "(max-width: 600px)", "height": 240}
# With one snapshot, Plotly zooms the date axis down to milliseconds; show
# the month before it instead, with the point at the right edge (by the columns).
LONE_POINT_DAYS = 30

# Light-theme fallbacks; the page re-colors from the tokens.
LIGHT = {
    "var(--asset)": "#2457C5",
    "var(--asset-2)": "#8FB0EE",
    "var(--liability-2)": "#D9772E",
    "var(--liability-3)": "#E9A066",
    "var(--liability-4)": "#F3C79E",
    "var(--ink)": "#15171A",
    "var(--liability)": "#B4530F",
    "var(--muted)": "#4A505A",
    "var(--grid)": "#ECEEF1",
    "var(--rule-strong)": "#DADDE2",
    "var(--surface)": "#FFFFFF",
}

COLUMN_LABELS = {RecordType.ASSET: "Assets", RecordType.LIABILITY: "Liabilities"}


def _fallback(css: str) -> str:
    return LIGHT.get(css, LIGHT["var(--muted)"])


def build_figure(
    points: list[Point], categories: dict[RecordType, list[CategoryTotal]]
) -> dict[str, Any]:
    """The figure as Plotly JSON (a plain dict): data, layout."""
    import plotly.graph_objects as go

    dates = [p.date.isoformat() for p in points]
    # A lone point draws no line, so give it a marker.
    mode = "lines+markers" if len(points) == 1 else "lines"
    fig = go.Figure()
    for name, values, color, width in [
        ("Assets", [p.assets for p in points], "var(--asset)", 2),
        ("Net worth", [p.net_worth for p in points], "var(--ink)", 3),
        ("Liabilities", [p.liabilities for p in points], "var(--liability)", 2),
    ]:
        fig.add_trace(
            go.Scatter(
                x=dates,
                y=[float(v) for v in values],
                name=name,
                mode=mode,
                line={"color": _fallback(color), "width": width},
                meta={"color": color},
                hovertemplate="%{y:$,.0f}",
                xaxis="x",
                yaxis="y",
            )
        )

    # Largest category first, so it sits at the bottom of its column.
    for type, column in COLUMN_LABELS.items():
        for category in categories.get(type, []):
            fig.add_trace(
                go.Bar(
                    x=[column],
                    y=[float(category.amount)],
                    name=category.label,
                    marker={
                        "color": _fallback(category.color),
                        "line": {"color": LIGHT["var(--surface)"], "width": 2},
                    },
                    meta={"color": category.color, "gap": "var(--surface)"},
                    hovertemplate="%{y:$,.0f}",
                    xaxis="x2",
                    yaxis="y",
                    width=0.7,
                )
            )

    axis_font = {"color": LIGHT["var(--muted)"], "size": 12}
    lone_range = {}
    if len(points) == 1:
        day = points[0].date
        lone_range = {
            "range": [
                (day - timedelta(days=LONE_POINT_DAYS)).isoformat(),
                (day + timedelta(days=1)).isoformat(),
            ]
        }
    fig.update_layout(
        template="none",
        height=320,
        margin={"t": 8, "b": 32, "l": 56, "r": 0},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Inter, system-ui, sans-serif", "color": axis_font["color"]},
        showlegend=False,
        barmode="stack",
        hovermode="x unified",
        # No drag (with every range fixed): a swipe over the chart scrolls
        # the page instead of being captured, and a tap still hovers.
        dragmode=False,
        hoverlabel={
            "bgcolor": LIGHT["var(--surface)"],
            "bordercolor": LIGHT["var(--rule-strong)"],
            "font": {"color": LIGHT["var(--ink)"]},
        },
        xaxis={
            "domain": LINES_DOMAIN,
            "type": "date",
            "showgrid": False,
            "showline": True,
            "linecolor": LIGHT["var(--rule-strong)"],
            "tickfont": axis_font,
            "ticks": "",
            "fixedrange": True,
            **lone_range,
        },
        xaxis2={
            "domain": COLUMNS_DOMAIN,
            "type": "category",
            "anchor": "y",
            "showgrid": False,
            "showline": True,
            "linecolor": LIGHT["var(--rule-strong)"],
            "tickfont": axis_font,
            "categoryorder": "array",
            "categoryarray": list(COLUMN_LABELS.values()),
            "range": [-0.5, 1.5],
            "fixedrange": True,
        },
        yaxis={
            "rangemode": "tozero",
            "tickprefix": "$",
            "tickformat": "~s",
            "gridcolor": LIGHT["var(--grid)"],
            "zeroline": False,
            "tickfont": axis_font,
            "fixedrange": True,
        },
        shapes=[
            {
                "type": "line",
                "xref": "paper",
                "yref": "paper",
                "x0": DIVIDER_X,
                "x1": DIVIDER_X,
                "y0": -0.08,
                "y1": 1,
                "line": {
                    "color": LIGHT["var(--rule-strong)"],
                    "width": 1,
                    "dash": "dash",
                },
            }
        ],
        meta={
            "font": "var(--muted)",
            "grid": "var(--grid)",
            "axis": "var(--rule-strong)",
            "surface": "var(--surface)",
            "ink": "var(--ink)",
            "narrow": {**NARROW, "below": NARROW_BELOW_PX},
            "phone": PHONE,
        },
    )
    return json.loads(fig.to_json())
