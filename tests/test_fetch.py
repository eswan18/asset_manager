import os
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from asset_manager.fetch import (
    dollars_to_decimal,
    get_service,
    parse_records_from_table,
)
from asset_manager.models import RecordType


@pytest.mark.skipif(
    os.getenv("CI") is not None or os.getenv("GOOGLE_APPLICATION_CREDENTIALS") is None,
    reason="no Google credentials"
)
def test_get_service_runs_without_error():
    _ = get_service()


def test_dollars_to_decimal():
    assert dollars_to_decimal("$1,234.56") == Decimal("1234.56")
    assert dollars_to_decimal("$100.00") == Decimal("100.00")
    assert dollars_to_decimal("$ -") == Decimal("0")
    assert dollars_to_decimal("$0.00") == Decimal("0.00")


def test_dollars_to_decimal_invalid():
    with pytest.raises(ValueError):
        dollars_to_decimal("not a dollar amount")


def test_parse_records_from_table_assets():
    raw_table = [
        ["Description", "Amount", "Accessible", "Liquidity"],
        ["Savings", "$1,000.00", "Y", "$500.00"],
        ["401k", "$5,000.00", "N", "$0.00"],
    ]
    col_idx = slice(0, 4)
    record_date = date(2024, 1, 15)

    records = parse_records_from_table(raw_table, col_idx, RecordType.ASSET, record_date)

    assert len(records) == 2
    assert records[0].description == "Savings"
    assert records[0].amount == Decimal("1000.00")
    assert records[0].type == RecordType.ASSET
    assert records[0].date == record_date

    assert records[1].description == "401k"
    assert records[1].amount == Decimal("5000.00")


def test_parse_records_from_table_liabilities():
    raw_table = [
        ["Description", "Amount", "Accessible"],
        ["Credit Card", "$500.00", "Y"],
        ["Mortgage", "$200,000.00", "Y"],
    ]
    col_idx = slice(0, 3)
    record_date = date(2024, 1, 15)

    records = parse_records_from_table(raw_table, col_idx, RecordType.LIABILITY, record_date)

    assert len(records) == 2
    assert records[0].description == "Credit Card"
    assert records[1].description == "Mortgage"


def test_parse_records_from_table_skips_blank_rows():
    raw_table = [
        ["Description", "Amount", "Accessible"],
        ["Savings", "$1,000.00", "Y"],
        ["", "$0.00", ""],  # Blank description - should be skipped
        ["Checking", "$500.00", "Y"],
    ]
    col_idx = slice(0, 3)
    record_date = date(2024, 1, 15)

    records = parse_records_from_table(raw_table, col_idx, RecordType.ASSET, record_date)

    assert len(records) == 2
    assert records[0].description == "Savings"
    assert records[1].description == "Checking"


def test_parse_records_from_table_empty():
    raw_table = [
        ["Description", "Amount", "Accessible"],
    ]
    col_idx = slice(0, 3)
    record_date = date(2024, 1, 15)

    records = parse_records_from_table(raw_table, col_idx, RecordType.ASSET, record_date)

    assert len(records) == 0
