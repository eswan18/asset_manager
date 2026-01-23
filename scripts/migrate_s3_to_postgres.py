#!/usr/bin/env python3
"""
One-time migration script to move data from S3 CSV files to PostgreSQL.

Usage:
    ENV=dev uv run python scripts/migrate_s3_to_postgres.py

This script:
1. Lists all CSV files in the S3 bucket
2. Reads each file and parses the records
3. Inserts records into PostgreSQL (with upsert handling)
4. Reports migration statistics

IMPORTANT: This script only READS from S3. It does not modify S3 data.
"""

import re
import sys
from datetime import date, datetime
from decimal import Decimal
from io import StringIO

import pandas as pd

# Add parent directory to path for imports
sys.path.insert(0, str(__file__).rsplit("/", 2)[0])

from asset_manager.db import get_connection_context
from asset_manager.models import Record, RecordType
from asset_manager.repository import insert_records
from asset_manager.s3 import list_objects_in_bucket, read_string_from_object

DAILY_SUMMARY_NAME_REGEX = re.compile(r"summaries_(\d{4}_\d{2}_\d{2}).csv")
YEARLY_SUMMARY_NAME_REGEX = re.compile(r"summaries_(\d{4}).csv")


def parse_amount(value: float | str) -> Decimal:
    """Convert amount to Decimal."""
    if pd.isna(value):
        return Decimal("0")
    return Decimal(str(value))


def parse_record_type(value: str) -> RecordType:
    """Convert type string to RecordType enum."""
    if value.lower() == "asset":
        return RecordType.ASSET
    elif value.lower() == "liability":
        return RecordType.LIABILITY
    else:
        raise ValueError(f"Unknown record type: {value}")


def records_from_dataframe(
    df: pd.DataFrame, record_date: date | None = None
) -> list[Record]:
    """
    Convert a pandas DataFrame to a list of Record objects.

    If record_date is provided, it's used for all records (for daily files).
    Otherwise, the Date column in the DataFrame is used (for yearly files).
    """
    records = []

    for _, row in df.iterrows():
        # Get the date from the row or use the provided date
        if record_date is not None:
            rec_date = record_date
        elif "Date" in row and pd.notna(row["Date"]):
            if isinstance(row["Date"], str):
                rec_date = datetime.fromisoformat(row["Date"].split("T")[0]).date()
            else:
                rec_date = pd.to_datetime(row["Date"]).date()
        else:
            print(f"Warning: No date for row {row}, skipping")
            continue

        # Skip rows without a description
        if (
            "Description" not in row
            or pd.isna(row["Description"])
            or not str(row["Description"]).strip()
        ):
            continue

        try:
            record = Record(
                date=rec_date,
                type=parse_record_type(row["Type"]),
                description=str(row["Description"]).strip(),
                amount=parse_amount(row["Amount"]),
            )
            records.append(record)
        except Exception as e:
            print(f"Warning: Could not parse row {row}: {e}")
            continue

    return records


def read_csv_from_s3(object_name: str) -> pd.DataFrame:
    """Read a CSV file from S3 into a DataFrame."""
    content = read_string_from_object(object_name)
    return pd.read_csv(StringIO(content))


def migrate_daily_files() -> tuple[int, int]:
    """
    Migrate all daily CSV files from S3.

    Returns (files_processed, records_migrated).
    """
    object_names = list_objects_in_bucket()
    daily_files = [
        name for name in object_names if DAILY_SUMMARY_NAME_REGEX.match(name)
    ]

    print(f"Found {len(daily_files)} daily files to migrate")

    total_records = 0
    files_processed = 0

    with get_connection_context() as conn:
        for filename in sorted(daily_files):
            match = DAILY_SUMMARY_NAME_REGEX.match(filename)
            if not match:
                continue

            # Parse date from filename (format: summaries_YYYY_MM_DD.csv)
            date_str = match.group(1)
            year, month, day = map(int, date_str.split("_"))
            file_date = date(year, month, day)

            print(f"Processing {filename} (date: {file_date})...")

            try:
                df = read_csv_from_s3(filename)
                records = records_from_dataframe(df, record_date=file_date)

                if records:
                    inserted = insert_records(conn, records)
                    total_records += inserted
                    print(f"  -> Inserted {inserted} records")

                files_processed += 1
            except Exception as e:
                print(f"  -> Error: {e}")

    return files_processed, total_records


def migrate_yearly_files() -> tuple[int, int]:
    """
    Migrate all yearly consolidated CSV files from S3.

    Returns (files_processed, records_migrated).
    """
    object_names = list_objects_in_bucket()
    yearly_files = [
        name for name in object_names if YEARLY_SUMMARY_NAME_REGEX.match(name)
    ]

    print(f"Found {len(yearly_files)} yearly files to migrate")

    total_records = 0
    files_processed = 0

    with get_connection_context() as conn:
        for filename in sorted(yearly_files):
            print(f"Processing {filename}...")

            try:
                df = read_csv_from_s3(filename)
                # Yearly files have Date column in the data
                records = records_from_dataframe(df, record_date=None)

                if records:
                    inserted = insert_records(conn, records)
                    total_records += inserted
                    print(f"  -> Inserted {inserted} records")

                files_processed += 1
            except Exception as e:
                print(f"  -> Error: {e}")

    return files_processed, total_records


def main():
    print("=" * 60)
    print("S3 to PostgreSQL Migration")
    print("=" * 60)
    print()

    # Migrate yearly files first (they contain older data)
    print("Migrating yearly files...")
    yearly_files, yearly_records = migrate_yearly_files()
    print()

    # Migrate daily files
    print("Migrating daily files...")
    daily_files, daily_records = migrate_daily_files()
    print()

    # Summary
    print("=" * 60)
    print("Migration Complete!")
    print("=" * 60)
    print(f"Yearly files processed: {yearly_files}")
    print(f"Yearly records migrated: {yearly_records}")
    print(f"Daily files processed: {daily_files}")
    print(f"Daily records migrated: {daily_records}")
    print(f"Total records: {yearly_records + daily_records}")


if __name__ == "__main__":
    main()
