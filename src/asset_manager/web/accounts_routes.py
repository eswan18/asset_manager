"""Routes for the editable accounts page, the account form, and Save."""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from psycopg import Connection
from pydantic import BaseModel, Field

from asset_manager.accounts import (
    AccountError,
    create_account,
    parse_amount,
    retire_account,
    retire_blocker,
    retire_warning,
    save_snapshot,
    unretire_account,
    update_account,
)
from asset_manager.clock import today
from asset_manager.db import get_connection_context
from asset_manager.models import Account, ProportionalFormula, Record, RecordType
from asset_manager.repository import (
    get_account,
    get_accounts,
    get_latest_snapshot_records,
)

from .auth import CurrentUser
from .rendering import render, set_flash

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
    # Active rows first, retired rows last, alphabetical within each group
    rows.sort(key=lambda r: (r["retired"], r["name"].lower()))
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
            "snapshot_is_today": bool(latest) and latest[0].date == today(),
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
    as_of = today()
    try:
        with get_connection_context() as conn:
            count = save_snapshot(conn, payload.values, payload.cost_bases, as_of)
    except AccountError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({"date": as_of.isoformat(), "count": count})


# --- account form ------------------------------------------------------------


def _form_defaults(type_: str) -> dict[str, Any]:
    return {
        "name": "",
        "type": type_,
        "computed": False,
        "rate_percent": "",
        "cost_basis": "",
        "input_ids": [],
    }


def _form_from_account(account: Account) -> dict[str, Any]:
    formula = account.formula
    return {
        "name": account.name,
        "type": account.type.value,
        "computed": formula is not None,
        "rate_percent": format_percent(formula.rate) if formula else "",
        "cost_basis": format_amount(formula.cost_basis) if formula else "",
        "input_ids": list(account.input_ids),
    }


def _candidates(accounts: list[Account], exclude_id: int | None) -> list[Account]:
    """Accounts eligible as formula inputs: active, plain, not the account itself."""
    return [
        a for a in accounts if a.is_active and not a.is_computed and a.id != exclude_id
    ]


def _parse_formula(
    computed: bool, rate_percent: str, cost_basis: str
) -> ProportionalFormula | None:
    if not computed:
        return None
    try:
        rate = (Decimal(rate_percent.strip()) / 100).quantize(Decimal("0.000001"))
    except InvalidOperation:
        raise AccountError("Rate must be a number, e.g. 15 for 15%") from None
    if not rate.is_finite() or rate < 0:
        raise AccountError("Rate must be zero or more")
    basis = parse_amount(cost_basis) if cost_basis.strip() else Decimal("0")
    return ProportionalFormula(rate=rate, cost_basis=basis)


def _retire_state(conn: Connection, account: Account) -> tuple[str | None, str | None]:
    """(blocker, warning) for the edit page's Retire button; both None when retired."""
    if not account.is_active:
        return None, None
    blocker = retire_blocker(conn, account)
    warning = None if blocker else retire_warning(conn, account)
    return blocker, warning


