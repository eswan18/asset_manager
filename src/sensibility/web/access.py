"""Which workspace a request acts in, and whether the user's role allows it.

API routes name the workspace in the path (`/api/workspaces/{workspace_id}/…`).
A workspace the user is not a live member of is a 404, so its existence is
not revealed; a role too low for the route is a 403.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, HTTPException

from sensibility import repository as repo
from sensibility.db import get_connection_context
from sensibility.models import Role, Workspace

from .auth import CurrentUser


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


def check_can_remove(access: WorkspaceAccess, user_id: int) -> None:
    """Owners remove anyone; anyone may remove themselves (leave)."""
    if user_id != access.user["id"] and access.role != Role.OWNER:
        raise HTTPException(
            status_code=403, detail="Only owners can remove other members"
        )
