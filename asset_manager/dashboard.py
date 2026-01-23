from typing import cast

import altair as alt
import pandas as pd

from .db import get_connection_context
from .models import Record
from .repository import get_all_records


def records_to_dataframe(records: list[Record]) -> pd.DataFrame:
    """Convert a list of Record models to a pandas DataFrame for Altair."""
    return pd.DataFrame(
        [
            {
                "Date": r.date,
                "Type": r.type.value,
                "Description": r.description,
                "Amount": float(r.amount),
            }
            for r in records
        ]
    )


def get_all_data() -> pd.DataFrame | None:
    """Fetch all records from the database and return as a DataFrame."""
    with get_connection_context() as conn:
        records = get_all_records(conn)

    if not records:
        return None

    return records_to_dataframe(records)


def make_charts() -> alt.Chart:
    data = get_all_data()
    if data is None:
        raise ValueError("No data to display")

    asset_data = data[data.Type == "asset"]
    liability_data = data[data.Type == "liability"]

    # Prepare a dataset of net assets by day.
    assets_by_day = (
        asset_data.groupby("Date", as_index=False)["Amount"].sum().reset_index()
    )
    liabilities_by_day = (
        liability_data.groupby("Date", as_index=False)["Amount"].sum().reset_index()
    )

    net_worth_data = pd.merge(
        assets_by_day, liabilities_by_day, suffixes=("_asset", "_liability"), on="Date"
    )
    net_worth_data["Amount"] = (
        net_worth_data.Amount_asset - net_worth_data.Amount_liability
    )

    # Make charts.
    asset_chart = (
        alt.Chart(asset_data)
        .mark_line()
        .encode(
            x="Date:T",
            y="Amount:Q",
            color="Description:N",
            tooltip=["Description", "Amount"],
        )
        .properties(title="Assets")
        .interactive()
    )
    liability_chart = (
        alt.Chart(liability_data)
        .mark_line()
        .encode(
            x="Date:T",
            y="Amount:Q",
            color="Description:N",
            tooltip=["Description", "Amount"],
        )
        .properties(title="Liabilities")
        .interactive()
    )
    totals_chart = (
        alt.Chart(data)
        .mark_line()
        .encode(x="Date:T", y="sum(Amount)", color="Type:N")
        .properties(title="Totals")
        .interactive()
    )
    net_chart = (
        alt.Chart(net_worth_data)
        .mark_line()
        .encode(
            x="Date:T",
            y="Amount",
        )
        .properties(title="Net Worth")
    )
    top_row = asset_chart | liability_chart
    bottom_row = totals_chart | net_chart
    result = top_row & bottom_row
    # Not sure why this is needed, but mypy thinks result is Any otherwise.
    return cast(alt.Chart, result)
