"""Tests for the account service: rules and the save transaction."""

from datetime import date
from decimal import Decimal

import psycopg
import pytest

from sensibility.accounts import (
    AccountError,
    create_account,
    parse_amount,
    retire_account,
    retire_blocker,
    retire_warning,
    save_snapshot,
    unretire_account,
    update_account,
)
from sensibility.models import ProportionalFormula, RecordType
from sensibility.repository import get_account, get_all_records, upsert_amounts
from tests.support import WS

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


@pytest.mark.parametrize("text", ["", "abc", "1.2.3", "NaN", "Infinity", "1e999"])
def test_parse_amount_rejects_junk(text):
    with pytest.raises(AccountError):
        parse_amount(text)


def test_parse_amount_rejects_amounts_too_large_to_store():
    with pytest.raises(AccountError, match="too large"):
        parse_amount("99999999999999999")


@pytest.mark.db
class TestCreateAndUpdate:
    def test_create_strips_name(self, db_connection):
        account = create_account(
            db_connection, WS, "  Savings   Account ", RecordType.ASSET
        )
        assert account.name == "Savings Account"
        assert account.id is not None

    def test_create_rejects_blank_name(self, db_connection):
        with pytest.raises(AccountError, match="Name is required"):
            create_account(db_connection, WS, "   ", RecordType.ASSET)

    def test_create_rejects_duplicate_name_within_type(self, db_connection):
        create_account(db_connection, WS, "Savings", RecordType.ASSET)
        with pytest.raises(AccountError, match="already exists"):
            create_account(db_connection, WS, "Savings", RecordType.ASSET)
        create_account(db_connection, WS, "Savings", RecordType.LIABILITY)

    def test_computed_needs_an_input(self, db_connection):
        with pytest.raises(AccountError, match="at least one input"):
            create_account(db_connection, WS, "Tax", RecordType.LIABILITY, RATE, [])

    def test_input_must_exist_and_be_plain_and_active(self, db_connection):
        schwab = create_account(db_connection, WS, "Schwab", RecordType.ASSET)
        tax = create_account(
            db_connection, WS, "Tax", RecordType.LIABILITY, RATE, [schwab.id]
        )
        retired = create_account(db_connection, WS, "Old", RecordType.ASSET)
        retire_account(db_connection, WS, retired.id, TODAY)

        with pytest.raises(AccountError, match="does not exist"):
            create_account(db_connection, WS, "X", RecordType.LIABILITY, RATE, [9999])
        with pytest.raises(AccountError, match="is computed"):
            create_account(db_connection, WS, "X", RecordType.LIABILITY, RATE, [tax.id])
        with pytest.raises(AccountError, match="is retired"):
            create_account(
                db_connection, WS, "X", RecordType.LIABILITY, RATE, [retired.id]
            )

    def test_inputs_are_deduplicated_and_sorted(self, db_connection):
        a = create_account(db_connection, WS, "A", RecordType.ASSET)
        b = create_account(db_connection, WS, "B", RecordType.ASSET)
        tax = create_account(
            db_connection, WS, "Tax", RecordType.LIABILITY, RATE, [b.id, a.id, b.id]
        )
        assert tax.input_ids == [a.id, b.id]

    def test_update_renames_and_rejects_collision(self, db_connection):
        a = create_account(db_connection, WS, "A", RecordType.ASSET)
        create_account(db_connection, WS, "B", RecordType.ASSET)
        updated = update_account(db_connection, WS, a.id, "A2")
        assert updated.name == "A2"
        with pytest.raises(AccountError, match="already exists"):
            update_account(db_connection, WS, a.id, "B")
        # Keeping your own name is fine
        update_account(db_connection, WS, a.id, "A2")

    def test_update_cannot_use_self_as_input(self, db_connection):
        a = create_account(db_connection, WS, "A", RecordType.LIABILITY)
        with pytest.raises(AccountError, match="its own input"):
            update_account(db_connection, WS, a.id, "A", RATE, [a.id])

    def test_an_input_cannot_be_made_computed(self, db_connection):
        schwab = create_account(db_connection, WS, "Schwab", RecordType.ASSET)
        other = create_account(db_connection, WS, "Other", RecordType.ASSET)
        create_account(
            db_connection, WS, "Tax", RecordType.LIABILITY, RATE, [schwab.id]
        )
        with pytest.raises(AccountError, match="is an input to Tax"):
            update_account(db_connection, WS, schwab.id, "Schwab", RATE, [other.id])

    def test_update_can_add_formula_to_plain_account(self, db_connection):
        schwab = create_account(db_connection, WS, "Schwab", RecordType.ASSET)
        tax = create_account(db_connection, WS, "Tax", RecordType.LIABILITY)
        updated = update_account(db_connection, WS, tax.id, "Tax", RATE, [schwab.id])
        assert updated.formula == RATE
        assert updated.input_ids == [schwab.id]
        loaded = get_account(db_connection, WS, tax.id)
        assert loaded is not None and loaded.input_ids == [schwab.id]


