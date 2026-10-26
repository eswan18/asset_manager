"""Workspace rules: names, soft delete, and the last-owner rule."""

import threading
import time

import psycopg
import pytest

from asset_manager import repository as repo
from asset_manager.models import Role
from asset_manager.workspaces import (
    WorkspaceError,
    change_role,
    create_workspace,
    delete_workspace,
    remove_member,
    update_workspace,
)
from tests.support import USER_ID, WS


def _add_user(conn, sub: str, role: Role | None = None, workspace_id: int = WS) -> int:
    row = conn.execute(
        "INSERT INTO users (idp_sub, email) VALUES (%s, %s) RETURNING id",
        (sub, f"{sub}@example.com"),
    ).fetchone()
    assert row is not None
    if role is not None:
        repo.add_member(conn, workspace_id, row[0], role)
    conn.commit()
    return row[0]


def _roles(conn, workspace_id: int = WS) -> dict[int, Role]:
    return {m.user_id: m.role for m in repo.get_members(conn, workspace_id)}


@pytest.mark.db
class TestCreateAndUpdate:
    def test_creator_is_the_only_member_and_an_owner(self, db_connection):
        ws = create_workspace(db_connection, USER_ID, "  Joint   Finances ")
        assert ws.name == "Joint Finances"
        assert _roles(db_connection, ws.id) == {USER_ID: Role.OWNER}

    def test_blank_names_are_rejected(self, db_connection):
        with pytest.raises(WorkspaceError, match="Name is required"):
            create_workspace(db_connection, USER_ID, "   ")
        ws = repo.get_workspace(db_connection, WS)
        assert ws is not None
        with pytest.raises(WorkspaceError, match="Name is required"):
            update_workspace(db_connection, ws, name=" ")

    def test_update_renames(self, db_connection):
        ws = repo.get_workspace(db_connection, WS)
        assert ws is not None
        update_workspace(db_connection, ws, name="  Joint  ")
        loaded = repo.get_workspace(db_connection, WS)
        assert loaded is not None and loaded.name == "Joint"

    def test_update_with_nothing_changes_nothing(self, db_connection):
        ws = repo.get_workspace(db_connection, WS)
        assert ws is not None
        update_workspace(db_connection, ws)
        assert repo.get_workspace(db_connection, WS) == ws


@pytest.mark.db
class TestSoftDelete:
    def test_deleted_workspace_is_gone_for_members_but_its_data_stays(
        self, db_connection
    ):
        from asset_manager.accounts import create_account
        from asset_manager.models import RecordType

        cash = create_account(db_connection, WS, "Cash", RecordType.ASSET)
        delete_workspace(db_connection, WS)

        assert repo.get_access(db_connection, WS, USER_ID) is None
        assert repo.get_memberships(db_connection, USER_ID) == []
        ws = repo.get_workspace(db_connection, WS)
        assert ws is not None and ws.deleted_at is not None
        assert repo.get_account(db_connection, WS, cash.id) is not None
        # The rows behind it are untouched, so a restore is one UPDATE.
        assert _roles(db_connection) == {USER_ID: Role.OWNER}


@pytest.mark.db
class TestLastOwner:
    def test_the_only_owner_cannot_be_demoted_or_removed(self, db_connection):
        for role in (Role.EDITOR, Role.VIEWER):
            with pytest.raises(WorkspaceError, match="at least one owner"):
                change_role(db_connection, WS, USER_ID, role)
        with pytest.raises(WorkspaceError, match="at least one owner"):
            remove_member(db_connection, WS, USER_ID)
        assert _roles(db_connection) == {USER_ID: Role.OWNER}

    def test_with_a_second_owner_the_first_can_step_down(self, db_connection):
        other = _add_user(db_connection, "other", Role.EDITOR)
        change_role(db_connection, WS, other, Role.OWNER)
        change_role(db_connection, WS, USER_ID, Role.VIEWER)
        assert _roles(db_connection) == {USER_ID: Role.VIEWER, other: Role.OWNER}
        with pytest.raises(WorkspaceError, match="at least one owner"):
            remove_member(db_connection, WS, other)

    def test_non_owners_can_be_changed_and_removed_freely(self, db_connection):
        other = _add_user(db_connection, "other", Role.VIEWER)
        change_role(db_connection, WS, other, Role.EDITOR)
        remove_member(db_connection, WS, other)
        assert _roles(db_connection) == {USER_ID: Role.OWNER}

    def test_changing_a_non_member_is_an_error(self, db_connection):
        stranger = _add_user(db_connection, "stranger")
        with pytest.raises(WorkspaceError, match="not a member"):
            change_role(db_connection, WS, stranger, Role.EDITOR)
        with pytest.raises(WorkspaceError, match="not a member"):
            remove_member(db_connection, WS, stranger)

    def test_concurrent_demotions_cannot_leave_no_owner(self, db_connection, db_url):
        """Two owners each demoting the other at once: one must fail."""
        other = _add_user(db_connection, "other", Role.OWNER)
        first = psycopg.connect(db_url)
        second = psycopg.connect(db_url)
        outcome: list[BaseException | None] = []
        try:
            with first.transaction():
                # The first demotion holds the membership lock...
                repo.get_members(first, WS, for_update=True)

                def demote_first_owner() -> None:
                    try:
                        change_role(second, WS, USER_ID, Role.EDITOR)
                        outcome.append(None)
                    except BaseException as e:
                        outcome.append(e)

                racer = threading.Thread(target=demote_first_owner)
                racer.start()
                time.sleep(0.3)
                assert racer.is_alive(), "the second change should wait for the lock"
                repo.set_member_role(first, WS, other, Role.EDITOR)
            # ...and commits; the second then sees one owner left and refuses.
            racer.join(timeout=5)
        finally:
            first.close()
            second.close()

        assert len(outcome) == 1 and isinstance(outcome[0], WorkspaceError)
        assert _roles(db_connection) == {USER_ID: Role.OWNER, other: Role.EDITOR}
