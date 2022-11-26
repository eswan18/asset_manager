"""
A wrapper over writing and reading data.

The current underlying datastore is s3 but that could change, and the interface for this
module should be unaffected.
"""
import re
from io import StringIO
from typing import Iterator

import pandas as pd

from .s3 import list_objects_in_bucket, read_string_from_object

# Data is stored in daily files until the end of the year, at which point it's
# (interactively) consolidated into a "yearly" file.
# Yearly data has a Date column but daily data doesn't; the date must be inferred from
# the object name.
DAILY_SUMMARY_NAME_REGEX = re.compile(r"summaries_(\d{4}_\d{2}_\d{2}).csv")
YEARLY_SUMMARY_NAME_REGEX = re.compile(r"summaries_(\d{4}).csv")


def _read_df(object_name: str) -> pd.DataFrame:
    """
    Given an object name, extract the DataFrame stored in it.
    """
    string_io = StringIO()
    string_io.write(read_string_from_object(object_name))
    string_io.seek(0)
    df = pd.read_csv(string_io)
    string_io.close()
    return df


def get_all_data() -> pd.DataFrame | None:
    """
    Get all stored records as a single DataFrame.
    """
    dfs = []
    daily_data = get_daily_data()
    if daily_data is not None:
        dfs.append(daily_data)
    yearly_data = get_yearly_data()
    if yearly_data is not None:
        dfs.append(yearly_data)
    if len(dfs) == 0:
        return None
    all_data = pd.concat(dfs)
    return all_data


def _daily_object_names() -> Iterator[str]:
    # Get all objects and limit down to the names that look like daily data.
    object_names = list_objects_in_bucket()
    daily_object_names = (
        name for name in object_names if DAILY_SUMMARY_NAME_REGEX.match(name)
    )
    return daily_object_names


def get_daily_data() -> pd.DataFrame | None:
    """
    Get all day-level data merged into a single DataFrame.
    """
    dfs = []
    for name in _daily_object_names():
        df = _read_df(name)
        # Daily data doesn't have a Date column; we have to infer it from the name.
        match = DAILY_SUMMARY_NAME_REGEX.match(name)
        if match is None:
            raise ValueError(f"name {name} does not resemble a daily file.")
        date = match.groups()[0]
        df["Date"] = date.replace("_", "-")
        dfs.append(df)
    # Merge them all into one, since the new Date column will make them distinct.
    if len(dfs) == 0:
        return None
    full_df = pd.concat(dfs)
    # Some of the data may have had an dummy column from its original index values.
    bad_col = "Unnamed: 0"
    if bad_col in full_df.columns:
        full_df = full_df.drop(bad_col, axis=1)
    # Convert the date column into a Pandas date.
    full_df["Date"] = pd.to_datetime(full_df["Date"])
    return full_df


def _yearly_object_names() -> Iterator[str]:
    object_names = list_objects_in_bucket()
    yearly_object_names = (
        name for name in object_names if YEARLY_SUMMARY_NAME_REGEX.match(name)
    )
    return yearly_object_names


def get_yearly_data() -> pd.DataFrame | None:
    """
    Get all year-level data merged into a single DataFrame.
    """
    # Get all objects and limit down to the names that look like daily data.
    # Pull out a DataFrame in each object.
    dfs = [_read_df(name) for name in _yearly_object_names()]
    # No need to add a date column like we do for daily data; yearly data already has
    # one. We can just merge them together as they are.
    if len(dfs) == 0:
        return None
    full_df = pd.concat(dfs)
    # Convert the date column into a Pandas date.
    full_df["Date"] = pd.to_datetime(full_df["Date"])
    return full_df
