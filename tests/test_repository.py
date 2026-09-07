from datetime import date
from decimal import Decimal

import psycopg
import pytest

from asset_manager.models import Account, ProportionalFormula, RecordType
from asset_manager.repository import (
    get_account,
    get_account_by_name,
    get_accounts,
    get_all_records,
    get_dependents,
    get_latest_amount,
    get_latest_snapshot_records,
    get_records_by_date_range,
    get_summary_by_date,
    insert_account,
    set_formula,
    set_retired_at,
    update_account,
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
        assert [a.name for a in accounts] == ["Cap Gains Tax", "Schwab"]
        assert accounts[1].formula is None
        assert accounts[1].input_ids == []
        assert accounts[0].formula == ProportionalFormula(
            rate=Decimal("0.15"), cost_basis=Decimal("70634.00")
        )
        assert accounts[0].input_ids == [schwab.id]

    def test_get_accounts_orders_by_name_case_insensitively(self, db_connection):
        make_account(db_connection, "zeta")
        make_account(db_connection, "Alpha")
        make_account(db_connection, "beta")
        make_account(db_connection, "1119 N Winchester Value")
        assert [a.name for a in get_accounts(db_connection)] == [
            "1119 N Winchester Value",
            "Alpha",
            "beta",
            "zeta",
        ]

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


@pytest.mark.db
class TestAccountOperations:
    def test_get_account(self, db_connection):
        savings = make_account(db_connection, "Savings")
        loaded = get_account(db_connection, savings.id)
        assert loaded is not None and loaded.name == "Savings"
        assert get_account(db_connection, 9999) is None

    def test_update_account_replaces_name_formula_and_inputs(self, db_connection):
        a = make_account(db_connection, "A")
        b = make_account(db_connection, "B")
        tax = make_account(
            db_connection,
            "Tax",
            RecordType.LIABILITY,
            formula=ProportionalFormula(rate=Decimal("0.1")),
            input_ids=[a.id],
        )
        update_account(
            db_connection,
            tax.model_copy(
                update={
                    "name": "Tax v2",
                    "formula": ProportionalFormula(
                        rate=Decimal("0.2"), cost_basis=Decimal("5")
                    ),
                    "input_ids": [b.id],
                }
            ),
        )
        loaded = get_account(db_connection, tax.id)
        assert loaded is not None
        assert loaded.name == "Tax v2"
        assert loaded.formula == ProportionalFormula(
            rate=Decimal("0.2"), cost_basis=Decimal("5")
        )
        assert loaded.input_ids == [b.id]

    def test_update_account_can_clear_formula(self, db_connection):
        a = make_account(db_connection, "A")
        tax = make_account(
            db_connection,
            "Tax",
            RecordType.LIABILITY,
            formula=ProportionalFormula(rate=Decimal("0.1")),
            input_ids=[a.id],
        )
        update_account(
            db_connection, tax.model_copy(update={"formula": None, "input_ids": []})
        )
        loaded = get_account(db_connection, tax.id)
        assert loaded is not None and loaded.formula is None and loaded.input_ids == []

    def test_set_formula_only_touches_the_document(self, db_connection):
        a = make_account(db_connection, "A")
        tax = make_account(
            db_connection,
            "Tax",
            RecordType.LIABILITY,
            formula=ProportionalFormula(rate=Decimal("0.1")),
            input_ids=[a.id],
        )
        set_formula(
            db_connection,
            tax.id,
            ProportionalFormula(rate=Decimal("0.1"), cost_basis=Decimal("42")),
        )
        loaded = get_account(db_connection, tax.id)
        assert loaded is not None
        assert loaded.formula == ProportionalFormula(
            rate=Decimal("0.1"), cost_basis=Decimal("42")
        )
        assert loaded.input_ids == [a.id]

    def test_set_retired_at_round_trips(self, db_connection):
        a = make_account(db_connection, "A")
        set_retired_at(db_connection, a.id, date(2026, 9, 1))
        loaded = get_account(db_connection, a.id)
        assert loaded is not None and loaded.retired_at == date(2026, 9, 1)
        set_retired_at(db_connection, a.id, None)
        loaded = get_account(db_connection, a.id)
        assert loaded is not None and loaded.retired_at is None

    def test_get_dependents_lists_active_computed_accounts_only(self, db_connection):
        a = make_account(db_connection, "A")
        live = make_account(
            db_connection,
            "Live Tax",
            RecordType.LIABILITY,
            formula=ProportionalFormula(rate=Decimal("0.1")),
            input_ids=[a.id],
        )
        make_account(
            db_connection,
            "Old Tax",
            RecordType.LIABILITY,
            formula=ProportionalFormula(rate=Decimal("0.1")),
            input_ids=[a.id],
            retired_at=date(2026, 1, 1),
        )
        assert [d.id for d in get_dependents(db_connection, a.id)] == [live.id]
        assert get_dependents(db_connection, live.id) == []

    def test_get_latest_amount_uses_the_accounts_own_latest_row(self, db_connection):
        a = make_account(db_connection, "A")
        b = make_account(db_connection, "B")
        upsert_amounts(
            db_connection, date(2024, 1, 10), {a.id: Decimal("10"), b.id: Decimal("1")}
        )
        upsert_amounts(db_connection, date(2024, 2, 10), {b.id: Decimal("2")})
        assert get_latest_amount(db_connection, a.id) == Decimal("10.00")
        assert get_latest_amount(db_connection, b.id) == Decimal("2.00")
        assert get_latest_amount(db_connection, 9999) is None
