"""Workspace invites: owners offer a role to an email; its holder accepts.

An invite is matched only against a user's email as recorded at login,
which identity has verified. It never gets anyone past ALLOWED_EMAILS: the
invitee has to be able to log in already. Functions commit on success.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from psycopg import Connection

from . import repository as repo
from .models import Invite, Role

INVITE_TTL = timedelta(days=14)

# Deliberately loose: identity is the real check, at login. This only
# catches obvious typos before an invite sits unclaimable for two weeks.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class InviteError(ValueError):
    """A rule violation with a user-facing message."""


class InviteNotFound(LookupError):
    """No such invite for this caller. Also used when the invite exists but
    is someone else's, so ids reveal nothing."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_email(email: str) -> str:
    cleaned = email.strip().lower()
    if not _EMAIL.match(cleaned):
        raise InviteError(f"{email.strip()!r} is not an email address")
    return cleaned


def create_invite(
    conn: Connection, workspace_id: int, invited_by: int, email: str, role: Role
) -> Invite:
    email = _clean_email(email)
    with conn.transaction():
        if repo.is_member_email(conn, workspace_id, email):
            raise InviteError(f"{email} is already a member of this workspace")
        existing = repo.get_open_invite(conn, workspace_id, email)
        if existing is not None:
            if existing.is_pending(_now()):
                raise InviteError(
                    f"{email} already has a pending invite. Revoke it to change the role."
                )
            repo.set_invite_revoked(conn, existing.id)  # expired: make way
        invite = repo.insert_invite(
            conn, workspace_id, email, role, invited_by, _now() + INVITE_TTL
        )
    conn.commit()
    return invite


def revoke_invite(conn: Connection, workspace_id: int, invite_id: int) -> None:
    """Withdraw an open invite to this workspace (pending or expired)."""
    with conn.transaction():
        invite = repo.get_invite(conn, invite_id, for_update=True)
        if invite is None or invite.workspace_id != workspace_id:
            raise InviteNotFound()
        if not invite.is_open:
            raise InviteError("This invite has already been resolved")
        repo.set_invite_revoked(conn, invite_id)
    conn.commit()


def _pending_for(conn: Connection, email: str, invite_id: int) -> Invite:
    """The invite, locked, if it is pending and addressed to this email."""
    invite = repo.get_invite(conn, invite_id, for_update=True)
    if invite is None or invite.email != email or not invite.is_pending(_now()):
        raise InviteNotFound()
    workspace = repo.get_workspace(conn, invite.workspace_id)
    if workspace is None or workspace.deleted_at is not None:
        raise InviteNotFound()
    # An invite speaks for its sender, so it lapses when they stop being an
    # owner: a removed or demoted owner's invites must not let anyone in.
    sender = repo.get_access(conn, invite.workspace_id, invite.invited_by)
    if sender is None or sender[1] != Role.OWNER:
        raise InviteNotFound()
    return invite


def accept_invite(conn: Connection, user_id: int, email: str, invite_id: int) -> Invite:
    """Join the workspace in the invited role. `email` must be the user's
    verified email as recorded at login."""
    with conn.transaction():
        invite = _pending_for(conn, email, invite_id)
        if repo.get_access(conn, invite.workspace_id, user_id) is not None:
            raise InviteError("You are already a member of this workspace")
        repo.add_member(conn, invite.workspace_id, user_id, invite.role)
        repo.set_invite_accepted(conn, invite.id, user_id)
    conn.commit()
    return invite


def decline_invite(conn: Connection, email: str, invite_id: int) -> None:
    with conn.transaction():
        invite = _pending_for(conn, email, invite_id)
        repo.set_invite_declined(conn, invite.id)
    conn.commit()
