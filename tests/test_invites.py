"""Invite rules: who can be invited, and who can accept what."""

from datetime import timedelta

import psycopg
import pytest

from sensibility import repository as repo
from sensibility.invites import (
    INVITE_TTL,
    InviteError,
    InviteNotFound,
    accept_invite,
    create_invite,
    decline_invite,
    revoke_invite,
)
from sensibility.models import Role
from sensibility.workspaces import create_workspace, delete_workspace
from tests.support import USER_ID, WS

FRIEND = "friend@example.com"


def _add_user(conn, email: str) -> int:
    row = conn.execute(
        "INSERT INTO users (idp_sub, email) VALUES (%s, %s) RETURNING id",
        (f"sub-{email}", email),
    ).fetchone()
    conn.commit()
    assert row is not None
    return row[0]


def _expire(conn, invite_id: int) -> None:
    conn.execute(
        "UPDATE workspace_invites SET expires_at = now() - interval '1 second' WHERE id = %s",
        (invite_id,),
    )
    conn.commit()


def _roles(conn, workspace_id: int = WS) -> dict[int, Role]:
    return {m.user_id: m.role for m in repo.get_members(conn, workspace_id)}


@pytest.mark.db
class TestCreate:
    def test_stores_a_normalized_email_role_and_expiry(self, db_connection):
        invite = create_invite(
            db_connection, WS, USER_ID, "  Friend@Example.COM ", Role.EDITOR
        )
        assert (invite.email, invite.role, invite.invited_by) == (
            FRIEND,
            Role.EDITOR,
            USER_ID,
        )
        assert invite.expires_at - invite.created_at == pytest.approx(
            INVITE_TTL, abs=timedelta(seconds=5)
        )

    @pytest.mark.parametrize(
        "email", ["", "friend", "friend@", "@example.com", "a b@c.com", "a@b"]
    )
    def test_rejects_things_that_are_not_emails(self, db_connection, email):
        with pytest.raises(InviteError, match="not an email"):
            create_invite(db_connection, WS, USER_ID, email, Role.VIEWER)

    def test_rejects_an_existing_member(self, db_connection):
        with pytest.raises(InviteError, match="already a member"):
            create_invite(db_connection, WS, USER_ID, "ME@example.com", Role.VIEWER)

    def test_rejects_a_second_pending_invite(self, db_connection):
        create_invite(db_connection, WS, USER_ID, FRIEND, Role.VIEWER)
        with pytest.raises(InviteError, match="already has a pending invite"):
            create_invite(db_connection, WS, USER_ID, FRIEND, Role.EDITOR)

    def test_an_expired_invite_is_replaced(self, db_connection):
        old = create_invite(db_connection, WS, USER_ID, FRIEND, Role.VIEWER)
        _expire(db_connection, old.id)

        new = create_invite(db_connection, WS, USER_ID, FRIEND, Role.EDITOR)

        assert new.id != old.id
        stale = repo.get_invite(db_connection, old.id)
        assert stale is not None and stale.revoked_at is not None

    def test_the_database_allows_one_open_invite_per_email(self, db_connection):
        create_invite(db_connection, WS, USER_ID, FRIEND, Role.VIEWER)
        with pytest.raises(psycopg.errors.UniqueViolation):
            db_connection.execute(
                """
                INSERT INTO workspace_invites (workspace_id, email, role, invited_by, expires_at)
                VALUES (%s, %s, 'viewer', %s, now() + interval '1 day')
                """,
                (WS, FRIEND, USER_ID),
            )


