from __future__ import annotations

import configparser
import datetime
import os
import re
from decimal import Decimal
from importlib import resources
from typing import Any

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from psycopg import Connection
from pydantic import BaseModel

from .clock import today
from .db import get_connection_context
from .models import Account, RecordType
from .repository import get_account_by_name, insert_account, upsert_amounts

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

config_contents = (
    resources.files("asset_manager").joinpath("data/config.ini").read_text()
)
config = configparser.ConfigParser()
config.read_string(config_contents)
SHEET_ID = config["DEFAULT"]["SHEET_ID"]
SHEET_RANGE = config["DEFAULT"]["SHEET_RANGE"]


class ParsedRow(BaseModel):
    """One line of the sheet: an account name and its amount."""

    type: RecordType
    description: str
    amount: Decimal


def get_service() -> Any:
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


def parse_rows_from_table(
    raw_table: list[list[str]],
    col_idx: slice,
    record_type: RecordType,
) -> list[ParsedRow]:
    """
    Parse rows from a raw table slice.

    Args:
        raw_table: Raw table data from Google Sheets
        col_idx: Slice indicating which columns to use
        record_type: Whether these are assets or liabilities
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
    for idx, header in enumerate(col_headers):
        if (
            header not in ("Description", "Liquidity", "Accessible")
            and amount_idx is None
        ):
            # First non-Description, non-Liquidity, non-Accessible column is likely the amount
            amount_idx = idx

    if amount_idx is None:
        amount_idx = 1  # Default fallback

    rows = []
    for row in values:
        # Skip blank rows
        if len(row) <= desc_idx or not row[desc_idx].strip():
            continue

        description = row[desc_idx].strip()
        amount_str = row[amount_idx] if len(row) > amount_idx else "$ -"

        try:
            amount = dollars_to_decimal(amount_str)
        except ValueError:
            print(f"Warning: Could not parse amount '{amount_str}' for {description}")
            continue

        rows.append(ParsedRow(type=record_type, description=description, amount=amount))

    return rows


def fetch_rows() -> list[ParsedRow]:
    """
    Fetch data from Google Sheets and parse into rows.

    Returns the parsed rows without saving to the database.
    """
    service = get_service()
    sheets = service.spreadsheets()
    print("Pulling spreadsheet...")
    my_sheet = sheets.values().get(spreadsheetId=SHEET_ID, range=SHEET_RANGE).execute()
    raw_table: list[list[str]] = my_sheet.get("values", [])

    if not raw_table:
        print("No data found in the spreadsheet")
        return []

    # Some sad hard-coding...
    asset_cols = slice(0, 4)
    liability_cols = slice(4, 7)
    # The first row is just the headings: "Assets" & "Liabilities"
    raw_table = raw_table[1:]

    asset_rows = parse_rows_from_table(raw_table, asset_cols, RecordType.ASSET)
    liability_rows = parse_rows_from_table(
        raw_table, liability_cols, RecordType.LIABILITY
    )
    return asset_rows + liability_rows


def describe_rows(conn: Connection, rows: list[ParsedRow]) -> list[str]:
    """One printable line per row, noting accounts that would be created or skipped."""
    lines = []
    for row in rows:
        account = get_account_by_name(conn, row.type, row.description)
        if account is None:
            note = "  (new account)"
        elif not account.is_active:
            note = "  (retired, skipped)"
        else:
            note = ""
        lines.append(f"  {row.type.value}: {row.description} = ${row.amount}{note}")
    return lines


def save_rows(conn: Connection, rows: list[ParsedRow], as_of: datetime.date) -> int:
    """Write the sheet's values for `as_of`.

    Unknown descriptions become plain accounts. Retired accounts are skipped,
    with a warning if the sheet still shows a non-zero amount for one.
    Formulas are not evaluated: the sheet's own computed cells are written as-is.
    Commits.
    """
    amounts: dict[int, Decimal] = {}
    for row in rows:
        account = get_account_by_name(conn, row.type, row.description)
        if account is None:
            account = insert_account(conn, Account(name=row.description, type=row.type))
            print(f"Created account: {row.type.value} {row.description}")
        elif not account.is_active:
            if row.amount != 0:
                print(
                    f"Warning: {row.description} is retired but the sheet shows "
                    f"${row.amount}; skipping"
                )
            continue
        if account.id is not None:
            amounts[account.id] = row.amount
    count = upsert_amounts(conn, as_of, amounts)
    conn.commit()
    return count


def fetch_and_save() -> int:
    """
    Fetch data from Google Sheets and save to the database.

    Returns the number of records saved.
    """
    rows = fetch_rows()
    if not rows:
        return 0

    print(f"Parsed {len(rows)} rows:")
    with get_connection_context() as conn:
        for line in describe_rows(conn, rows):
            print(line)
        count = save_rows(conn, rows, today())
        print(f"Saved {count} records to database")
    return count
