"""Workspace and membership rules.

Everything here raises WorkspaceError with a message that is safe to show
the user. Functions commit on success.
"""

from __future__ import annotations

from psycopg import Connection

from . import repository as repo
from .models import Member, Role, Workspace


class WorkspaceError(ValueError):
    """A rule violation with a user-facing message."""


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise WorkspaceError("Name is required")
    return cleaned


def create_workspace(conn: Connection, owner_id: int, name: str) -> Workspace:
    """A new workspace with `owner_id` as its only member, an owner."""
    workspace = repo.insert_workspace(conn, _clean_name(name))
    repo.add_member(conn, workspace.id, owner_id, Role.OWNER)
    conn.commit()
    return workspace


def update_workspace(
    conn: Connection,
    workspace: Workspace,
    *,
    name: str | None = None,
) -> Workspace:
    """Rename it."""
    updated = workspace.model_copy(
        update={"name": workspace.name if name is None else _clean_name(name)}
    )
    repo.update_workspace(conn, updated)
    conn.commit()
    return updated


def delete_workspace(conn: Connection, workspace_id: int) -> None:
    """Soft delete: hidden from everyone, data kept, restorable by hand."""
    repo.soft_delete_workspace(conn, workspace_id)
    conn.commit()


def _locked_member(
    conn: Connection, workspace_id: int, user_id: int
) -> tuple[Member, list[Member]]:
    members = repo.get_members(conn, workspace_id, for_update=True)
    for member in members:
        if member.user_id == user_id:
            return member, members
    raise WorkspaceError(f"User {user_id} is not a member of this workspace")


def _check_not_last_owner(member: Member, members: list[Member]) -> None:
    owners = [m for m in members if m.role == Role.OWNER]
    if member.role == Role.OWNER and len(owners) == 1:
        raise WorkspaceError(
            "A workspace needs at least one owner. Make someone else an owner first."
        )


def change_role(conn: Connection, workspace_id: int, user_id: int, role: Role) -> None:
    with conn.transaction():
        member, members = _locked_member(conn, workspace_id, user_id)
        if role != Role.OWNER:
            _check_not_last_owner(member, members)
        repo.set_member_role(conn, workspace_id, user_id, role)
    conn.commit()


def remove_member(conn: Connection, workspace_id: int, user_id: int) -> None:
    """Remove a member, including yourself (leaving)."""
    with conn.transaction():
        member, members = _locked_member(conn, workspace_id, user_id)
        _check_not_last_owner(member, members)
        repo.delete_member(conn, workspace_id, user_id)
    conn.commit()
