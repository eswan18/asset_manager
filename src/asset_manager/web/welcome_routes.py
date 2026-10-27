"""The welcome page (board W): invites for you, and starting a workspace.

A user with no live workspace lands here (bare `/` and `/accounts` redirect
to it), and anyone reaches it from the user menu's "New workspace". The
writes are the JSON API's own, at their paths without `/api`: `POST
/workspaces` creates one, `POST /invites/{id}/accept|decline` answers an
invite. Only the invited (verified) email can answer; anyone else gets a
404, so invite ids reveal nothing.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from asset_manager import repository as repo
from asset_manager.db import get_connection_context
from asset_manager.invites import (
    InviteError,
    InviteNotFound,
    accept_invite,
    acceptable_invites,
    decline_invite,
)
from asset_manager.workspaces import WorkspaceError, create_workspace

from .access import page_prefix
from .auth import CurrentUser
from .rendering import render, set_flash
from .invite_strip import safe_next
from .viewer_zone import zone_of
from .wording import a_role, day_text

WELCOME_PATH = "/welcome"

router = APIRouter()


def first_name(user: dict[str, Any]) -> str:
    """ "Sam" from "Sam Lee"; the email's local part when there is no name."""
    name = (user.get("name") or "").strip()
    return name.split()[0] if name else user["email"].split("@")[0]


def _render(
    request: Request,
    user: dict[str, Any],
    *,
    errors: dict[str, str] | None = None,
    name: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    zone = zone_of(request)
    with get_connection_context() as conn:
        has_workspaces = bool(repo.get_memberships(conn, user["id"]))
        invites = []
        for invite, workspace, sender in acceptable_invites(conn, user["email"]):
            invites.append(
                {
                    "id": invite.id,
                    "workspace": workspace.name,
                    "line": f"{sender} invited you as {a_role(invite.role)} · "
                    f"expires {day_text(invite.expires_at, zone)}",
                }
            )
    return render(
        request,
        "welcome.html",
        {
            "user": user,
            "base": "",
            "first_name": first_name(user),
            "has_workspaces": has_workspaces,
            "invites": invites,
            "errors": errors or {},
            "name_value": name,
        },
        status_code=status_code,
    )


@router.get(WELCOME_PATH, response_class=HTMLResponse)
async def welcome_page(request: Request, user: CurrentUser):
    return _render(request, user)


@router.post("/workspaces")
async def create_workspace_route(
    request: Request, user: CurrentUser, name: Annotated[str, Form()] = ""
):
    """A new workspace with you as its owner; then into it."""
    try:
        with get_connection_context() as conn:
            workspace = create_workspace(conn, user["id"], name)
    except WorkspaceError as e:
        return _render(
            request, user, errors={"create": str(e)}, name=name, status_code=400
        )
    set_flash(request, "success", f"Created {workspace.name}.")
    return RedirectResponse(page_prefix(workspace.id), status_code=303)


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Invite not found")


@router.post("/invites/{invite_id}/accept")
async def accept_route(request: Request, user: CurrentUser, invite_id: int):
    """Join in the invited role, then go to its dashboard."""
    try:
        with get_connection_context() as conn:
            invite = accept_invite(conn, user["id"], user["email"], invite_id)
            workspace = repo.get_workspace(conn, invite.workspace_id)
    except InviteNotFound:
        raise _not_found() from None
    except InviteError as e:
        return _render(request, user, errors={"invites": str(e)}, status_code=400)
    name = workspace.name if workspace else "the workspace"
    set_flash(request, "success", f"Joined {name} as {a_role(invite.role)}.")
    return RedirectResponse(page_prefix(invite.workspace_id), status_code=303)


@router.post("/invites/{invite_id}/decline")
async def decline_route(
    request: Request,
    user: CurrentUser,
    invite_id: int,
    next: Annotated[str, Form()] = "",
):
    """Back to `next` (the invite strip's page) if it is a path on this
    site, else here."""
    try:
        with get_connection_context() as conn:
            decline_invite(conn, user["email"], invite_id)
            invite = repo.get_invite(conn, invite_id)
            workspace = (
                repo.get_workspace(conn, invite.workspace_id) if invite else None
            )
    except InviteNotFound:
        raise _not_found() from None
    name = workspace.name if workspace else "the workspace"
    set_flash(request, "success", f"Declined the invite to {name}.")
    return RedirectResponse(safe_next(next) or WELCOME_PATH, status_code=303)
