from __future__ import annotations

import os
import configparser
import datetime
from typing import List, TYPE_CHECKING
import pkg_resources

import pandas as pd
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

from .s3 import write_string_to_object
from .clean import drop_blank_rows, convert_dollar_cols_to_float


if TYPE_CHECKING:
    from googleapiclient._apis.sheets.v4.resources import SheetsResource


SERVICE_ACCOUNT_FILE = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

config_contents = pkg_resources.resource_string(__name__, "data/config.ini")
config = configparser.ConfigParser()
config.read_string(config_contents.decode())
SHEET_ID = config["DEFAULT"]["SHEET_ID"]
SHEET_RANGE = config["DEFAULT"]["SHEET_RANGE"]


def get_service() -> SheetsResource:
    """
    From https://developers.google.com/sheets/api/quickstart/python
    """
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=SCOPES,
    )
    service = build("sheets", "v4", credentials=creds)
    return service


def table_from_cells(raw_table: List[List[str]], col_idx: slice) -> pd.DataFrame:
    """
    Create a DataFrame from a table and a group of columns in it.
    """
    # See where the first blank row occurs in the given columns.
    first_blank = len(raw_table)
    for i, row in enumerate(raw_table):
        if len(row) <= col_idx.start:
            first_blank = i
            break
    # Now we know the desired column range *and* row range, so we can build
    # the table.
    rows_in_range = raw_table[:first_blank]

    def row_from_slice(row, _slice):
        if len(row) < _slice.start:
            slice_len = _slice.stop - _slice.start
            return [] * slice_len
        else:
            if len(row) < _slice.stop:
                return row[_slice]
            # Else, there are some elements in the range but not enough to get to "stop"
            else:
                n_missing = _slice.stop - len(row) - 1
                filled_row = row + [] * n_missing
                return filled_row[_slice]

    rows_in_range = [row_from_slice(r, col_idx) for r in rows_in_range]
    col_headers, *values = rows_in_range
    return pd.DataFrame(values, columns=col_headers)


def save_df(df: pd.DataFrame, name: str | None = None) -> None:
    """
    Save a DataFrame to S3.

    If `name` param is None, will use today's date to create a csv name like
    `summaries_2022_01_01.csv`.
    """
    if name is None:
        today = datetime.date.today().isoformat().replace("-", "_")
        name = f"summaries_{today}.csv"
    print("Writing DataFrame...")
    print(df.reset_index(drop=True).to_string())
    csv_text = df.to_csv(index=False)
    if not csv_text:
        msg = "CSV text is empty"
        raise ValueError(msg)
    write_string_to_object(object_name=name, text=csv_text)


if __name__ == "__main__":
    service = get_service()
    sheets = service.spreadsheets()
    print("Pulling spreadsheet...")
    my_sheet = sheets.values().get(spreadsheetId=SHEET_ID, range=SHEET_RANGE).execute()
    raw_table = my_sheet["values"]

    # Some sad hard-coding...
    asset_cols = slice(0, 4)
    liability_cols = slice(4, 7)
    # The first row is just the headings: "Assets" & "Liabilities"
    raw_table = raw_table[1:]

    # Extract the right cells and clean up dollar columns.
    asset_df = table_from_cells(raw_table, asset_cols)
    asset_df = drop_blank_rows(asset_df)
    asset_df = convert_dollar_cols_to_float(asset_df)
    liability_df = table_from_cells(raw_table, liability_cols)
    liability_df = drop_blank_rows(liability_df)
    liability_df = convert_dollar_cols_to_float(liability_df)

    # Union into a single DataFrame.
    asset_df["Type"] = "asset"
    liability_df["Type"] = "liability"
    liability_df["Accessible"] = "Y"
    full_df = pd.concat([asset_df, liability_df])
    # Add a date column.
    date = pd.to_datetime(datetime.date.today().isoformat())
    full_df["Date"] = date

    save_df(full_df)
