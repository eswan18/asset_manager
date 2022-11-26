import pandas as pd
import altair as alt

from .datastore import get_all_data


def make_charts() -> alt.Chart:
    data = get_all_data()
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
