"""JSON API for agents and scripts: read accounts, save a partial snapshot."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from asset_manager.accounts import AccountError, save_snapshot
from asset_manager.clock import today
from asset_manager.db import get_connection_context
from asset_manager.models import Account
from asset_manager.repository import get_accounts, get_latest_snapshot_records

from .auth import CurrentUser

router = APIRouter(prefix="/api")


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


@router.get("/accounts")
async def list_accounts(user: CurrentUser) -> JSONResponse:
    """Active accounts with their amount on the latest snapshot date.

    `amount` is null for an account with no row on that date (new or just
    unretired); a snapshot save must then include it.
    """
    with get_connection_context() as conn:
        accounts = get_accounts(conn, include_retired=False)
        latest = get_latest_snapshot_records(conn)
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


@router.post("/snapshots")
async def update_snapshot(payload: SnapshotUpdate, user: CurrentUser) -> JSONResponse:
    """Save today's snapshot from the given values plus the latest snapshot.

    Plain accounts left out keep their latest amount; computed accounts are
    re-evaluated. Each account in the response says which of those happened.
    """
    as_of = today()
    try:
        with get_connection_context() as conn:
            count = save_snapshot(
                conn, payload.values, payload.cost_bases, as_of, carry_forward=True
            )
            accounts = get_accounts(conn, include_retired=False)
            saved = {r.account_id: r.amount for r in get_latest_snapshot_records(conn)}
    except AccountError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

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
