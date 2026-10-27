"""Workspace settings (board V): the name, the people, leaving and deleting.

Owners get the whole page. Editors and viewers get it read-only (members and
their roles, no pending invites, which the API lists to owners only) plus
Leave. Every write goes through `workspaces.py` / `invites.py` with the same
access as the JSON API's routes, posts, and redirects back here (or to `/`
after leaving or deleting). A refusal re-renders the page with a 400 and the
service's message beside the control that caused it.

Removing someone, revoking an invite, leaving and deleting ask first, in the
page: `?confirm=member-{user_id}`, `invite-{invite_id}`, `leave` or `delete`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from psycopg import Connection

from asset_manager import repository as repo
from asset_manager.clock import local_date
from asset_manager.db import get_connection_context
from asset_manager.invites import (
    INVITE_TTL,
    InviteError,
    InviteNotFound,
    create_invite,
    revoke_invite,
    sender_is_owner,
)
from asset_manager.models import Member, Role
from asset_manager.workspaces import (
    WorkspaceError,
    change_role,
    delete_workspace,
    is_last_owner,
    remove_member,
    update_workspace,
)

from .access import (
    OwnerAccess,
    ViewerAccess,
    WorkspaceAccess,
    check_can_remove,
    page_prefix,
    shell_context,
)
from .rendering import render, set_flash
from .viewer_zone import zone_of

router = APIRouter(prefix="/workspaces/{workspace_id}")

ROLES = [Role.OWNER, Role.EDITOR, Role.VIEWER]


# --- view helpers ----------------------------------------------------------


def a_role(role: Role) -> str:
    """ "an owner", "an editor", "a viewer"."""
    return ("an " if role.value[0] in "aeiou" else "a ") + role.value


def day_text(instant: datetime, zone: str) -> str:
    """ "Oct 20": the day `instant` falls on in the viewer's zone."""
    day = local_date(instant, zone)
    return f"{day:%b} {day.day}"


def display_name(member: Member) -> str:
    return member.name or member.email


def _settings_url(access: WorkspaceAccess) -> str:
    return f"{page_prefix(access.workspace.id)}/settings"


def settings_view(
    conn: Connection, access: WorkspaceAccess, zone: str, confirm: str = ""
) -> dict[str, Any]:
    """Everything the page shows. Owners also get the pending invites; a
    `confirm` the viewer could not act on is ignored."""
    me = access.user["id"]
    is_owner = access.role == Role.OWNER
    members = repo.get_members(conn, access.workspace.id)
    by_id = {m.user_id: m for m in members}
    can_leave = me in by_id and not is_last_owner(by_id[me], members)

    people: list[dict[str, Any]] = []
    for m in members:
        you = m.user_id == me
        removable = (is_owner or you) and (can_leave or not you)
        people.append(
            {
                "kind": "member",
                "id": m.user_id,
                "name": display_name(m),
                "email": m.email,
                "role": m.role.value,
                "you": you,
                "removable": removable,
                "remove_label": f"Leave {access.workspace.name}"
                if you
                else f"Remove {display_name(m)}",
                "confirming": removable and confirm == f"member-{m.user_id}",
            }
        )

    invites = (
        repo.get_pending_workspace_invites(conn, access.workspace.id)
        if is_owner
        else []
    )
    for invite in invites:
        sender = by_id.get(invite.invited_by)
        if invite.invited_by == me:
            sent_by = "you"
        elif sender is not None:
            sent_by = display_name(sender)
        else:
            sent_by = "a former member"
        sub = f"Sent by {sent_by} {day_text(invite.created_at, zone)} · "
        if sender_is_owner(conn, invite):
            sub += f"expires {day_text(invite.expires_at, zone)}"
        else:  # it cannot be accepted (and the sender is not you: you're an owner)
            sub += f"lapsed: {sent_by} is no longer an owner"
        people.append(
            {
                "kind": "invite",
                "id": invite.id,
                "name": invite.email,
                "sub": sub,
                "role": invite.role.value,
                "remove_label": f"Revoke the invite to {invite.email}",
                "confirming": confirm == f"invite-{invite.id}",
            }
        )

    count = len(members)
    return {
        "is_owner": is_owner,
        "your_role": a_role(access.role),
        "people": people,
        "member_count": f"{count} member{'' if count == 1 else 's'}",
        "invite_count": len(invites),
        "can_leave": can_leave,
        # The template shows these only where can_leave / is_owner allow.
        "confirm_leave": confirm == "leave",
        "confirm_delete": confirm == "delete",
        "delete_reach": "you, its only member"
        if count == 1
        else f"all {count} members",
        "invite_days": INVITE_TTL.days,
        "roles": [r.value for r in ROLES],
        "settings_url": _settings_url(access),
    }


