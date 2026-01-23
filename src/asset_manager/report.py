"""Generate interactive HTML reports for financial data."""
from __future__ import annotations

import tempfile
import webbrowser
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .models import Record, RecordType


def _transform_data(
    records: list[Record],
) -> tuple[
    dict[str, list[tuple[date, Decimal]]],
    dict[str, list[tuple[date, Decimal]]],
    list[tuple[date, Decimal, Decimal, Decimal]],
]:
    """Transform records into data structures for charting.

    Returns:
        - assets_by_item: {description: [(date, amount), ...]}
        - liabilities_by_item: {description: [(date, amount), ...]}
        - summary: [(date, total_assets, total_liabilities, net_worth), ...]
    """
    assets_by_item: dict[str, list[tuple[date, Decimal]]] = defaultdict(list)
    liabilities_by_item: dict[str, list[tuple[date, Decimal]]] = defaultdict(list)

    # Group records by date for summary calculation
    by_date: dict[date, dict[str, Decimal]] = defaultdict(
        lambda: {"assets": Decimal("0"), "liabilities": Decimal("0")}
    )

    for record in records:
        if record.type == RecordType.ASSET:
            assets_by_item[record.description].append((record.date, record.amount))
            by_date[record.date]["assets"] += record.amount
        else:
            liabilities_by_item[record.description].append((record.date, record.amount))
            by_date[record.date]["liabilities"] += record.amount

    # Sort each series by date
    for series in assets_by_item.values():
        series.sort(key=lambda x: x[0])
    for series in liabilities_by_item.values():
        series.sort(key=lambda x: x[0])

    # Build summary data
    summary = [
        (d, totals["assets"], totals["liabilities"], totals["assets"] - totals["liabilities"])
        for d, totals in sorted(by_date.items())
    ]

    return dict(assets_by_item), dict(liabilities_by_item), summary


def generate_report(
    records: list[Record],
    output_path: Path | None = None,
    open_browser: bool = True,
) -> Path:
    """Generate an interactive HTML report and optionally open in browser.

    Args:
        records: List of financial records from the database.
        output_path: Where to save the HTML. Defaults to temp directory.
        open_browser: Whether to open the report in the default browser.

    Returns:
        Path to the generated HTML file.
    """
    assets_data, liabilities_data, summary_data = _transform_data(records)

    # Create subplot figure with 3 rows
    fig = make_subplots(
        rows=3,
        cols=1,
        subplot_titles=("Assets by Item", "Liabilities by Item", "Net Worth Summary"),
        vertical_spacing=0.08,
    )

    # Chart 1: Assets by item
    for description, series in sorted(assets_data.items()):
        dates = [point[0] for point in series]
        amounts = [float(point[1]) for point in series]
        fig.add_trace(
            go.Scatter(
                x=dates,
                y=amounts,
                name=description,
                mode="lines+markers",
                legendgroup="assets",
                legendgrouptitle_text="Assets",
            ),
            row=1,
            col=1,
        )

    # Chart 2: Liabilities by item
    for description, series in sorted(liabilities_data.items()):
        dates = [point[0] for point in series]
        amounts = [float(point[1]) for point in series]
        fig.add_trace(
            go.Scatter(
                x=dates,
                y=amounts,
                name=description,
                mode="lines+markers",
                legendgroup="liabilities",
                legendgrouptitle_text="Liabilities",
            ),
            row=2,
            col=1,
        )

    # Chart 3: Summary (total assets, total liabilities, net worth)
    if summary_data:
        dates = [point[0] for point in summary_data]
        total_assets = [float(point[1]) for point in summary_data]
        total_liabilities = [float(point[2]) for point in summary_data]
        net_worth = [float(point[3]) for point in summary_data]

        fig.add_trace(
            go.Scatter(
                x=dates,
                y=total_assets,
                name="Total Assets",
                mode="lines+markers",
                line={"color": "green"},
                legendgroup="summary",
                legendgrouptitle_text="Summary",
            ),
            row=3,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=dates,
                y=total_liabilities,
                name="Total Liabilities",
                mode="lines+markers",
                line={"color": "red"},
                legendgroup="summary",
            ),
            row=3,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=dates,
                y=net_worth,
                name="Net Worth",
                mode="lines+markers",
                line={"color": "blue", "width": 3},
                legendgroup="summary",
            ),
            row=3,
            col=1,
        )

    # Update layout
    fig.update_layout(
        title_text="Financial Report",
        height=1000,
        showlegend=True,
        hovermode="x unified",
    )

    # Format y-axes as currency
    fig.update_yaxes(tickprefix="$", tickformat=",.0f")

    # Determine output path
    if output_path is None:
        output_path = Path(tempfile.gettempdir()) / "asset_report.html"

    # Write HTML
    fig.write_html(output_path)

    # Open in browser if requested
    if open_browser:
        webbrowser.open(f"file://{output_path.absolute()}")

    return output_path
