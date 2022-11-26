from __future__ import annotations

import os
import re
import pickle
import configparser
import datetime
from typing import List, TYPE_CHECKING
import pkg_resources

import pandas as pd
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

from .storage import write_string_to_object


if TYPE_CHECKING:
    from googleapiclient._apis.sheets.v4.resources import SheetsResource


config_contents = pkg_resources.resource_string(__name__, "data/config.ini")
config = configparser.ConfigParser()
config.read_string(config_contents.decode())
SHEET_ID = config["DEFAULT"]["SHEET_ID"]
SHEET_RANGE = config["DEFAULT"]["SHEET_RANGE"]

# If modifying these scopes, delete the file token.pickle.
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def setup_service() -> SheetsResource:
    """
    From https://developers.google.com/sheets/api/quickstart/python
    """
    creds = None
    # The file token.pickle stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)

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


def drop_blank_rows(df: pd.DataFrame) -> pd.DataFrame:
    bad_rows = df.isnull().sum(axis=1) == df.shape[1]
    # Another heuristic: Description should never be blank.
    bad_rows |= df["Description"].str.len() == 0
    return df.loc[~bad_rows]


def convert_dollar_cols_to_float(df: pd.DataFrame) -> pd.DataFrame:
    """
    Find string cols in a DF that contain dollar amounts and convert them to float types
    """

    def dollars_to_float(dollar_str):
        pattern = r"\d+(,\d{3})*(.\d\d)?"
        matches = re.search(pattern, dollar_str)
        if matches is not None:
            as_float = float(matches[0].replace(",", ""))
            return as_float
        elif "$ -" in dollar_str:
            return 0
        else:
            raise ValueError(f"can't parse '{dollar_str}'")

    df2 = df.copy()
    for col in df:
        if all(df[col].str.contains("$", regex=False)):
            df2[col] = df[col].apply(dollars_to_float)
    return df2


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


if __name__ == '__main__':
    service = setup_service()
    sheets = service.spreadsheets()
    print("Pulling spreadsheet...")
    my_sheet = sheets.values().get(spreadsheetId=SHEET_ID, range=SHEET_RANGE).execute()
    raw_table = my_sheet["values"]

    # Some sad hard-coding...
    asset_cols = slice(0, 4)
    liability_cols = slice(4, 7)
    # The first row is just the headings: "Assets" & "Liabilities"
    raw_table = raw_table[1:]

    asset_df = table_from_cells(raw_table, asset_cols)
    liability_df = table_from_cells(raw_table, liability_cols)

    # On the chance some blank rows slip in, get rid of them.
    asset_df = drop_blank_rows(asset_df)
    liability_df = drop_blank_rows(liability_df)

    asset_df = convert_dollar_cols_to_float(asset_df)
    liability_df = convert_dollar_cols_to_float(liability_df)

    # Merge into a single DF so we can group and sum.
    asset_df["Type"] = "asset"
    liability_df["Type"] = "liability"
    liability_df["Accessible"] = "Y"
    full_df = pd.concat([asset_df, liability_df])

    save_df(full_df)