def _render(
    request: Request,
    access: WorkspaceAccess,
    *,
    confirm: str = "",
    errors: dict[str, str] | None = None,
    name: str | None = None,
    invite: dict[str, str] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """The page. `name` and `invite` keep a refused form's input."""
    with get_connection_context() as conn:
        view = settings_view(conn, access, zone_of(request), confirm)
    return render(
        request,
        "settings.html",
        {
            # The settings path, not the request's: a refused POST renders
            # here too, and the picker must link to settings elsewhere.
            **shell_context(access, _settings_url(access)),
            **view,
            "active_tab": "settings",
            "errors": errors or {},
            "name_value": access.workspace.name if name is None else name,
            "invite_form": invite or {"email": "", "role": Role.EDITOR.value},
        },
        status_code=status_code,
    )


def _back(access: WorkspaceAccess) -> RedirectResponse:
    return RedirectResponse(_settings_url(access), status_code=303)


def _home() -> RedirectResponse:
    """After leaving or deleting: `/` finds your oldest remaining workspace,
    or the welcome page."""
    return RedirectResponse("/", status_code=303)


def _parse_role(text: str, error: type[ValueError]) -> Role:
    """The role a form chose; anything else raises the route's own error."""
    try:
        return Role(text)
    except ValueError:
        raise error("Choose a role: owner, editor or viewer.") from None


def _get_member(conn: Connection, access: WorkspaceAccess, user_id: int) -> Member:
    for member in repo.get_members(conn, access.workspace.id):
        if member.user_id == user_id:
            return member
    raise HTTPException(status_code=404, detail="Member not found")


# --- routes ----------------------------------------------------------------


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, access: ViewerAccess, confirm: str = ""):
    """Every member may look; only owners get the controls."""
    return _render(request, access, confirm=confirm)


@router.post("/settings")
async def rename_route(
    request: Request, access: OwnerAccess, name: Annotated[str, Form()] = ""
):
    try:
        with get_connection_context() as conn:
            workspace = update_workspace(conn, access.workspace, name=name)
    except WorkspaceError as e:
        return _render(
            request, access, errors={"general": str(e)}, name=name, status_code=400
        )
    set_flash(request, "success", f"Saved {workspace.name}.")
    return _back(access)


@router.post("/delete")
async def delete_route(request: Request, access: OwnerAccess):
    """Soft delete: gone for every member; the data is kept."""
    with get_connection_context() as conn:
        delete_workspace(conn, access.workspace.id)
    set_flash(request, "success", f"Deleted {access.workspace.name}.")
    return _home()


@router.post("/members/{user_id}")
async def change_role_route(
    request: Request,
    access: OwnerAccess,
    user_id: int,
    role: Annotated[str, Form()] = "",
):
    """Owners only. The last owner cannot be demoted."""
    with get_connection_context() as conn:
        member = _get_member(conn, access, user_id)
        try:
            new_role = _parse_role(role, WorkspaceError)
            change_role(conn, access.workspace.id, user_id, new_role)
        except WorkspaceError as e:
            return _render(request, access, errors={"people": str(e)}, status_code=400)
    if user_id == access.user["id"]:
        set_flash(request, "success", f"You're now {a_role(new_role)}.")
    else:
        name = display_name(member)
        set_flash(request, "success", f"{name} is now {a_role(new_role)}.")
    return _back(access)


@router.post("/members/{user_id}/remove")
async def remove_route(request: Request, access: ViewerAccess, user_id: int):
    """Owners remove anyone; anyone may remove themselves, which is leaving.
    The last owner cannot leave."""
    check_can_remove(access, user_id)
    leaving = user_id == access.user["id"]
    with get_connection_context() as conn:
        member = _get_member(conn, access, user_id)
        try:
            remove_member(conn, access.workspace.id, user_id)
        except WorkspaceError as e:
            section = "leave" if leaving else "people"
            return _render(request, access, errors={section: str(e)}, status_code=400)
    if leaving:
        set_flash(request, "success", f"You left {access.workspace.name}.")
        return _home()
    set_flash(request, "success", f"Removed {display_name(member)}.")
    return _back(access)


@router.post("/invites")
async def invite_route(
    request: Request,
    access: OwnerAccess,
    email: Annotated[str, Form()] = "",
    role: Annotated[str, Form()] = "",
):
    """No email is sent: the invitee sees it when they log in."""
    try:
        with get_connection_context() as conn:
            invite = create_invite(
                conn,
                access.workspace.id,
                access.user["id"],
                email,
                _parse_role(role, InviteError),
            )
    except InviteError as e:
        return _render(
            request,
            access,
            errors={"invite": str(e)},
            invite={"email": email, "role": role},
            status_code=400,
        )
    set_flash(request, "success", f"Invited {invite.email} as {a_role(invite.role)}.")
    return _back(access)


@router.post("/invites/{invite_id}/revoke")
async def revoke_route(request: Request, access: OwnerAccess, invite_id: int):
    try:
        with get_connection_context() as conn:
            invite = repo.get_invite(conn, invite_id)
            revoke_invite(conn, access.workspace.id, invite_id)
    except InviteNotFound:
        raise HTTPException(status_code=404, detail="Invite not found") from None
    except InviteError as e:
        return _render(request, access, errors={"people": str(e)}, status_code=400)
    assert invite is not None  # revoke_invite found it
    set_flash(request, "success", f"Revoked the invite to {invite.email}.")
    return _back(access)
