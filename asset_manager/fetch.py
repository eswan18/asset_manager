from __future__ import annotations

import configparser
import datetime
import os
import re
from decimal import Decimal
from typing import TYPE_CHECKING

import pkg_resources
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from .db import get_connection_context
from .models import Record, RecordType
from .repository import insert_records

if TYPE_CHECKING:
    from googleapiclient._apis.sheets.v4.resources import SheetsResource


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
    service_account_file = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    creds = Credentials.from_service_account_file(
        service_account_file,
        scopes=SCOPES,
    )
    service = build("sheets", "v4", credentials=creds)
    return service


def dollars_to_decimal(dollar_str: str) -> Decimal:
    """Convert a dollar string like '$1,234.56' to a Decimal."""
    pattern = r"\d+(,\d{3})*(.\d\d)?"
    matches = re.search(pattern, dollar_str)
    if matches is not None:
        return Decimal(matches[0].replace(",", ""))
    elif "$ -" in dollar_str:
        return Decimal("0")
    else:
        raise ValueError(f"can't parse '{dollar_str}'")


def parse_records_from_table(
    raw_table: list[list[str]],
    col_idx: slice,
    record_type: RecordType,
    record_date: datetime.date,
) -> list[Record]:
    """
    Parse records from a raw table slice.

    Args:
        raw_table: Raw table data from Google Sheets
        col_idx: Slice indicating which columns to use
        record_type: Whether these are assets or liabilities
        record_date: The date to assign to all records
    """
    # Find where the first blank row occurs in the given columns
    first_blank = len(raw_table)
    for i, row in enumerate(raw_table):
        if len(row) <= col_idx.start:
            first_blank = i
            break

    rows_in_range = raw_table[:first_blank]

    # Extract the slice from each row, handling short rows
    def row_from_slice(row: list[str], _slice: slice) -> list[str]:
        if len(row) < _slice.start:
            return [""] * (_slice.stop - _slice.start)
        return row[_slice] + [""] * max(0, _slice.stop - len(row))

    rows_in_range = [row_from_slice(r, col_idx) for r in rows_in_range]

    if not rows_in_range:
        return []

    col_headers, *values = rows_in_range

    # Find column indices
    desc_idx = col_headers.index("Description") if "Description" in col_headers else 0
    # Amount is typically the column with dollar values
    amount_idx = None
    accessible_idx = None
    for idx, header in enumerate(col_headers):
        if header == "Accessible":
            accessible_idx = idx
        elif header not in ("Description", "Liquidity") and amount_idx is None:
            # First non-Description, non-Liquidity column is likely the amount
            amount_idx = idx

    if amount_idx is None:
        amount_idx = 1  # Default fallback

    records = []
    for row in values:
        # Skip blank rows
        if len(row) <= desc_idx or not row[desc_idx].strip():
            continue

        description = row[desc_idx].strip()
        amount_str = row[amount_idx] if len(row) > amount_idx else "$ -"

        # Parse accessible flag (default True for liabilities)
        if record_type == RecordType.LIABILITY:
            accessible = True
        elif accessible_idx is not None and len(row) > accessible_idx:
            accessible = row[accessible_idx].strip().upper() == "Y"
        else:
            accessible = True

        try:
            amount = dollars_to_decimal(amount_str)
        except ValueError:
            print(f"Warning: Could not parse amount '{amount_str}' for {description}")
            continue

        records.append(
            Record(
                date=record_date,
                type=record_type,
                description=description,
                amount=amount,
                accessible=accessible,
            )
        )

    return records


def fetch_and_save() -> int:
    """
    Fetch data from Google Sheets and save to the database.

    Returns the number of records saved.
    """
    service = get_service()
    sheets = service.spreadsheets()
    print("Pulling spreadsheet...")
    my_sheet = sheets.values().get(spreadsheetId=SHEET_ID, range=SHEET_RANGE).execute()
    raw_table: list[list[str]] = my_sheet["values"]

    # Some sad hard-coding...
    asset_cols = slice(0, 4)
    liability_cols = slice(4, 7)
    # The first row is just the headings: "Assets" & "Liabilities"
    raw_table = raw_table[1:]

    today = datetime.date.today()

    # Parse records from each section
    asset_records = parse_records_from_table(
        raw_table, asset_cols, RecordType.ASSET, today
    )
    liability_records = parse_records_from_table(
        raw_table, liability_cols, RecordType.LIABILITY, today
    )

    all_records = asset_records + liability_records

    print(f"Parsed {len(all_records)} records:")
    for record in all_records:
        print(f"  {record.type.value}: {record.description} = ${record.amount}")

    # Save to database
    with get_connection_context() as conn:
        count = insert_records(conn, all_records)
        print(f"Saved {count} records to database")

    return count


if __name__ == "__main__":
    fetch_and_save()
