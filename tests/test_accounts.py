"""Tests for the account service: rules and the save transaction."""

from datetime import date
from decimal import Decimal

import pytest

from asset_manager.accounts import (
    AccountError,
    create_account,
    parse_amount,
    retire_account,
    retire_blocker,
    save_snapshot,
    unretire_account,
    update_account,
)
from asset_manager.models import ProportionalFormula, RecordType
from asset_manager.repository import get_account, get_all_records, upsert_amounts

TODAY = date(2026, 9, 6)
RATE = ProportionalFormula(rate=Decimal("0.15"))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1531.32", Decimal("1531.32")),
        ("$1,531.32", Decimal("1531.32")),
        (" 1,531 ", Decimal("1531.00")),
        ("-17.44", Decimal("-17.44")),
        ("(17.44)", Decimal("-17.44")),
        ("0", Decimal("0.00")),
        ("10.005", Decimal("10.01")),
    ],
)
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "1.2.3", "NaN", "Infinity"])
def test_parse_amount_rejects_junk(text):
    with pytest.raises(AccountError):
        parse_amount(text)


@pytest.mark.db
class TestCreateAndUpdate:
    def test_create_strips_name(self, db_connection):
        account = create_account(
            db_connection, "  Savings   Account ", RecordType.ASSET
        )
        assert account.name == "Savings Account"
        assert account.id is not None

    def test_create_rejects_blank_name(self, db_connection):
        with pytest.raises(AccountError, match="Name is required"):
            create_account(db_connection, "   ", RecordType.ASSET)

    def test_create_rejects_duplicate_name_within_type(self, db_connection):
        create_account(db_connection, "Savings", RecordType.ASSET)
        with pytest.raises(AccountError, match="already exists"):
            create_account(db_connection, "Savings", RecordType.ASSET)
        create_account(db_connection, "Savings", RecordType.LIABILITY)

    def test_computed_needs_an_input(self, db_connection):
        with pytest.raises(AccountError, match="at least one input"):
            create_account(db_connection, "Tax", RecordType.LIABILITY, RATE, [])

    def test_input_must_exist_and_be_plain_and_active(self, db_connection):
        schwab = create_account(db_connection, "Schwab", RecordType.ASSET)
        tax = create_account(
            db_connection, "Tax", RecordType.LIABILITY, RATE, [schwab.id]
        )
        retired = create_account(db_connection, "Old", RecordType.ASSET)
        retire_account(db_connection, retired.id, TODAY)

        with pytest.raises(AccountError, match="does not exist"):
            create_account(db_connection, "X", RecordType.LIABILITY, RATE, [9999])
        with pytest.raises(AccountError, match="is computed"):
            create_account(db_connection, "X", RecordType.LIABILITY, RATE, [tax.id])
        with pytest.raises(AccountError, match="is retired"):
            create_account(db_connection, "X", RecordType.LIABILITY, RATE, [retired.id])

    def test_inputs_are_deduplicated_and_sorted(self, db_connection):
        a = create_account(db_connection, "A", RecordType.ASSET)
        b = create_account(db_connection, "B", RecordType.ASSET)
        tax = create_account(
            db_connection, "Tax", RecordType.LIABILITY, RATE, [b.id, a.id, b.id]
        )
        assert tax.input_ids == [a.id, b.id]

    def test_update_renames_and_rejects_collision(self, db_connection):
        a = create_account(db_connection, "A", RecordType.ASSET)
        create_account(db_connection, "B", RecordType.ASSET)
        updated = update_account(db_connection, a.id, "A2")
        assert updated.name == "A2"
        with pytest.raises(AccountError, match="already exists"):
            update_account(db_connection, a.id, "B")
        # Keeping your own name is fine
        update_account(db_connection, a.id, "A2")

    def test_update_cannot_use_self_as_input(self, db_connection):
        a = create_account(db_connection, "A", RecordType.LIABILITY)
        with pytest.raises(AccountError, match="its own input"):
            update_account(db_connection, a.id, "A", RATE, [a.id])

    def test_an_input_cannot_be_made_computed(self, db_connection):
        schwab = create_account(db_connection, "Schwab", RecordType.ASSET)
        other = create_account(db_connection, "Other", RecordType.ASSET)
        create_account(db_connection, "Tax", RecordType.LIABILITY, RATE, [schwab.id])
        with pytest.raises(AccountError, match="is an input to Tax"):
            update_account(db_connection, schwab.id, "Schwab", RATE, [other.id])

    def test_update_can_add_formula_to_plain_account(self, db_connection):
        schwab = create_account(db_connection, "Schwab", RecordType.ASSET)
        tax = create_account(db_connection, "Tax", RecordType.LIABILITY)
        updated = update_account(db_connection, tax.id, "Tax", RATE, [schwab.id])
        assert updated.formula == RATE
        assert updated.input_ids == [schwab.id]
        loaded = get_account(db_connection, tax.id)
        assert loaded is not None and loaded.input_ids == [schwab.id]


