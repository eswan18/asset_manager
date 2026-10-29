"""JSON for the settings page, the welcome page and the shell's invite strip.

The writes these pages make already exist in `api_routes` (rename, delete,
roles, remove/leave, invite, revoke, create, accept, decline). What is here
is what the pages read that the older endpoints did not say: who may leave
(the last-owner rule), whose row can be removed, which pending invites have
lapsed, and who sent each invite. `settings_model.settings_facts` is shared
with the Jinja settings page, so the rules can't drift.

Times are ISO 8601 instants; the browser shows them as days in its own zone.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from sensibility import repository as repo
from sensibility.db import get_connection_context
from sensibility.invites import INVITE_TTL, acceptable_invites
from sensibility.models import Role

from .access import ViewerAccess
from .auth import CurrentUser
from .settings_model import display_name, settings_facts

router = APIRouter(prefix="/api")

# The order the role choices are offered in.
ROLES = [Role.OWNER, Role.EDITOR, Role.VIEWER]


# --- workspace settings --------------------------------------------------------


class SettingsMemberOut(BaseModel):
    user_id: int
    name: str | None
    email: str
    display_name: str = Field(description="The name, or the email without one")
    role: Role
    joined_at: str
    you: bool
    removable: bool = Field(
        description="You may remove this member (on your own row: leave). "
        "Owners remove anyone; anyone removes themselves, except the last owner"
    )


class SettingsInviteOut(BaseModel):
    id: int
    email: str
    role: Role
    invited_by: int
    sent_by_you: bool
    sender_name: str | None = Field(
        description="The sender's display name; None once they are no longer "
        'a member (the page says "a former member")'
    )
    created_at: str
    expires_at: str
    lapsed: bool = Field(
        description="The sender is no longer an owner, so it cannot be accepted"
    )


class WorkspaceSettingsOut(BaseModel):
    id: int
    name: str
    role: Role = Field(description="Your role here")
    is_owner: bool = Field(
        description="You may rename, delete, invite, revoke, change roles and "
        "remove others"
    )
    can_leave: bool = Field(description="False only for the last owner")
    members: list[SettingsMemberOut] = Field(description="Oldest first")
    invites: list[SettingsInviteOut] = Field(
        description="Pending, oldest first. Owners only: empty for others"
    )
    invite_ttl_days: int
    roles: list[Role] = Field(description="The role choices, in order")


@router.get("/workspaces/{workspace_id}/settings")
async def workspace_settings(access: ViewerAccess) -> WorkspaceSettingsOut:
    """Everything the settings page shows. Every member may read it; only
    owners get the pending invites."""
    with get_connection_context() as conn:
        facts = settings_facts(conn, access)
    return WorkspaceSettingsOut(
        id=access.workspace.id,
        name=access.workspace.name,
        role=access.role,
        is_owner=facts.is_owner,
        can_leave=facts.can_leave,
        members=[
            SettingsMemberOut(
                user_id=row.member.user_id,
                name=row.member.name,
                email=row.member.email,
                display_name=display_name(row.member),
                role=row.member.role,
                joined_at=row.member.joined_at.isoformat(),
                you=row.you,
                removable=row.removable,
            )
            for row in facts.members
        ],
        invites=[
            SettingsInviteOut(
                id=found.invite.id,
                email=found.invite.email,
                role=found.invite.role,
                invited_by=found.invite.invited_by,
                sent_by_you=found.by_you,
                sender_name=display_name(found.sender) if found.sender else None,
                created_at=found.invite.created_at.isoformat(),
                expires_at=found.invite.expires_at.isoformat(),
                lapsed=found.lapsed,
            )
            for found in facts.invites
        ],
        invite_ttl_days=INVITE_TTL.days,
        roles=ROLES,
    )


# --- your invites ----------------------------------------------------------------


class MyInviteOut(BaseModel):
    id: int
    workspace_id: int
    workspace_name: str
    email: str
    role: Role
    invited_by: int
    sender_name: str = Field(description="The sender's name, or their email")
    created_at: str
    expires_at: str
    acceptable: bool = Field(
        description="You can accept it now. False when it has lapsed (its "
        "sender is no longer an owner); the welcome page and the invite strip "
        "show only acceptable invites"
    )


class MyInvitesOut(BaseModel):
    invites: list[MyInviteOut] = Field(
        description="Oldest first (the invite strip shows newest first)"
    )


@router.get("/invites")
async def my_invites(user: CurrentUser) -> MyInvitesOut:
    """Pending invites addressed to your email."""
    with get_connection_context() as conn:
        found = repo.get_pending_invites_for_email(conn, user["email"])
        senders = {
            a.invite.id: a.sender for a in acceptable_invites(conn, user["email"])
        }
        invites = []
        for invite, workspace in found:
            sender = senders.get(invite.id)
            if sender is None:  # lapsed: look the sender up
                sent_by = repo.get_user(conn, invite.invited_by)
                sender = (sent_by.name or sent_by.email) if sent_by else ""
            invites.append(
                MyInviteOut(
                    id=invite.id,
                    workspace_id=invite.workspace_id,
                    workspace_name=workspace.name,
                    email=invite.email,
                    role=invite.role,
                    invited_by=invite.invited_by,
                    sender_name=sender,
                    created_at=invite.created_at.isoformat(),
                    expires_at=invite.expires_at.isoformat(),
                    acceptable=invite.id in senders,
                )
            )
    return MyInvitesOut(invites=invites)
