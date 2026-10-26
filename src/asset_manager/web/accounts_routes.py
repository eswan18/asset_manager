"""Routes for the editable accounts page, the account form, and Save."""

from __future__ import annotations

import logging
from datetime import date
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
from asset_manager.models import (
    Account,
    AccountCategory,
    ProportionalFormula,
    Record,
    RecordType,
)
from asset_manager.repository import (
    get_account,
    get_account_history,
    get_accounts,
    get_latest_snapshot_records,
)

from .access import (
    EditorAccess,
    ViewerAccess,
    WorkspaceAccess,
    page_prefix,
    shell_context,
)
from .rendering import render, set_flash

logger = logging.getLogger(__name__)
# Every page names its workspace, as the API does: /api/workspaces/1/accounts
# is the data behind /workspaces/1/accounts.
router = APIRouter(prefix="/workspaces/{workspace_id}")


# --- view helpers ----------------------------------------------------------


def _accounts_url(access: WorkspaceAccess) -> str:
    return f"{page_prefix(access.workspace.id)}/accounts"


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
    has no row on that date (new or just unretired).
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
                "category": account.category.value if account.category else None,
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
                # The saved value as money: a computed row's read-only figure
                # before the script recomputes it.
                "value_display": "—" if amount is None else format_money(amount),
                # "was $X" under an edited row: the value a Discard returns to.
                "was_display": "nothing yet"
                if amount is None
                else format_money(amount),
                "retired_display": format_short_date(account.retired_at)
                if account.retired_at
                else None,
            }
        )
    return rows


def format_short_date(day: date, today: date | None = None) -> str:
    """Oct 24, 2026; or Oct 24 when `today` is given and in the same year."""
    if today is not None and day.year == today.year:
        return f"{day:%b} {day.day}"
    return f"{day:%b} {day.day}, {day.year}"


def snapshot_line(today: date, last_saved: date | None) -> str:
    """The page head's line: what Save will write, and when it last ran.
    Both dates are in the workspace's time zone."""
    head = f"Saving writes today's snapshot, {format_short_date(today)}."
    if last_saved is None:
        return f"{head} Nothing saved yet."
    if last_saved == today:
        return f"{head} Last saved today; saving again replaces it."
    return f"{head} Last saved {format_short_date(last_saved, today)}."


def saved_total(rows: list[dict[str, Any]]) -> Decimal:
    """Sum of the active rows' amounts on the latest snapshot date. The page's
    script recomputes every total live; these are what it starts from."""
    return sum(
        (
            Decimal(r["amount"])
            for r in rows
            if not r["retired"] and r["amount"] is not None
        ),
        Decimal("0"),
    )