@pytest.mark.db
class TestRetire:
    def test_retire_blocked_when_latest_amount_is_nonzero(self, db_connection):
        a = create_account(db_connection, "A", RecordType.ASSET)
        upsert_amounts(db_connection, date(2026, 1, 1), {a.id: Decimal("5")})
        db_connection.commit()
        assert retire_blocker(db_connection, a) is not None
        with pytest.raises(AccountError, match="Set it to zero and save"):
            retire_account(db_connection, a.id, TODAY)

    def test_retire_blocked_when_it_feeds_a_formula(self, db_connection):
        schwab = create_account(db_connection, "Schwab", RecordType.ASSET)
        create_account(db_connection, "Tax", RecordType.LIABILITY, RATE, [schwab.id])
        with pytest.raises(AccountError, match="is an input to Tax"):
            retire_account(db_connection, schwab.id, TODAY)

    def test_retire_allowed_at_zero_or_never_snapshotted(self, db_connection):
        never = create_account(db_connection, "Never", RecordType.ASSET)
        zero = create_account(db_connection, "Zero", RecordType.ASSET)
        upsert_amounts(db_connection, date(2026, 1, 1), {zero.id: Decimal("0")})
        db_connection.commit()
        assert retire_blocker(db_connection, never) is None
        assert retire_account(db_connection, never.id, TODAY).retired_at == TODAY
        assert retire_account(db_connection, zero.id, TODAY).retired_at == TODAY
        loaded = get_account(db_connection, zero.id)
        assert loaded is not None and loaded.retired_at == TODAY

    def test_retire_twice_and_unretire(self, db_connection):
        a = create_account(db_connection, "A", RecordType.ASSET)
        retire_account(db_connection, a.id, TODAY)
        with pytest.raises(AccountError, match="already retired"):
            retire_account(db_connection, a.id, TODAY)
        assert unretire_account(db_connection, a.id).retired_at is None
        with pytest.raises(AccountError, match="is not retired"):
            unretire_account(db_connection, a.id)


@pytest.mark.db
class TestSaveSnapshot:
    def _setup(self, conn):
        schwab = create_account(conn, "Schwab", RecordType.ASSET)
        cash = create_account(conn, "Cash", RecordType.ASSET)
        tax = create_account(
            conn,
            "Tax",
            RecordType.LIABILITY,
            ProportionalFormula(rate=Decimal("0.15"), cost_basis=Decimal("100")),
            [schwab.id],
        )
        old = create_account(conn, "Old", RecordType.ASSET)
        retire_account(conn, old.id, date(2026, 1, 1))
        return schwab, cash, tax, old

    def test_writes_every_active_account_and_updates_basis(self, db_connection):
        schwab, cash, tax, old = self._setup(db_connection)
        count = save_snapshot(
            db_connection,
            {schwab.id: Decimal("1000"), cash.id: Decimal("50")},
            {tax.id: Decimal("400")},
            TODAY,
        )
        assert count == 3
        rows = {(r.description, r.amount) for r in get_all_records(db_connection)}
        assert rows == {
            ("Schwab", Decimal("1000.00")),
            ("Cash", Decimal("50.00")),
            ("Tax", Decimal("90.00")),
        }
        loaded = get_account(db_connection, tax.id)
        assert loaded is not None and loaded.formula is not None
        assert loaded.formula.cost_basis == Decimal("400.00")

    def test_same_day_save_replaces(self, db_connection):
        schwab, cash, tax, _ = self._setup(db_connection)
        save_snapshot(
            db_connection,
            {schwab.id: Decimal("1000"), cash.id: Decimal("50")},
            {},
            TODAY,
        )
        save_snapshot(
            db_connection,
            {schwab.id: Decimal("2000"), cash.id: Decimal("50")},
            {},
            TODAY,
        )
        rows = {(r.description, r.amount) for r in get_all_records(db_connection)}
        assert rows == {
            ("Schwab", Decimal("2000.00")),
            ("Cash", Decimal("50.00")),
            ("Tax", Decimal("285.00")),
        }

    def test_missing_value_writes_nothing_including_basis(self, db_connection):
        schwab, cash, tax, _ = self._setup(db_connection)
        with pytest.raises(AccountError, match="Missing value for Cash"):
            save_snapshot(
                db_connection,
                {schwab.id: Decimal("1000")},
                {tax.id: Decimal("999")},
                TODAY,
            )
        assert get_all_records(db_connection) == []
        loaded = get_account(db_connection, tax.id)
        assert loaded is not None and loaded.formula is not None
        assert loaded.formula.cost_basis == Decimal("100")

    def test_rejects_retired_computed_and_unknown_ids(self, db_connection):
        schwab, cash, tax, old = self._setup(db_connection)
        base = {schwab.id: Decimal("1"), cash.id: Decimal("1")}
        with pytest.raises(AccountError, match="not an active account"):
            save_snapshot(db_connection, {**base, old.id: Decimal("0")}, {}, TODAY)
        with pytest.raises(AccountError, match="is computed"):
            save_snapshot(db_connection, {**base, tax.id: Decimal("0")}, {}, TODAY)
        with pytest.raises(AccountError, match="not an active computed account"):
            save_snapshot(db_connection, base, {cash.id: Decimal("0")}, TODAY)
        assert get_all_records(db_connection) == []
