"""JSON API for agents and scripts.

Everything a workspace holds lives under /api/workspaces/{workspace_id}/.
The access dependencies answer 404 for a workspace you are not in and 403
for a role too low for the route.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from asset_manager import repository as repo
from asset_manager.accounts import AccountError, save_snapshot
from asset_manager.clock import default_timezone, today
from asset_manager.db import get_connection_context
from asset_manager.models import Account, Member, Role, Workspace
from asset_manager.repository import get_accounts, get_latest_snapshot_records
from asset_manager.workspaces import (
    WorkspaceError,
    change_role,
    create_workspace,
    delete_workspace,
    remove_member,
    update_workspace,
)

from .access import EditorAccess, OwnerAccess, ViewerAccess
from .auth import CurrentUser

router = APIRouter(prefix="/api")


def error(message: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


def workspace_json(workspace: Workspace, role: Role) -> dict[str, Any]:
    return {
        "id": workspace.id,
        "name": workspace.name,
        "timezone": workspace.timezone,
        "role": role.value,
    }


def member_json(member: Member) -> dict[str, Any]:
    return {
        "user_id": member.user_id,
        "email": member.email,
        "name": member.name,
        "role": member.role.value,
        "joined_at": member.joined_at.isoformat(),
    }


# --- you -------------------------------------------------------------------


@router.get("/me")
async def me(user: CurrentUser) -> JSONResponse:
    """You, and every workspace you are in with your role there."""
    with get_connection_context() as conn:
        memberships = repo.get_memberships(conn, user["id"])
    return JSONResponse(
        {
            "id": user["id"],
            "email": user["email"],
            "name": user["name"],
            "is_admin": user["is_admin"],
            "workspaces": [workspace_json(w, r) for w, r in memberships],
        }
    )


# --- workspaces ------------------------------------------------------------


class WorkspaceCreate(BaseModel):
    name: str
    timezone: str | None = None


class WorkspaceUpdate(BaseModel):
    name: str | None = None
    timezone: str | None = None


@router.post("/workspaces")
async def create_workspace_route(
    payload: WorkspaceCreate, user: CurrentUser
) -> JSONResponse:
    """A new workspace with you as its owner."""
    try:
        with get_connection_context() as conn:
            workspace = create_workspace(
                conn,
                user["id"],
                payload.name,
                payload.timezone or default_timezone(),
            )
    except WorkspaceError as e:
        return error(str(e))
    return JSONResponse(workspace_json(workspace, Role.OWNER), status_code=201)


@router.get("/workspaces/{workspace_id}")
async def get_workspace_route(access: ViewerAccess) -> JSONResponse:
    return JSONResponse(workspace_json(access.workspace, access.role))


@router.patch("/workspaces/{workspace_id}")
async def update_workspace_route(
    payload: WorkspaceUpdate, access: OwnerAccess
) -> JSONResponse:
    """Rename the workspace or change the time zone new snapshots are dated in."""
    try:
        with get_connection_context() as conn:
            workspace = update_workspace(
                conn, access.workspace, name=payload.name, timezone=payload.timezone
            )
    except WorkspaceError as e:
        return error(str(e))
    return JSONResponse(workspace_json(workspace, access.role))


@router.delete("/workspaces/{workspace_id}")
async def delete_workspace_route(access: OwnerAccess) -> JSONResponse:
    """Soft delete: gone for every member, but the data is kept."""
    with get_connection_context() as conn:
        delete_workspace(conn, access.workspace.id)
    return JSONResponse({"deleted": access.workspace.id})


# --- members ---------------------------------------------------------------


class RoleUpdate(BaseModel):
    role: Role


@router.get("/workspaces/{workspace_id}/members")
async def list_members(access: ViewerAccess) -> JSONResponse:
    with get_connection_context() as conn:
        members = repo.get_members(conn, access.workspace.id)
    return JSONResponse({"members": [member_json(m) for m in members]})


@router.patch("/workspaces/{workspace_id}/members/{user_id}")
async def change_member_role(
    user_id: int, payload: RoleUpdate, access: OwnerAccess
) -> JSONResponse:
    """Owners only. The last owner cannot be demoted."""
    try:
        with get_connection_context() as conn:
            change_role(conn, access.workspace.id, user_id, payload.role)
    except WorkspaceError as e:
        return error(str(e))
    return JSONResponse({"user_id": user_id, "role": payload.role.value})


@router.delete("/workspaces/{workspace_id}/members/{user_id}")
async def remove_member_route(user_id: int, access: ViewerAccess) -> JSONResponse:
    """Owners remove anyone; anyone can remove themselves (leave). The last
    owner cannot leave."""
    if user_id != access.user["id"] and access.role != Role.OWNER:
        raise HTTPException(
            status_code=403, detail="Only owners can remove other members"
        )
    try:
        with get_connection_context() as conn:
            remove_member(conn, access.workspace.id, user_id)
    except WorkspaceError as e:
        return error(str(e))
    return JSONResponse({"removed": user_id})


# --- accounts and snapshots --------------------------------------------------


def account_json(account: Account, amount: Decimal | None) -> dict[str, Any]:
    formula = account.formula
    return {
        "id": account.id,
        "name": account.name,
        "type": account.type.value,
        "category": account.category.value if account.category else None,
        "computed": account.is_computed,
        "formula": formula.model_dump(mode="json") if formula else None,
        "input_ids": list(account.input_ids),
        "amount": None if amount is None else str(amount),
    }


@router.get("/workspaces/{workspace_id}/accounts")
async def list_accounts(access: ViewerAccess) -> JSONResponse:
    """Active accounts with their amount on the latest snapshot date.

    `amount` is null for an account with no row on that date (new or just
    unretired); a snapshot save must then include it.
    """
    workspace_id = access.workspace.id
    with get_connection_context() as conn:
        accounts = get_accounts(conn, workspace_id, include_retired=False)
        latest = get_latest_snapshot_records(conn, workspace_id)
    amounts = {r.account_id: r.amount for r in latest}
    return JSONResponse(
        {
            "as_of": latest[0].date.isoformat() if latest else None,
            "accounts": [account_json(a, amounts.get(a.id)) for a in accounts],
        }
    )


class SnapshotUpdate(BaseModel):
    values: dict[int, Decimal] = Field(default_factory=dict)
    cost_bases: dict[int, Decimal] = Field(default_factory=dict)


@router.post("/workspaces/{workspace_id}/snapshots")
async def update_snapshot(
    payload: SnapshotUpdate, access: EditorAccess
) -> JSONResponse:
    """Save today's snapshot from the given values plus the latest snapshot.

    Today is the workspace's today, in its time zone. Plain accounts left out
    keep their latest amount; computed accounts are re-evaluated. Each
    account in the response says which of those happened.
    """
    workspace = access.workspace
    as_of = today(workspace.timezone)
    try:
        with get_connection_context() as conn:
            count = save_snapshot(
                conn,
                workspace.id,
                payload.values,
                payload.cost_bases,
                as_of,
                carry_forward=True,
            )
            accounts = get_accounts(conn, workspace.id, include_retired=False)
            saved = {
                r.account_id: r.amount
                for r in get_latest_snapshot_records(conn, workspace.id)
            }
    except AccountError as e:
        return error(str(e))

    def source(account: Account) -> str:
        if account.is_computed:
            return "computed"
        return "updated" if account.id in payload.values else "carried_forward"

    return JSONResponse(
        {
            "date": as_of.isoformat(),
            "count": count,
            "accounts": [
                {**account_json(a, saved.get(a.id)), "source": source(a)}
                for a in accounts
            ],
        }
    )
