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
    asset_chart = alt.Chart(asset_data).mark_line().encode(
        x='Date:T',
        y='Amount:Q',
        color='Description:N',
    ).properties(
        title='Assets'
    )
    liability_chart = alt.Chart(liability_data).mark_line().encode(
        x='Date:T',
        y='Amount:Q',
        color='Description:N',
    ).properties(
        title='Liabilities'
    )
    return asset_chart | liability_chart