@pytest.mark.db
class TestRetire:
    def test_retire_allowed_when_latest_amount_is_nonzero_with_warning(
        self, db_connection
    ):
        a = create_account(db_connection, WS, "A", RecordType.ASSET)
        upsert_amounts(db_connection, WS, date(2026, 1, 1), {a.id: Decimal("5")})
        db_connection.commit()
        assert retire_blocker(db_connection, WS, a) is None
        warning = retire_warning(db_connection, WS, a)
        assert warning is not None
        assert "$5.00" in warning
        assert "January 1, 2026" in warning
        assert "stops counting" in warning
        assert retire_account(db_connection, WS, a.id, TODAY).retired_at == TODAY

    def test_retire_warning_absent_at_zero_or_never_snapshotted(self, db_connection):
        never = create_account(db_connection, WS, "Never", RecordType.ASSET)
        zero = create_account(db_connection, WS, "Zero", RecordType.ASSET)
        upsert_amounts(db_connection, WS, date(2026, 1, 1), {zero.id: Decimal("0")})
        db_connection.commit()
        assert retire_warning(db_connection, WS, never) is None
        assert retire_warning(db_connection, WS, zero) is None

    def test_retire_warning_formats_a_negative_amount_without_a_double_sign(
        self, db_connection
    ):
        a = create_account(db_connection, WS, "A", RecordType.LIABILITY)
        upsert_amounts(db_connection, WS, date(2026, 1, 1), {a.id: Decimal("-17.44")})
        db_connection.commit()
        warning = retire_warning(db_connection, WS, a)
        assert warning is not None
        assert "-$17.44" in warning
        assert "$-17.44" not in warning

    def test_retire_blocked_when_it_feeds_a_formula(self, db_connection):
        schwab = create_account(db_connection, WS, "Schwab", RecordType.ASSET)
        create_account(
            db_connection, WS, "Tax", RecordType.LIABILITY, RATE, [schwab.id]
        )
        with pytest.raises(AccountError, match="is an input to Tax"):
            retire_account(db_connection, WS, schwab.id, TODAY)

    def test_retire_allowed_at_zero_or_never_snapshotted(self, db_connection):
        never = create_account(db_connection, WS, "Never", RecordType.ASSET)
        zero = create_account(db_connection, WS, "Zero", RecordType.ASSET)
        upsert_amounts(db_connection, WS, date(2026, 1, 1), {zero.id: Decimal("0")})
        db_connection.commit()
        assert retire_blocker(db_connection, WS, never) is None
        assert retire_account(db_connection, WS, never.id, TODAY).retired_at == TODAY
        assert retire_account(db_connection, WS, zero.id, TODAY).retired_at == TODAY
        loaded = get_account(db_connection, WS, zero.id)
        assert loaded is not None and loaded.retired_at == TODAY

    def test_retire_twice_and_unretire(self, db_connection):
        a = create_account(db_connection, WS, "A", RecordType.ASSET)
        retire_account(db_connection, WS, a.id, TODAY)
        with pytest.raises(AccountError, match="already retired"):
            retire_account(db_connection, WS, a.id, TODAY)
        assert unretire_account(db_connection, WS, a.id).retired_at is None
        with pytest.raises(AccountError, match="is not retired"):
            unretire_account(db_connection, WS, a.id)

    def test_unretire_rechecks_inputs_of_a_computed_account(self, db_connection):
        schwab = create_account(db_connection, WS, "Schwab", RecordType.ASSET)
        tax = create_account(
            db_connection, WS, "Tax", RecordType.LIABILITY, RATE, [schwab.id]
        )
        # Tax was never snapshotted, so retiring it is allowed.
        retire_account(db_connection, WS, tax.id, TODAY)
        # Schwab has no active dependents now (Tax is retired), so it too
        # can be retired.
        retire_account(db_connection, WS, schwab.id, TODAY)

        with pytest.raises(AccountError, match="Cannot unretire Tax") as exc_info:
            unretire_account(db_connection, WS, tax.id)
        assert "is retired" in str(exc_info.value)

        unretire_account(db_connection, WS, schwab.id)
        assert unretire_account(db_connection, WS, tax.id).retired_at is None


