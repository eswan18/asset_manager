"""record_login: users are matched on identity's sub, and claimed once by email."""

import pytest

from sensibility.repository import get_user
from sensibility.users import record_login


def _preprovision(conn, email: str, *, is_admin: bool = False) -> int:
    row = conn.execute(
        "INSERT INTO users (email, name, is_admin) VALUES (%s, 'Pre', %s) RETURNING id",
        (email, is_admin),
    ).fetchone()
    conn.commit()
    assert row is not None
    return row[0]


@pytest.mark.db
class TestRecordLogin:
    def test_first_login_creates_a_user(self, db_connection):
        user = record_login(db_connection, "sub-new", "New@Example.com ", "New")
        assert (user.idp_sub, user.email, user.name) == (
            "sub-new",
            "new@example.com",
            "New",
        )
        assert user.is_admin is False
        assert user.last_login_at is not None

    def test_later_logins_match_on_sub_and_refresh_email_and_name(self, db_connection):
        first = record_login(db_connection, "sub-a", "a@example.com", "A")
        again = record_login(db_connection, "sub-a", "a2@example.com", "A Two")
        assert again.id == first.id
        assert (again.email, again.name) == ("a2@example.com", "A Two")

    def test_a_preprovisioned_row_is_claimed_and_keeps_admin(self, db_connection):
        user_id = _preprovision(db_connection, "boss@example.com", is_admin=True)
        user = record_login(db_connection, "sub-boss", "Boss@example.com", "Boss")
        assert user.id == user_id
        assert (user.idp_sub, user.is_admin, user.name) == ("sub-boss", True, "Boss")

    def test_a_claimed_row_cannot_be_claimed_again_by_another_sub(self, db_connection):
        user_id = _preprovision(db_connection, "boss@example.com", is_admin=True)
        record_login(db_connection, "sub-boss", "boss@example.com", "Boss")

        # Someone else at identity later presents the same email (say, after
        # the real owner changed theirs). They get their own row, not admin.
        other = record_login(db_connection, "sub-other", "boss@example.com", "Other")

        assert other.id != user_id
        assert other.is_admin is False
        boss = get_user(db_connection, user_id)
        assert boss is not None and boss.idp_sub == "sub-boss"

    def test_matching_on_sub_wins_over_a_preprovisioned_email(self, db_connection):
        existing = record_login(db_connection, "sub-a", "a@example.com", "A")
        provisioned = _preprovision(db_connection, "a2@example.com", is_admin=True)

        again = record_login(db_connection, "sub-a", "a2@example.com", "A")

        assert again.id == existing.id and again.is_admin is False
        row = get_user(db_connection, provisioned)
        assert row is not None and row.idp_sub is None
