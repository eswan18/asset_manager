"""Which workspace a request acts in, and whether the user's role allows it.

API routes name the workspace in the path. A workspace the user is not a
live member of is a 404, so its existence is not revealed; a role too low
for the route is a 403. Pages have no workspace in the path yet and act in
the user's oldest membership, until the frontend gets a workspace switcher.
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


def _api_access(needed: Role):
    def dependency(workspace_id: int, user: CurrentUser) -> WorkspaceAccess:
        with get_connection_context() as conn:
            found = repo.get_access(conn, workspace_id, user["id"])
        if found is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
        workspace, role = found
        _check_role(role, needed)
        return WorkspaceAccess(user=user, workspace=workspace, role=role)

    return dependency


def _page_access(needed: Role):
    def dependency(user: CurrentUser) -> WorkspaceAccess:
        with get_connection_context() as conn:
            memberships = repo.get_memberships(conn, user["id"])
        if not memberships:
            raise NoWorkspace()
        workspace, role = memberships[0]
        _check_role(role, needed)
        return WorkspaceAccess(user=user, workspace=workspace, role=role)

    return dependency


ViewerAccess = Annotated[WorkspaceAccess, Depends(_api_access(Role.VIEWER))]
EditorAccess = Annotated[WorkspaceAccess, Depends(_api_access(Role.EDITOR))]
OwnerAccess = Annotated[WorkspaceAccess, Depends(_api_access(Role.OWNER))]

PageViewer = Annotated[WorkspaceAccess, Depends(_page_access(Role.VIEWER))]
PageEditor = Annotated[WorkspaceAccess, Depends(_page_access(Role.EDITOR))]
