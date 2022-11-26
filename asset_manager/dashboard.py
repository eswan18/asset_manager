import re
from io import StringIO

import pandas as pd
import altair as alt

from .s3 import read_string_from_object, list_objects_in_bucket


DAILY_SUMMARY_NAME_REGEX = re.compile(r"summaries_(\d{4}_\d{2}_\d{2}).csv")


def add_date_column_from_name(df: pd.DataFrame, name: str) -> pd.DataFrame:
    match = DAILY_SUMMARY_NAME_REGEX.match(name)
    if match is None:
        raise ValueError(f"name {name} does not resemble a daily file.")
    date = match.groups()[0]
    df2 = df.copy()
    df2["Date"] = date.replace("_", "-")
    return df2


def extract_df_from_object(name: str) -> pd.DataFrame | None:
    """
    Given an object name, extract the DataFrame stored in it.

    If the object name doesn't match our expected convention, None will be
    returned.
    """
    string_io = StringIO()
    string_io.write(read_string_from_object(name))
    string_io.seek(0)
    df = pd.read_csv(string_io)
    string_io.close()
    return df


def get_daily_data() -> pd.DataFrame:
    # Get all objects and limit down to the names that look like daily data.
    object_names = list_objects_in_bucket()
    daily_object_names = (name for name in object_names if DAILY_SUMMARY_NAME_REGEX.match(name)) 
    # Pull out a DataFrame in each object and add a date column.
    dfs = (extract_df_from_object(name) for name in daily_object_names)
    dfs = (add_date_column_from_name(df, name) for df, name in zip(dfs, daily_object_names))
    # Merge them all into one, since the new Date column will make them distinct.
    full_df = pd.concat(dfs)
    # Some of the data may have had an dummy column from its original index values.
    bad_col = "Unnamed: 0"
    if bad_col in full_df.columns:
        full_df = full_df.drop(bad_col, axis=1)
    # Convert the date column into a Pandas date.
    full_df["Date"] = pd.to_datetime(full_df["Date"])
    return full_df


def make_charts() -> alt.Chart:
    data = get_daily_data()
    asset_data = data[data.Type == "asset"]
    liability_data = data[data.Type == "liability"]
    # Prepare a dataset of net assets by day.
    assets_by_day = asset_data.groupby("Date", as_index=False)[["Date", "Amount"]].sum()
    inaccessible_by_day = (
        asset_data[asset_data["Accessible"] == "N"]
        .groupby("Date", as_index=False)[["Date", "Amount"]]
        .sum()
    )
    liabilities_by_day = liability_data.groupby("Date", as_index=False)[
        ["Date", "Amount"]
    ].sum()
    net_data = pd.merge(
        assets_by_day, liabilities_by_day, suffixes=("_asset", "_liability"), on="Date"
    )
    net_data["Amount"] = net_data.Amount_asset - net_data.Amount_liability
    net_data["Type"] = "All"
    # Accessible funds
    net_access_data = pd.merge(
        net_data,
        inaccessible_by_day,
        suffixes=("_net", "_inaccessible"),
        on="Date",
    )
    net_access_data["Amount"] = (
        net_access_data.Amount_net - net_access_data.Amount_inaccessible
    )
    net_access_data["Type"] = "Accessible"
    net_worth_data = pd.concat([net_data, net_access_data])
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
            color="Type:N",
        )
        .properties(title="Net Worth")
    )
    return (asset_chart | liability_chart) & (totals_chart | net_chart)