@pytest.mark.db
class TestSaveSnapshot:
    def _setup(self, conn):
        schwab = create_account(conn, WS, "Schwab", RecordType.ASSET)
        cash = create_account(conn, WS, "Cash", RecordType.ASSET)
        tax = create_account(
            conn,
            WS,
            "Tax",
            RecordType.LIABILITY,
            ProportionalFormula(rate=Decimal("0.15"), cost_basis=Decimal("100")),
            [schwab.id],
        )
        old = create_account(conn, WS, "Old", RecordType.ASSET)
        retire_account(conn, WS, old.id, date(2026, 1, 1))
        return schwab, cash, tax, old

    def test_writes_every_active_account_and_updates_basis(self, db_connection):
        schwab, cash, tax, old = self._setup(db_connection)
        count = save_snapshot(
            db_connection,
            WS,
            {schwab.id: Decimal("1000"), cash.id: Decimal("50")},
            {tax.id: Decimal("400")},
            TODAY,
        )
        assert count == 3
        rows = {(r.description, r.amount) for r in get_all_records(db_connection, WS)}
        assert rows == {
            ("Schwab", Decimal("1000.00")),
            ("Cash", Decimal("50.00")),
            ("Tax", Decimal("90.00")),
        }
        loaded = get_account(db_connection, WS, tax.id)
        assert loaded is not None and loaded.formula is not None
        assert loaded.formula.cost_basis == Decimal("400.00")

    def test_commits_even_when_a_transaction_was_already_open(
        self, db_connection, db_url
    ):
        """`conn.transaction()` only COMMITs when the connection was idle on
        entry; on a connection with an already-open transaction (the normal
        state after any prior statement) it uses a savepoint instead, which
        does nothing durable on its own. save_snapshot must commit either way.
        """
        schwab, cash, tax, _ = self._setup(db_connection)
        # A plain SELECT opens a transaction on the primary connection, same
        # as any normal prior query would.
        with db_connection.cursor() as cur:
            cur.execute("SELECT 1")

        save_snapshot(
            db_connection,
            WS,
            {schwab.id: Decimal("1000"), cash.id: Decimal("50")},
            {},
            TODAY,
        )

        second_conn = psycopg.connect(db_url)
        try:
            rows = {(r.description, r.amount) for r in get_all_records(second_conn, WS)}
        finally:
            second_conn.close()
        assert rows == {
            ("Schwab", Decimal("1000.00")),
            ("Cash", Decimal("50.00")),
            ("Tax", Decimal("135.00")),
        }

    def test_same_day_save_replaces(self, db_connection):
        schwab, cash, tax, _ = self._setup(db_connection)
        save_snapshot(
            db_connection,
            WS,
            {schwab.id: Decimal("1000"), cash.id: Decimal("50")},
            {},
            TODAY,
        )
        save_snapshot(
            db_connection,
            WS,
            {schwab.id: Decimal("2000"), cash.id: Decimal("50")},
            {},
            TODAY,
        )
        rows = {(r.description, r.amount) for r in get_all_records(db_connection, WS)}
        assert rows == {
            ("Schwab", Decimal("2000.00")),
            ("Cash", Decimal("50.00")),
            ("Tax", Decimal("285.00")),
        }

    def test_carry_forward_fills_omitted_accounts_from_latest_snapshot(
        self, db_connection
    ):
        schwab, cash, tax, _ = self._setup(db_connection)
        upsert_amounts(
            db_connection,
            WS,
            date(2026, 9, 1),
            {
                schwab.id: Decimal("1000"),
                cash.id: Decimal("50"),
                tax.id: Decimal("135"),
            },
        )
        count = save_snapshot(
            db_connection,
            WS,
            {schwab.id: Decimal("2000")},
            {},
            TODAY,
            carry_forward=True,
        )
        assert count == 3
        rows = {
            (r.description, r.amount)
            for r in get_all_records(db_connection, WS)
            if r.date == TODAY
        }
        # Tax is re-evaluated from the new Schwab value, not carried.
        assert rows == {
            ("Schwab", Decimal("2000.00")),
            ("Cash", Decimal("50.00")),
            ("Tax", Decimal("285.00")),
        }

    def test_carry_forward_still_needs_accounts_missing_from_latest(
        self, db_connection
    ):
        schwab, cash, _, _ = self._setup(db_connection)
        upsert_amounts(
            db_connection, WS, date(2026, 9, 1), {schwab.id: Decimal("1000")}
        )
        with pytest.raises(AccountError, match="Missing value for Cash"):
            save_snapshot(db_connection, WS, {}, {}, TODAY, carry_forward=True)
        assert [r.date for r in get_all_records(db_connection, WS)] == [
            date(2026, 9, 1)
        ]

    def _today_rows(self, conn) -> dict[str, Decimal]:
        return {
            r.description: r.amount
            for r in get_all_records(conn, WS)
            if r.date == TODAY
        }

    def test_carry_forward_twice_in_one_day_keeps_the_first_update(self, db_connection):
        """The second partial save carries from today's rows, not yesterday's."""
        schwab, cash, tax, _ = self._setup(db_connection)
        upsert_amounts(
            db_connection,
            WS,
            date(2026, 9, 1),
            {
                schwab.id: Decimal("1000"),
                cash.id: Decimal("50"),
                tax.id: Decimal("135"),
            },
        )
        save_snapshot(
            db_connection,
            WS,
            {schwab.id: Decimal("2000")},
            {},
            TODAY,
            carry_forward=True,
        )
        save_snapshot(
            db_connection, WS, {cash.id: Decimal("75")}, {}, TODAY, carry_forward=True
        )
        assert self._today_rows(db_connection) == {
            "Schwab": Decimal("2000.00"),
            "Cash": Decimal("75.00"),
            "Tax": Decimal("285.00"),
        }

    def test_carry_forward_recomputes_from_carried_inputs_and_new_basis(
        self, db_connection
    ):
        schwab, cash, tax, _ = self._setup(db_connection)
        upsert_amounts(
            db_connection,
            WS,
            date(2026, 9, 1),
            {
                schwab.id: Decimal("1000"),
                cash.id: Decimal("50"),
                tax.id: Decimal("135"),
            },
        )
        save_snapshot(
            db_connection,
            WS,
            {cash.id: Decimal("60")},
            {tax.id: Decimal("400")},
            TODAY,
            carry_forward=True,
        )
        assert self._today_rows(db_connection) == {
            "Schwab": Decimal("1000.00"),
            "Cash": Decimal("60.00"),
            "Tax": Decimal("90.00"),
        }

    def test_carry_forward_does_not_revive_a_retired_account(self, db_connection):
        schwab, cash, tax, old = self._setup(db_connection)
        # Old has a row on the latest date, then is retired after it.
        upsert_amounts(
            db_connection,
            WS,
            date(2026, 9, 1),
            {schwab.id: Decimal("1000"), cash.id: Decimal("50"), old.id: Decimal("7")},
        )
        count = save_snapshot(db_connection, WS, {}, {}, TODAY, carry_forward=True)
        assert count == 3
        assert "Old" not in self._today_rows(db_connection)

    def test_carry_forward_ignores_a_stale_computed_amount(self, db_connection):
        """A computed account's latest row is never carried, even if wrong."""
        schwab, cash, tax, _ = self._setup(db_connection)
        upsert_amounts(
            db_connection,
            WS,
            date(2026, 9, 1),
            {schwab.id: Decimal("1000"), cash.id: Decimal("50"), tax.id: Decimal("-1")},
        )
        save_snapshot(db_connection, WS, {}, {}, TODAY, carry_forward=True)
        assert self._today_rows(db_connection)["Tax"] == Decimal("135.00")

    def test_carry_forward_with_no_snapshots_needs_every_value(self, db_connection):
        schwab, cash, _, _ = self._setup(db_connection)
        with pytest.raises(AccountError, match="Missing value for Cash"):
            save_snapshot(
                db_connection,
                WS,
                {schwab.id: Decimal("1")},
                {},
                TODAY,
                carry_forward=True,
            )
        save_snapshot(
            db_connection,
            WS,
            {schwab.id: Decimal("1"), cash.id: Decimal("2")},
            {},
            TODAY,
            carry_forward=True,
        )
        assert set(self._today_rows(db_connection)) == {"Schwab", "Cash", "Tax"}

    def test_carry_forward_failure_writes_nothing_including_basis(self, db_connection):
        schwab, cash, tax, old = self._setup(db_connection)
        upsert_amounts(
            db_connection,
            WS,
            date(2026, 9, 1),
            {
                schwab.id: Decimal("1000"),
                cash.id: Decimal("50"),
                tax.id: Decimal("135"),
            },
        )
        before = get_all_records(db_connection, WS)
        with pytest.raises(AccountError, match="not an active account"):
            save_snapshot(
                db_connection,
                WS,
                {schwab.id: Decimal("5"), old.id: Decimal("1")},
                {tax.id: Decimal("999")},
                TODAY,
                carry_forward=True,
            )
        assert get_all_records(db_connection, WS) == before
        loaded = get_account(db_connection, WS, tax.id)
        assert loaded is not None and loaded.formula is not None
        assert loaded.formula.cost_basis == Decimal("100")

    @pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "sNaN"])
    def test_rejects_non_finite_amounts_and_bases(self, db_connection, bad):
        schwab, cash, tax, _ = self._setup(db_connection)
        base = {schwab.id: Decimal("1"), cash.id: Decimal("1")}
        with pytest.raises(AccountError, match="invalid amount"):
            save_snapshot(db_connection, WS, {**base, cash.id: Decimal(bad)}, {}, TODAY)
        with pytest.raises(AccountError, match="invalid cost basis"):
            save_snapshot(db_connection, WS, base, {tax.id: Decimal(bad)}, TODAY)
        assert get_all_records(db_connection, WS) == []

    def test_missing_value_writes_nothing_including_basis(self, db_connection):
        schwab, cash, tax, _ = self._setup(db_connection)
        with pytest.raises(AccountError, match="Missing value for Cash"):
            save_snapshot(
                db_connection,
                WS,
                {schwab.id: Decimal("1000")},
                {tax.id: Decimal("999")},
                TODAY,
            )
        assert get_all_records(db_connection, WS) == []
        loaded = get_account(db_connection, WS, tax.id)
        assert loaded is not None and loaded.formula is not None
        assert loaded.formula.cost_basis == Decimal("100")

    def test_rejects_a_value_too_large_to_store_and_writes_nothing(self, db_connection):
        schwab, cash, tax, _ = self._setup(db_connection)
        with pytest.raises(AccountError, match="too large"):
            save_snapshot(
                db_connection,
                WS,
                {schwab.id: Decimal("1e14"), cash.id: Decimal("50")},
                {},
                TODAY,
            )
        assert get_all_records(db_connection, WS) == []

    def test_rejects_retired_computed_and_unknown_ids(self, db_connection):
        schwab, cash, tax, old = self._setup(db_connection)
        base = {schwab.id: Decimal("1"), cash.id: Decimal("1")}
        with pytest.raises(AccountError, match="not an active account"):
            save_snapshot(db_connection, WS, {**base, old.id: Decimal("0")}, {}, TODAY)
        with pytest.raises(AccountError, match="is computed"):
            save_snapshot(db_connection, WS, {**base, tax.id: Decimal("0")}, {}, TODAY)
        # cash is active but plain: named, not "active" (it plainly is).
        with pytest.raises(AccountError, match="Cash is not a computed account"):
            save_snapshot(db_connection, WS, base, {cash.id: Decimal("0")}, TODAY)
        # old is retired, not merely absent: named, and still "not an active
        # computed account" since it isn't in the active set at all.
        with pytest.raises(AccountError, match="not an active computed account"):
            save_snapshot(db_connection, WS, base, {old.id: Decimal("0")}, TODAY)
        with pytest.raises(AccountError, match="not an active computed account"):
            save_snapshot(db_connection, WS, base, {9999: Decimal("0")}, TODAY)
        assert get_all_records(db_connection, WS) == []
