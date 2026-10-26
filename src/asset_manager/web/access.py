"""Which workspace a request acts in, and whether the user's role allows it.

API routes and pages both name the workspace in the path (pages are the API
path without `/api`). A workspace the user is not a live member of is a 404,
so its existence is not revealed; a role too low for the route is a 403.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, HTTPException

from asset_manager import repository as repo
from asset_manager.db import get_connection_context
from asset_manager.models import Role, Workspace

from .auth import CurrentUser


@dataclass(frozen=True)
class WorkspaceAccess:
    user: dict[str, Any]
    workspace: Workspace
    role: Role


class NoWorkspace(Exception):
    """A page was requested by a user who is not in any workspace."""


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


def oldest_workspace_id(user: dict[str, Any]) -> int:
    """The workspace that bare paths (`/`, `/accounts`) redirect into."""
    with get_connection_context() as conn:
        memberships = repo.get_memberships(conn, user["id"])
    if not memberships:
        raise NoWorkspace()
    return memberships[0][0].id


def shell_context(access: WorkspaceAccess, path: str) -> dict[str, Any]:
    """What base.html needs on every page: the user, this workspace, and the
    picker's other workspaces, each linking to the same section of the app
    (an account's edit page maps to the other workspace's Accounts page)."""
    prefix = page_prefix(access.workspace.id)
    section = path.removeprefix(prefix).strip("/").split("/")[0]
    with get_connection_context() as conn:
        memberships = repo.get_memberships(conn, access.user["id"])
    return {
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
