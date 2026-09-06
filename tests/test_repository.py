from datetime import date
from decimal import Decimal

import psycopg
import pytest

from asset_manager.models import Account, ProportionalFormula, Record, RecordType
from asset_manager.repository import (
    get_account_by_name,
    get_accounts,
    get_all_records,
    get_latest_snapshot_records,
    get_records_by_date_range,
    get_summary_by_date,
    insert_account,
    insert_records,
    upsert_amounts,
)


def make_account(
    conn, name: str, type: RecordType = RecordType.ASSET, **kwargs
) -> Account:
    return insert_account(conn, Account(name=name, type=type, **kwargs))


@pytest.mark.db
class TestSnapshots:
    def test_upsert_and_fetch_records(self, db_connection):
        savings = make_account(db_connection, "Savings Account")
        card = make_account(db_connection, "Credit Card", RecordType.LIABILITY)

        count = upsert_amounts(
            db_connection,
            date(2024, 1, 15),
            {savings.id: Decimal("10000.00"), card.id: Decimal("500.00")},
        )
        assert count == 2

        fetched = get_all_records(db_connection)
        assert [(r.type, r.description, r.amount, r.account_id) for r in fetched] == [
            (RecordType.ASSET, "Savings Account", Decimal("10000.00"), savings.id),
            (RecordType.LIABILITY, "Credit Card", Decimal("500.00"), card.id),
        ]

    def test_upsert_replaces_same_date(self, db_connection):
        savings = make_account(db_connection, "Savings Account")
        upsert_amounts(
            db_connection, date(2024, 1, 15), {savings.id: Decimal("10000.00")}
        )
        upsert_amounts(
            db_connection, date(2024, 1, 15), {savings.id: Decimal("15000.00")}
        )

        fetched = get_all_records(db_connection)
        assert len(fetched) == 1
        assert fetched[0].amount == Decimal("15000.00")

    def test_upsert_empty(self, db_connection):
        assert upsert_amounts(db_connection, date(2024, 1, 15), {}) == 0
        assert get_all_records(db_connection) == []

    def test_get_records_by_date_range(self, db_connection):
        a1 = make_account(db_connection, "Account 1")
        a2 = make_account(db_connection, "Account 2")
        a3 = make_account(db_connection, "Account 3")
        upsert_amounts(db_connection, date(2024, 1, 10), {a1.id: Decimal("1000.00")})
        upsert_amounts(db_connection, date(2024, 1, 15), {a2.id: Decimal("2000.00")})
        upsert_amounts(db_connection, date(2024, 1, 20), {a3.id: Decimal("3000.00")})

        fetched = get_records_by_date_range(
            db_connection, date(2024, 1, 12), date(2024, 1, 18)
        )
        assert [r.description for r in fetched] == ["Account 2"]

    def test_get_latest_snapshot_records(self, db_connection):
        a1 = make_account(db_connection, "Account 1")
        a2 = make_account(db_connection, "Account 2")
        upsert_amounts(
            db_connection, date(2024, 1, 10), {a1.id: Decimal("1"), a2.id: Decimal("2")}
        )
        upsert_amounts(db_connection, date(2024, 1, 20), {a1.id: Decimal("3")})

        latest = get_latest_snapshot_records(db_connection)
        assert [(r.date, r.description, r.amount) for r in latest] == [
            (date(2024, 1, 20), "Account 1", Decimal("3.00"))
        ]

    def test_get_summary_by_date(self, db_connection):
        a1 = make_account(db_connection, "Asset 1")
        a2 = make_account(db_connection, "Asset 2")
        l1 = make_account(db_connection, "Liability 1", RecordType.LIABILITY)
        upsert_amounts(
            db_connection,
            date(2024, 1, 15),
            {
                a1.id: Decimal("1000.00"),
                a2.id: Decimal("2000.00"),
                l1.id: Decimal("500.00"),
            },
        )

        summaries = get_summary_by_date(db_connection)
        assert [(s.type, s.total_amount) for s in summaries] == [
            (RecordType.ASSET, Decimal("3000.00")),
            (RecordType.LIABILITY, Decimal("500.00")),
        ]

    def test_insert_records_bridge_creates_accounts_by_name(self, db_connection):
        records = [
            Record(
                date=date(2024, 1, 15),
                type=RecordType.ASSET,
                description="Savings",
                amount=Decimal("10"),
            ),
            Record(
                date=date(2024, 1, 15),
                type=RecordType.LIABILITY,
                description="Card",
                amount=Decimal("5"),
            ),
        ]
        assert insert_records(db_connection, records) == 2
        assert [a.name for a in get_accounts(db_connection)] == ["Savings", "Card"]
        assert len(get_all_records(db_connection)) == 2


@pytest.mark.db
class TestAccounts:
    def test_insert_and_get_accounts_round_trips_formula_and_inputs(
        self, db_connection
    ):
        schwab = make_account(db_connection, "Schwab")
        tax = make_account(
            db_connection,
            "Cap Gains Tax",
            RecordType.LIABILITY,
            formula=ProportionalFormula(
                rate=Decimal("0.15"), cost_basis=Decimal("70634.00")
            ),
            input_ids=[schwab.id],
        )
        assert tax.id is not None
        assert tax.created_at is not None

        accounts = get_accounts(db_connection)
        assert [a.name for a in accounts] == ["Schwab", "Cap Gains Tax"]
        assert accounts[0].formula is None
        assert accounts[0].input_ids == []
        assert accounts[1].formula == ProportionalFormula(
            rate=Decimal("0.15"), cost_basis=Decimal("70634.00")
        )
        assert accounts[1].input_ids == [schwab.id]

    def test_get_accounts_can_exclude_retired(self, db_connection):
        make_account(db_connection, "Live")
        make_account(db_connection, "Old", retired_at=date(2026, 1, 1))
        assert [a.name for a in get_accounts(db_connection)] == ["Live", "Old"]
        assert [a.name for a in get_accounts(db_connection, include_retired=False)] == [
            "Live"
        ]

    def test_get_account_by_name_is_per_type(self, db_connection):
        make_account(db_connection, "Winchester", RecordType.ASSET)
        make_account(db_connection, "Winchester", RecordType.LIABILITY)
        asset = get_account_by_name(db_connection, RecordType.ASSET, "Winchester")
        liability = get_account_by_name(
            db_connection, RecordType.LIABILITY, "Winchester"
        )
        assert asset is not None and asset.type == RecordType.ASSET
        assert liability is not None and liability.type == RecordType.LIABILITY
        assert get_account_by_name(db_connection, RecordType.ASSET, "Nope") is None

    def test_name_is_unique_within_type(self, db_connection):
        make_account(db_connection, "Savings")
        with pytest.raises(psycopg.errors.UniqueViolation):
            make_account(db_connection, "Savings")
        db_connection.rollback()
