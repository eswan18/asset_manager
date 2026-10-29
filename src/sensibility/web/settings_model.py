"""What the settings page knows about a workspace's people, as data.

`api_settings` serves it as JSON for the React app's settings page: who may
leave (not the last owner), whose row can be removed, and which pending
invites have lapsed because their sender is no longer an owner.
"""

from __future__ import annotations

from dataclasses import dataclass

from psycopg import Connection

from sensibility import repository as repo
from sensibility.invites import sender_is_owner
from sensibility.models import Invite, Member, Role
from sensibility.workspaces import is_last_owner

from .access import WorkspaceAccess


def display_name(member: Member) -> str:
    return member.name or member.email


@dataclass(frozen=True)
class MemberFacts:
    member: Member
    you: bool
    # Owners may remove anyone and anyone may remove themselves (leave),
    # except the last owner, who cannot leave.
    removable: bool


@dataclass(frozen=True)
class InviteFacts:
    invite: Invite
    sender: Member | None  # None once the sender is no longer a member
    by_you: bool
    # Its sender is no longer an owner, so it cannot be accepted.
    lapsed: bool


@dataclass(frozen=True)
class SettingsFacts:
    is_owner: bool
    can_leave: bool
    members: list[MemberFacts]  # oldest first
    invites: list[InviteFacts]  # pending, oldest first; owners only (else empty)


def settings_facts(conn: Connection, access: WorkspaceAccess) -> SettingsFacts:
    me = access.user["id"]
    is_owner = access.role == Role.OWNER
    members = repo.get_members(conn, access.workspace.id)
    by_id = {m.user_id: m for m in members}
    can_leave = me in by_id and not is_last_owner(by_id[me], members)

    people = []
    for m in members:
        you = m.user_id == me
        people.append(
            MemberFacts(
                member=m,
                you=you,
                removable=(is_owner or you) and (can_leave or not you),
            )
        )

    invites = (
        repo.get_pending_workspace_invites(conn, access.workspace.id)
        if is_owner
        else []
    )
    return SettingsFacts(
        is_owner=is_owner,
        can_leave=can_leave,
        members=people,
        invites=[
            InviteFacts(
                invite=invite,
                sender=by_id.get(invite.invited_by),
                by_you=invite.invited_by == me,
                lapsed=not sender_is_owner(conn, invite),
            )
            for invite in invites
        ],
    )
