"""Routes for the editable accounts page, the account form, and Save."""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from asset_manager.accounts import AccountError, save_snapshot
from asset_manager.db import get_connection_context
from asset_manager.models import Account, Record
from asset_manager.repository import get_accounts, get_latest_snapshot_records

from .auth import CurrentUser
from .rendering import render

logger = logging.getLogger(__name__)
router = APIRouter()


# --- view helpers ----------------------------------------------------------


def format_percent(rate: Decimal) -> str:
    """0.15 -> "15", 0.325 -> "32.5"."""
    text = f"{rate * 100:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def format_amount(amount: Decimal | None) -> str:
    return "" if amount is None else f"{amount:,.2f}"


def formula_text(account: Account, by_id: dict[int, Account]) -> str:
    """Human-readable formula, e.g. "15% × (Schwab + Fidelity − basis)"."""
    formula = account.formula
    if formula is None:
        return ""
    names = [by_id[i].name if i in by_id else f"account {i}" for i in account.input_ids]
    return f"{format_percent(formula.rate)}% × ({' + '.join(names)} − basis)"


def account_rows(accounts: list[Account], latest: list[Record]) -> list[dict[str, Any]]:
    """JSON-safe view model for the accounts page, one dict per account.

    `amount` is the account's value on the latest snapshot date, or None if it
    has no row on that date (new, just unretired, or dropped from the sheet).
    """
    by_id = {a.id: a for a in accounts if a.id is not None}
    amounts = {r.account_id: r.amount for r in latest}
    rows = []
    for account in accounts:
        amount = amounts.get(account.id)
        formula = account.formula
        rows.append(
            {
                "id": account.id,
                "name": account.name,
                "type": account.type.value,
                "computed": account.is_computed,
                "formula": formula.model_dump(mode="json") if formula else None,
                "input_ids": list(account.input_ids),
                "amount": None if amount is None else str(amount),
                "amount_display": format_amount(amount),
                "basis_display": format_amount(formula.cost_basis) if formula else "",
                "retired": not account.is_active,
                "retired_at": account.retired_at.isoformat()
                if account.retired_at
                else None,
                "formula_text": formula_text(account, by_id),
            }
        )
    return rows


# --- page ------------------------------------------------------------------


@router.get("/accounts", response_class=HTMLResponse)
async def accounts_page(request: Request, user: CurrentUser):
    """Render the editable accounts page."""
    try:
        with get_connection_context() as conn:
            accounts = get_accounts(conn)
            latest = get_latest_snapshot_records(conn)
    except Exception:
        logger.exception("Database error in accounts")
        return render(
            request,
            "accounts.html",
            {
                "user": user,
                "active_tab": "accounts",
                "error": "An error occurred while loading your data. Please try again later.",
                "rows": [],
            },
        )

    rows = account_rows(accounts, latest)
    # Active rows first, retired rows last, id order within each group
    rows.sort(key=lambda r: (r["retired"], r["id"]))
    return render(
        request,
        "accounts.html",
        {
            "user": user,
            "active_tab": "accounts",
            "rows": rows,
            "assets": [r for r in rows if r["type"] == "asset"],
            "liabilities": [r for r in rows if r["type"] == "liability"],
            "retired_count": sum(1 for r in rows if r["retired"]),
            "snapshot_date": latest[0].date if latest else None,
        },
    )


# --- save ------------------------------------------------------------------


class SnapshotPayload(BaseModel):
    values: dict[int, Decimal] = Field(default_factory=dict)
    cost_bases: dict[int, Decimal] = Field(default_factory=dict)


@router.post("/snapshots")
async def save_snapshot_route(
    payload: SnapshotPayload, user: CurrentUser
) -> JSONResponse:
    """Write a complete snapshot for today from the page's staged values."""
    today = date.today()
    try:
        with get_connection_context() as conn:
            count = save_snapshot(conn, payload.values, payload.cost_bases, today)
    except AccountError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({"date": today.isoformat(), "count": count})
