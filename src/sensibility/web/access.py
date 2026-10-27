"""Which workspace a request acts in, and whether the user's role allows it.

API routes and pages both name the workspace in the path (pages are the API
path without `/api`). A workspace the user is not a live member of is a 404,
so its existence is not revealed; a role too low for the route is a 403.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request

from sensibility import repository as repo
from sensibility.db import get_connection_context
from sensibility.models import Role, Workspace

from .auth import CurrentUser
from .invite_strip import strip_items
from .viewer_zone import zone_of


@dataclass(frozen=True)
class WorkspaceAccess:
    user: dict[str, Any]
    workspace: Workspace
    role: Role


def _check_role(role: Role, needed: Role) -> None:
    if not role.allows(needed):
        raise HTTPException(
            status_code=403, detail=f"This needs the {needed.value} role or higher"
        )


def _access(needed: Role):
    def dependency(workspace_id: int, user: CurrentUser) -> WorkspaceAccess:
        with get_connection_context() as conn:
            found = repo.get_access(conn, workspace_id, user["id"])
        if found is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
        workspace, role = found
        _check_role(role, needed)
        return WorkspaceAccess(user=user, workspace=workspace, role=role)

    return dependency


ViewerAccess = Annotated[WorkspaceAccess, Depends(_access(Role.VIEWER))]
EditorAccess = Annotated[WorkspaceAccess, Depends(_access(Role.EDITOR))]
OwnerAccess = Annotated[WorkspaceAccess, Depends(_access(Role.OWNER))]


def page_prefix(workspace_id: int) -> str:
    """Where a workspace's pages live: `/workspaces/1` + `/accounts`."""
    return f"/workspaces/{workspace_id}"


def check_can_remove(access: WorkspaceAccess, user_id: int) -> None:
    """Owners remove anyone; anyone may remove themselves (leave)."""
    if user_id != access.user["id"] and access.role != Role.OWNER:
        raise HTTPException(
            status_code=403, detail="Only owners can remove other members"
        )


def oldest_workspace_id(user: dict[str, Any]) -> int | None:
    """The workspace that bare paths (`/`, `/accounts`) redirect into; None
    when the user is in no live workspace (they go to the welcome page)."""
    with get_connection_context() as conn:
        memberships = repo.get_memberships(conn, user["id"])
    return memberships[0][0].id if memberships else None


def shell_context(
    request: Request, access: WorkspaceAccess, path: str | None = None
) -> dict[str, Any]:
    """What base.html needs on every page: the user, this workspace, the
    picker's other workspaces, each linking to the same section of the app
    (an account's edit page maps to the other workspace's Accounts page),
    and the invite strip.

    `path` is the page's own path when the request's is not (a drawer, or a
    refused POST that re-renders its page); it defaults to the request's.
    The strip's Decline returns to this page: the request itself on a GET,
    query included, else `path`."""
    path = path or request.url.path
    prefix = page_prefix(access.workspace.id)
    section = path.removeprefix(prefix).strip("/").split("/")[0]
    if request.method == "GET":
        query = request.url.query
        here = request.url.path + (f"?{query}" if query else "")
    else:
        here = path
    with get_connection_context() as conn:
        memberships = repo.get_memberships(conn, access.user["id"])
        invites = strip_items(conn, access.user["email"], zone_of(request))
    return {
        "invite_strip": invites,
        "here": here,
        "user": access.user,
        "workspace": access.workspace,
        "role": access.role,
        "base": prefix,
        "workspaces": [
            {
                "name": workspace.name,
                "url": page_prefix(workspace.id) + (f"/{section}" if section else ""),
                "current": workspace.id == access.workspace.id,
            }
            for workspace, _ in memberships
        ],
    }
