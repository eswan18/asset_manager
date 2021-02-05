import re
from io import StringIO
from functools import reduce
from typing import Optional

import pandas as pd
import altair as alt

from .storage import read_string_from_object, list_objects_in_bucket

def get_summary_data():
    summary_names = list_objects_in_bucket()
    def prep_df_from_name(name) -> Optional[pd.DataFrame]:
        match = re.match(r'summaries_(\d\d\d\d_\d\d_\d\d)\.csv', name)
        if match is None:
            return None
        date = match.groups()[0]
        string_io = StringIO()
        string_io.write(read_string_from_object(name))
        string_io.seek(0)
        df = pd.read_csv(string_io)
        string_io.close()
        # Add a column holding the date
        df['Date'] = date.replace('_', '-')
        return df
    full_df = pd.concat((prep_df_from_name(name) for name in summary_names))
    # Some of the data may have had an dummy column from its original index values.
    bad_col = 'Unnamed: 0'
    if bad_col in full_df.columns:
        full_df = full_df.drop(bad_col, axis=1)
    # Convert the date column into a Pandas date.
    full_df['Date'] = pd.to_datetime(full_df['Date'])
    return full_df

def make_charts():
    data = get_summary_data()
    asset_data = data[data.Type == 'asset']
    liability_data = data[data.Type == 'liability']
    # Prepare a dataset of net assets by day.
    assets_by_day = asset_data.groupby(
        'Date',
        as_index=False
    )[['Date', 'Amount']].sum()
    inaccessible_by_day = asset_data[asset_data['Accessible'] == 'N'].groupby(
        'Date',
        as_index=False
    )[['Date', 'Amount']].sum()
    liabilities_by_day = liability_data.groupby(
        'Date',
        as_index=False
    )[['Date', 'Amount']].sum()
    net_data = pd.merge(
        assets_by_day,
        liabilities_by_day,
        suffixes=('_asset', '_liability'),
        on='Date'
    )
    net_data['Amount'] = net_data.Amount_asset - net_data.Amount_liability
    net_data['Type'] = 'All'
    # Accessible funds
    net_access_data = pd.merge(
        net_data,
        inaccessible_by_day,
        suffixes=('_net', '_inaccessible'),
        on='Date',
    )
    net_access_data['Amount'] = net_access_data.Amount_net - net_access_data.Amount_inaccessible
    net_access_data['Type'] = 'Accessible'
    net_worth_data = pd.concat([net_data, net_access_data])
    # Make charts.
    asset_chart = alt.Chart(asset_data).mark_line().encode(
        x='Date:T',
        y='Amount:Q',
        color='Description:N',
        tooltip=['Description', 'Amount']
    ).properties(
        title='Assets'
    ).interactive()
    liability_chart = alt.Chart(liability_data).mark_line().encode(
        x='Date:T',
        y='Amount:Q',
        color='Description:N',
        tooltip=['Description', 'Amount']
    ).properties(
        title='Liabilities'
    ).interactive()
    totals_chart = alt.Chart(data).mark_line().encode(
        x='Date:T',
        y='sum(Amount)',
        color='Type:N'
    ).properties(
        title='Totals'
    ).interactive()
    net_chart = alt.Chart(net_worth_data).mark_line().encode(
        x='Date:T',
        y='Amount',
        color='Type:N',
    ).properties(
        title='Net Worth'
    )
    return (asset_chart | liability_chart) & (totals_chart | net_chart)
