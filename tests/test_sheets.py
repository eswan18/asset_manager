import os
from datetime import date
from decimal import Decimal

import pytest

from asset_manager.accounts import create_account, retire_account
from asset_manager.models import RecordType
from asset_manager.repository import get_accounts, get_all_records
from asset_manager.sheets import (
    ParsedRow,
    describe_rows,
    dollars_to_decimal,
    get_service,
    parse_rows_from_table,
    save_rows,
)


@pytest.mark.skipif(
    os.getenv("CI") is not None or os.getenv("GOOGLE_APPLICATION_CREDENTIALS") is None,
    reason="no Google credentials",
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


def test_parse_rows_from_table_assets():
    raw_table = [
        ["Description", "Amount", "Accessible", "Liquidity"],
        ["Savings", "$1,000.00", "Y", "$500.00"],
        ["401k", "$5,000.00", "N", "$0.00"],
    ]
    rows = parse_rows_from_table(raw_table, slice(0, 4), RecordType.ASSET)

    assert len(rows) == 2
    assert rows[0].description == "Savings"
    assert rows[0].amount == Decimal("1000.00")
    assert rows[0].type == RecordType.ASSET
    assert rows[1].description == "401k"
    assert rows[1].amount == Decimal("5000.00")


def test_parse_rows_from_table_liabilities():
    raw_table = [
        ["Description", "Amount", "Accessible"],
        ["Credit Card", "$500.00", "Y"],
        ["Mortgage", "$200,000.00", "Y"],
    ]
    col_idx = slice(0, 3)

    rows = parse_rows_from_table(raw_table, col_idx, RecordType.LIABILITY)

    assert len(rows) == 2
    assert rows[0].description == "Credit Card"
    assert rows[1].description == "Mortgage"


def test_parse_rows_from_table_skips_blank_rows():
    raw_table = [
        ["Description", "Amount", "Accessible"],
        ["Savings", "$1,000.00", "Y"],
        ["", "$0.00", ""],  # Blank description - should be skipped
        ["Checking", "$500.00", "Y"],
    ]
    col_idx = slice(0, 3)

    rows = parse_rows_from_table(raw_table, col_idx, RecordType.ASSET)

    assert len(rows) == 2
    assert rows[0].description == "Savings"
    assert rows[1].description == "Checking"


def test_parse_rows_from_table_empty():
    raw_table = [
        ["Description", "Amount", "Accessible"],
    ]
    col_idx = slice(0, 3)

    rows = parse_rows_from_table(raw_table, col_idx, RecordType.ASSET)

    assert len(rows) == 0


@pytest.mark.db
def test_save_rows_creates_unknown_accounts_and_skips_retired(db_connection, capsys):
    known = create_account(db_connection, "Savings", RecordType.ASSET)
    old = create_account(db_connection, "Old 401k", RecordType.ASSET)
    retire_account(db_connection, old.id, date(2026, 1, 1))
    rows = [
        ParsedRow(type=RecordType.ASSET, description="Savings", amount=Decimal("10")),
        ParsedRow(type=RecordType.ASSET, description="Brokerage", amount=Decimal("20")),
        ParsedRow(type=RecordType.ASSET, description="Old 401k", amount=Decimal("5")),
        ParsedRow(type=RecordType.LIABILITY, description="Card", amount=Decimal("1")),
    ]

    count = save_rows(db_connection, rows, date(2026, 9, 6))

    assert count == 3
    assert [a.name for a in get_accounts(db_connection)] == [
        "Brokerage",
        "Card",
        "Old 401k",
        "Savings",
    ]
    written = {(r.description, r.amount) for r in get_all_records(db_connection)}
    assert written == {
        ("Savings", Decimal("10.00")),
        ("Brokerage", Decimal("20.00")),
        ("Card", Decimal("1.00")),
    }
    assert known.id is not None
    assert "Old 401k is retired" in capsys.readouterr().out


@pytest.mark.db
def test_describe_rows_annotates_new_and_retired(db_connection):
    create_account(db_connection, "Savings", RecordType.ASSET)
    old = create_account(db_connection, "Old", RecordType.ASSET)
    retire_account(db_connection, old.id, date(2026, 1, 1))
    rows = [
        ParsedRow(type=RecordType.ASSET, description="Savings", amount=Decimal("10")),
        ParsedRow(type=RecordType.ASSET, description="New", amount=Decimal("1")),
        ParsedRow(type=RecordType.ASSET, description="Old", amount=Decimal("0")),
    ]
    lines = describe_rows(db_connection, rows)
    assert lines == [
        "  asset: Savings = $10",
        "  asset: New = $1  (new account)",
        "  asset: Old = $0  (retired, skipped)",
    ]