def _render_form(
    request: Request,
    user: dict[str, Any],
    *,
    account: Account | None,
    form: dict[str, Any],
    candidates: list[Account],
    error: str | None = None,
    blocker: str | None = None,
    warning: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    groups = [
        ("Assets", [c for c in candidates if c.type == RecordType.ASSET]),
        ("Liabilities", [c for c in candidates if c.type == RecordType.LIABILITY]),
    ]
    return render(
        request,
        "account_form.html",
        {
            "user": user,
            "active_tab": "accounts",
            "account": account,
            "form": form,
            "candidate_groups": [g for g in groups if g[1]],
            "error": error,
            "retire_blocker": blocker,
            "retire_warning": warning,
        },
        status_code=status_code,
    )


@router.get("/accounts/new", response_class=HTMLResponse)
async def new_account_page(
    request: Request, user: CurrentUser, type: Annotated[str, Query()] = "asset"
):
    type_ = type if type in ("asset", "liability") else "asset"
    with get_connection_context() as conn:
        candidates = _candidates(get_accounts(conn), None)
    return _render_form(
        request, user, account=None, form=_form_defaults(type_), candidates=candidates
    )


@router.post("/accounts")
async def create_account_route(
    request: Request,
    user: CurrentUser,
    name: Annotated[str, Form()] = "",
    type: Annotated[str, Form()] = "asset",
    computed: Annotated[bool, Form()] = False,
    rate_percent: Annotated[str, Form()] = "",
    cost_basis: Annotated[str, Form()] = "",
    input_ids: Annotated[list[int], Form()] = [],
):
    form = {
        "name": name,
        "type": type,
        "computed": computed,
        "rate_percent": rate_percent,
        "cost_basis": cost_basis,
        "input_ids": input_ids,
    }
    with get_connection_context() as conn:
        try:
            formula = _parse_formula(computed, rate_percent, cost_basis)
            account = create_account(conn, name, RecordType(type), formula, input_ids)
        except ValueError as e:
            candidates = _candidates(get_accounts(conn), None)
            return _render_form(
                request,
                user,
                account=None,
                form=form,
                candidates=candidates,
                error=str(e),
                status_code=400,
            )
    set_flash(request, "success", f"Added {account.name}")
    return RedirectResponse("/accounts", status_code=303)


@router.get("/accounts/{account_id}/edit", response_class=HTMLResponse)
async def edit_account_page(request: Request, user: CurrentUser, account_id: int):
    with get_connection_context() as conn:
        account = get_account(conn, account_id)
        if account is None:
            raise HTTPException(status_code=404, detail="Account not found")
        candidates = _candidates(get_accounts(conn), account_id)
        blocker, warning = _retire_state(conn, account)
    return _render_form(
        request,
        user,
        account=account,
        form=_form_from_account(account),
        candidates=candidates,
        blocker=blocker,
        warning=warning,
    )


@router.post("/accounts/{account_id}")
async def update_account_route(
    request: Request,
    user: CurrentUser,
    account_id: int,
    name: Annotated[str, Form()] = "",
    computed: Annotated[bool, Form()] = False,
    rate_percent: Annotated[str, Form()] = "",
    cost_basis: Annotated[str, Form()] = "",
    input_ids: Annotated[list[int], Form()] = [],
):
    with get_connection_context() as conn:
        account = get_account(conn, account_id)
        if account is None:
            raise HTTPException(status_code=404, detail="Account not found")
        form = {
            "name": name,
            "type": account.type.value,
            "computed": computed,
            "rate_percent": rate_percent,
            "cost_basis": cost_basis,
            "input_ids": input_ids,
        }
        try:
            formula = _parse_formula(computed, rate_percent, cost_basis)
            updated = update_account(conn, account_id, name, formula, input_ids)
        except ValueError as e:
            candidates = _candidates(get_accounts(conn), account_id)
            blocker, warning = _retire_state(conn, account)
            return _render_form(
                request,
                user,
                account=account,
                form=form,
                candidates=candidates,
                error=str(e),
                blocker=blocker,
                warning=warning,
                status_code=400,
            )
    set_flash(request, "success", f"Saved {updated.name}")
    return RedirectResponse("/accounts", status_code=303)


@router.post("/accounts/{account_id}/retire")
async def retire_account_route(request: Request, user: CurrentUser, account_id: int):
    with get_connection_context() as conn:
        try:
            account = retire_account(conn, account_id, today())
        except AccountError as e:
            set_flash(request, "error", str(e))
            return RedirectResponse("/accounts", status_code=303)
    set_flash(request, "success", f"Retired {account.name}")
    return RedirectResponse("/accounts", status_code=303)


@router.post("/accounts/{account_id}/unretire")
async def unretire_account_route(request: Request, user: CurrentUser, account_id: int):
    with get_connection_context() as conn:
        try:
            account = unretire_account(conn, account_id)
        except AccountError as e:
            set_flash(request, "error", str(e))
            return RedirectResponse("/accounts", status_code=303)
    set_flash(request, "success", f"Unretired {account.name}")
    return RedirectResponse("/accounts", status_code=303)