def section_view(kind: str, title: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """One card of the accounts page: its category groups with subtotals and
    its total, from the rows of one type."""
    groups = category_groups(rows)
    for group in groups:
        group["subtotal"] = format_money(saved_total(group["rows"]))
    return {
        "kind": kind,
        "title": title,
        "groups": groups,
        "total": format_money(saved_total(rows)),
    }


UNCATEGORIZED = "uncategorized"


def category_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Split one section's rows under category subheadings.

    Categories come in AccountCategory order with Uncategorized last, and only
    those with rows appear. Row order within a group is preserved. `retired`
    marks a group whose rows are all retired, so it hides with them.
    """
    order = [(c.value, c.label) for c in AccountCategory]
    order.append((UNCATEGORIZED, "Uncategorized"))
    groups = []
    for key, label in order:
        members = [r for r in rows if (r["category"] or UNCATEGORIZED) == key]
        if members:
            groups.append(
                {
                    "key": key,
                    "label": label,
                    "rows": members,
                    "retired": all(r["retired"] for r in members),
                }
            )
    return groups


# --- page ------------------------------------------------------------------


@router.get("/accounts", response_class=HTMLResponse)
async def accounts_page(request: Request, access: ViewerAccess):
    """Render the editable accounts page."""
    workspace = access.workspace
    shell = shell_context(access, request.url.path)
    try:
        with get_connection_context() as conn:
            accounts = get_accounts(conn, workspace.id)
            latest = get_latest_snapshot_records(conn, workspace.id)
    except Exception:
        logger.exception("Database error in accounts")
        return render(
            request,
            "accounts.html",
            {
                **shell,
                "active_tab": "accounts",
                "error": "An error occurred while loading your data. Please try again later.",
                "rows": [],
            },
        )

    rows = account_rows(accounts, latest)
    # Active rows first, retired rows last, alphabetical within each group
    rows.sort(key=lambda r: (r["retired"], r["name"].lower()))
    assets = [r for r in rows if r["type"] == "asset"]
    liabilities = [r for r in rows if r["type"] == "liability"]
    as_of = today(workspace.timezone)
    last_saved = latest[0].date if latest else None
    return render(
        request,
        "accounts.html",
        {
            **shell,
            "active_tab": "accounts",
            "rows": rows,
            "sections": [
                section_view("asset", "Assets", assets),
                section_view("liability", "Liabilities", liabilities),
            ],
            "net_worth": format_money(saved_total(assets) - saved_total(liabilities)),
            "retired_count": sum(1 for r in rows if r["retired"]),
            "snapshot_line": snapshot_line(as_of, last_saved),
            "snapshot_is_today": last_saved == as_of,
        },
    )


# --- save ------------------------------------------------------------------


class SnapshotPayload(BaseModel):
    values: dict[int, Decimal] = Field(default_factory=dict)
    cost_bases: dict[int, Decimal] = Field(default_factory=dict)


@router.post("/snapshots")
async def save_snapshot_route(
    payload: SnapshotPayload, access: EditorAccess
) -> JSONResponse:
    """Write a complete snapshot for today from the page's staged values."""
    workspace = access.workspace
    as_of = today(workspace.timezone)
    try:
        with get_connection_context() as conn:
            count = save_snapshot(
                conn, workspace.id, payload.values, payload.cost_bases, as_of
            )
    except AccountError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({"date": as_of.isoformat(), "count": count})


# --- account form ------------------------------------------------------------


def _form_defaults(type_: str) -> dict[str, Any]:
    return {
        "name": "",
        "type": type_,
        "category": "",
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
        "category": account.category.value if account.category else "",
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


def _parse_category(category: str) -> AccountCategory | None:
    if not category:
        return None
    try:
        return AccountCategory(category)
    except ValueError:
        raise AccountError(f"{category!r} is not a category") from None


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


def history_rows(records: list[Record]) -> list[dict[str, Any]]:
    """View model for the edit page's history table: newest first, with the
    change since the previous snapshot. `records` arrive newest first."""
    rows: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        previous = records[index + 1].amount if index + 1 < len(records) else None
        change = None if previous is None else record.amount - previous
        rows.append(
            {
                "date": record.date.strftime("%B %-d, %Y"),
                "amount": format_money(record.amount),
                "change": None if change is None else format_change(change),
                "direction": (
                    "flat"
                    if change is None or change == 0
                    else ("up" if change > 0 else "down")
                ),
            }
        )
    return rows


def format_money(amount: Decimal) -> str:
    return f"-${-amount:,.2f}" if amount < 0 else f"${amount:,.2f}"


def format_change(change: Decimal) -> str:
    if change == 0:
        return "$0.00"
    return f"+{format_money(change)}" if change > 0 else format_money(change)


def _retire_state(
    conn: Connection, workspace_id: int, account: Account
) -> tuple[str | None, str | None]:
    """(blocker, warning) for the edit page's Retire button; both None when retired."""
    if not account.is_active:
        return None, None
    blocker = retire_blocker(conn, workspace_id, account)
    warning = None if blocker else retire_warning(conn, workspace_id, account)
    return blocker, warning


def _render_form(
    request: Request,
    access: WorkspaceAccess,
    *,
    account: Account | None,
    form: dict[str, Any],
    candidates: list[Account],
    error: str | None = None,
    blocker: str | None = None,
    warning: str | None = None,
    history: list[dict[str, Any]] | None = None,
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
            **shell_context(access, request.url.path),
            "active_tab": "accounts",
            "account": account,
            "form": form,
            "categories": list(AccountCategory),
            "candidate_groups": [g for g in groups if g[1]],
            "error": error,
            "retire_blocker": blocker,
            "retire_warning": warning,
            "history": history,
        },
        status_code=status_code,
    )


@router.get("/accounts/new", response_class=HTMLResponse)
async def new_account_page(
    request: Request, access: EditorAccess, type: Annotated[str, Query()] = "asset"
):
    type_ = type if type in ("asset", "liability") else "asset"
    with get_connection_context() as conn:
        candidates = _candidates(get_accounts(conn, access.workspace.id), None)
    return _render_form(
        request,
        access,
        account=None,
        form=_form_defaults(type_),
        candidates=candidates,
    )


@router.post("/accounts")
async def create_account_route(
    request: Request,
    access: EditorAccess,
    name: Annotated[str, Form()] = "",
    type: Annotated[str, Form()] = "asset",
    category: Annotated[str, Form()] = "",
    computed: Annotated[bool, Form()] = False,
    rate_percent: Annotated[str, Form()] = "",
    cost_basis: Annotated[str, Form()] = "",
    input_ids: Annotated[list[int], Form()] = [],
):
    form = {
        "name": name,
        "type": type,
        "category": category,
        "computed": computed,
        "rate_percent": rate_percent,
        "cost_basis": cost_basis,
        "input_ids": input_ids,
    }
    workspace_id = access.workspace.id
    with get_connection_context() as conn:
        try:
            formula = _parse_formula(computed, rate_percent, cost_basis)
            account = create_account(
                conn,
                workspace_id,
                name,
                RecordType(type),
                formula,
                input_ids,
                category=_parse_category(category),
            )
        except ValueError as e:
            candidates = _candidates(get_accounts(conn, workspace_id), None)
            return _render_form(
                request,
                access,
                account=None,
                form=form,
                candidates=candidates,
                error=str(e),
                status_code=400,
            )
    set_flash(request, "success", f"Added {account.name}")
    return RedirectResponse(_accounts_url(access), status_code=303)


@router.get("/accounts/{account_id}/edit", response_class=HTMLResponse)
async def edit_account_page(request: Request, access: ViewerAccess, account_id: int):
    workspace_id = access.workspace.id
    with get_connection_context() as conn:
        account = get_account(conn, workspace_id, account_id)
        if account is None:
            raise HTTPException(status_code=404, detail="Account not found")
        candidates = _candidates(get_accounts(conn, workspace_id), account_id)
        blocker, warning = _retire_state(conn, workspace_id, account)
        history = history_rows(get_account_history(conn, workspace_id, account_id))
    return _render_form(
        request,
        access,
        account=account,
        form=_form_from_account(account),
        candidates=candidates,
        blocker=blocker,
        warning=warning,
        history=history,
    )


@router.post("/accounts/{account_id}")
async def update_account_route(
    request: Request,
    access: EditorAccess,
    account_id: int,
    name: Annotated[str, Form()] = "",
    category: Annotated[str, Form()] = "",
    computed: Annotated[bool, Form()] = False,
    rate_percent: Annotated[str, Form()] = "",
    cost_basis: Annotated[str, Form()] = "",
    input_ids: Annotated[list[int], Form()] = [],
):
    workspace_id = access.workspace.id
    with get_connection_context() as conn:
        account = get_account(conn, workspace_id, account_id)
        if account is None:
            raise HTTPException(status_code=404, detail="Account not found")
        form = {
            "name": name,
            "type": account.type.value,
            "category": category,
            "computed": computed,
            "rate_percent": rate_percent,
            "cost_basis": cost_basis,
            "input_ids": input_ids,
        }
        try:
            formula = _parse_formula(computed, rate_percent, cost_basis)
            updated = update_account(
                conn,
                workspace_id,
                account_id,
                name,
                formula,
                input_ids,
                category=_parse_category(category),
            )
        except ValueError as e:
            candidates = _candidates(get_accounts(conn, workspace_id), account_id)
            blocker, warning = _retire_state(conn, workspace_id, account)
            history = history_rows(get_account_history(conn, workspace_id, account_id))
            return _render_form(
                request,
                access,
                account=account,
                form=form,
                candidates=candidates,
                error=str(e),
                blocker=blocker,
                warning=warning,
                history=history,
                status_code=400,
            )
    set_flash(request, "success", f"Saved {updated.name}")
    return RedirectResponse(_accounts_url(access), status_code=303)


@router.post("/accounts/{account_id}/retire")
async def retire_account_route(request: Request, access: EditorAccess, account_id: int):
    workspace = access.workspace
    with get_connection_context() as conn:
        try:
            account = retire_account(
                conn, workspace.id, account_id, today(workspace.timezone)
            )
        except AccountError as e:
            set_flash(request, "error", str(e))
            return RedirectResponse(_accounts_url(access), status_code=303)
    set_flash(request, "success", f"Retired {account.name}")
    return RedirectResponse(_accounts_url(access), status_code=303)


@router.post("/accounts/{account_id}/unretire")
async def unretire_account_route(
    request: Request, access: EditorAccess, account_id: int
):
    with get_connection_context() as conn:
        try:
            account = unretire_account(conn, access.workspace.id, account_id)
        except AccountError as e:
            set_flash(request, "error", str(e))
            return RedirectResponse(_accounts_url(access), status_code=303)
    set_flash(request, "success", f"Unretired {account.name}")
    return RedirectResponse(_accounts_url(access), status_code=303)