@pytest.mark.db
class TestAccept:
    def test_joins_in_the_invited_role(self, db_connection):
        friend = _add_user(db_connection, FRIEND)
        invite = create_invite(db_connection, WS, USER_ID, FRIEND, Role.EDITOR)

        accept_invite(db_connection, friend, FRIEND, invite.id)

        assert _roles(db_connection) == {USER_ID: Role.OWNER, friend: Role.EDITOR}
        done = repo.get_invite(db_connection, invite.id)
        assert done is not None and done.accepted_at is not None

    def test_only_the_invited_email_can_accept(self, db_connection):
        _add_user(db_connection, FRIEND)
        other = _add_user(db_connection, "other@example.com")
        invite = create_invite(db_connection, WS, USER_ID, FRIEND, Role.OWNER)

        with pytest.raises(InviteNotFound):
            accept_invite(db_connection, other, "other@example.com", invite.id)
        with pytest.raises(InviteNotFound):
            decline_invite(db_connection, "other@example.com", invite.id)
        assert other not in _roles(db_connection)

    @pytest.mark.parametrize(
        "ending", ["expired", "revoked", "declined", "accepted", "deleted"]
    )
    def test_nothing_but_a_pending_invite_can_be_accepted(self, db_connection, ending):
        friend = _add_user(db_connection, FRIEND)
        invite = create_invite(db_connection, WS, USER_ID, FRIEND, Role.EDITOR)
        if ending == "expired":
            _expire(db_connection, invite.id)
        elif ending == "revoked":
            revoke_invite(db_connection, WS, invite.id)
        elif ending == "declined":
            decline_invite(db_connection, FRIEND, invite.id)
        elif ending == "accepted":
            accept_invite(db_connection, friend, FRIEND, invite.id)
            repo.delete_member(db_connection, WS, friend)  # left again
            db_connection.commit()
        else:
            delete_workspace(db_connection, WS)

        with pytest.raises(InviteNotFound):
            accept_invite(db_connection, friend, FRIEND, invite.id)
        assert friend not in _roles(db_connection)

    def test_an_existing_member_cannot_accept_again(self, db_connection):
        friend = _add_user(db_connection, FRIEND)
        invite = create_invite(db_connection, WS, USER_ID, FRIEND, Role.OWNER)
        repo.add_member(db_connection, WS, friend, Role.VIEWER)
        db_connection.commit()

        with pytest.raises(InviteError, match="already a member"):
            accept_invite(db_connection, friend, FRIEND, invite.id)
        assert _roles(db_connection)[friend] == Role.VIEWER


@pytest.mark.db
class TestRevoke:
    def test_only_through_its_own_workspace(self, db_connection):
        create_workspace(db_connection, USER_ID, "Other")
        invite = create_invite(db_connection, WS, USER_ID, FRIEND, Role.VIEWER)

        with pytest.raises(InviteNotFound):
            revoke_invite(db_connection, 2, invite.id)

        revoke_invite(db_connection, WS, invite.id)
        with pytest.raises(InviteError, match="already been resolved"):
            revoke_invite(db_connection, WS, invite.id)


@pytest.mark.db
class TestSenderMustStillBeOwner:
    @pytest.mark.parametrize("change", ["demoted", "removed"])
    def test_an_ex_owners_invites_cannot_be_accepted(self, db_connection, change):
        from sensibility.workspaces import change_role, remove_member

        co_owner = _add_user(db_connection, "co@example.com")
        repo.add_member(db_connection, WS, co_owner, Role.OWNER)
        db_connection.commit()
        friend = _add_user(db_connection, FRIEND)
        invite = create_invite(db_connection, WS, co_owner, FRIEND, Role.OWNER)

        if change == "demoted":
            change_role(db_connection, WS, co_owner, Role.EDITOR)
        else:
            remove_member(db_connection, WS, co_owner)

        with pytest.raises(InviteNotFound):
            accept_invite(db_connection, friend, FRIEND, invite.id)
        assert friend not in _roles(db_connection)

    def test_a_current_owners_invite_still_works(self, db_connection):
        co_owner = _add_user(db_connection, "co@example.com")
        repo.add_member(db_connection, WS, co_owner, Role.OWNER)
        db_connection.commit()
        friend = _add_user(db_connection, FRIEND)
        invite = create_invite(db_connection, WS, co_owner, FRIEND, Role.VIEWER)

        accept_invite(db_connection, friend, FRIEND, invite.id)

        assert _roles(db_connection)[friend] == Role.VIEWER


@pytest.mark.db
def test_an_accept_racing_a_revoke_fails_cleanly(db_connection, db_url):
    """While a revoke holds the invite, an accept waits, then sees it revoked
    and reports not-found, rather than tripping a constraint mid-write."""
    import threading
    import time

    friend = _add_user(db_connection, FRIEND)
    invite = create_invite(db_connection, WS, USER_ID, FRIEND, Role.EDITOR)
    revoker = psycopg.connect(db_url)
    accepter = psycopg.connect(db_url)
    outcome: list[BaseException | None] = []
    try:
        with revoker.transaction():
            repo.get_invite(revoker, invite.id, for_update=True)

            def accept() -> None:
                try:
                    accept_invite(accepter, friend, FRIEND, invite.id)
                    outcome.append(None)
                except BaseException as e:
                    outcome.append(e)

            racer = threading.Thread(target=accept)
            racer.start()
            time.sleep(0.3)
            assert racer.is_alive(), "the accept should wait for the revoke"
            repo.set_invite_revoked(revoker, invite.id)
        racer.join(timeout=5)
    finally:
        revoker.close()
        accepter.close()

    assert len(outcome) == 1 and isinstance(outcome[0], InviteNotFound)
    assert friend not in _roles(db_connection)
