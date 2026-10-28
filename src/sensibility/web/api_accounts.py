"""The Accounts page and the account drawer as data, and account writes.

    GET   /api/workspaces/{id}/accounts/overview?retired=   the page (viewer)
    GET   /api/workspaces/{id}/accounts/{aid}               the drawer (viewer)
    POST  /api/workspaces/{id}/accounts                     create (editor)
    PATCH /api/workspaces/{id}/accounts/{aid}               update (editor)
    POST  /api/workspaces/{id}/accounts/{aid}/retire        (editor)
    POST  /api/workspaces/{id}/accounts/{aid}/unretire      (editor)

The page models come from the helpers the Jinja pages use
(web/accounts_routes.py), and every rule is the service's (accounts.py), so
its messages come back as {"error": ...} with a 400. An account id from
another workspace is a 404, like one that does not exist. The plain
`GET .../accounts` list (api_routes.py) is unchanged: scripts use it.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from psycopg import Connection
from pydantic import BaseModel, Field

from sensibility.accounts import (
    AccountError,
    create_account,
    parse_formula,
    retire_account,
    unretire_account,
    update_account,
)
from sensibility.db import get_connection_context
from sensibility.models import (
    Account,
    AccountCategory,
    Formula,
    Record,
    RecordType,
    Role,
)
from sensibility.repository import (
    get_account,
    get_account_history,
    get_accounts,
    get_latest_snapshot_records,
)

from .access import EditorAccess, ViewerAccess
from .accounts_routes import (
    _candidate_groups,
    _retire_state,
    accounts_view,
    format_percent,
    formula_text,
    saved_total,
)
from .api_models import (
    CategoryOption,
    Money,
    category_options,
    maybe_money,
    money,
    responses,
)
from .viewer_zone import Today

router = APIRouter(prefix="/api/workspaces/{workspace_id}/accounts")

INPUT_GROUP_KINDS = {"Assets": RecordType.ASSET, "Liabilities": RecordType.LIABILITY}


# --- response models ---------------------------------------------------------


class InputRef(BaseModel):
    id: int
    name: str


class FormulaOut(BaseModel):
    """A computed account's value: rate × (sum of inputs − cost basis)."""

    kind: Literal["proportional"] = "proportional"
    rate: str = Field(description='The rate as a fraction: "0.15"')
    rate_percent: str = Field(description='The rate in percent: "15", "32.5"')
    cost_basis: Money
    inputs: list[InputRef] = Field(description="The accounts it sums")
    text: str = Field(description='"15% × (Schwab + Fidelity − basis)"')


class AccountOut(BaseModel):
    id: int
    name: str
    type: RecordType
    category: AccountCategory | None = Field(description="Null is Uncategorized")
    amount: Money | None = Field(
        description="On the workspace's latest snapshot date; null if it has "
        "no row there (added, retired or unretired since)"
    )
    computed: bool
    formula: FormulaOut | None
    retired_at: dt.date | None = Field(description="Null while active")


class OverviewGroup(BaseModel):
    """One category subheading of a section."""

    key: str = Field(description='The category\'s key, or "uncategorized"')
    label: str
    subtotal: Money = Field(description="Its active accounts' saved amounts")
    retired: bool = Field(description="Every account in it is retired")
    accounts: list[AccountOut] = Field(
        description="Active first, then retired; by name within each"
    )


class OverviewSection(BaseModel):
    kind: RecordType
    title: str = Field(description='"Assets" or "Liabilities"')
    total: Money = Field(description="Its active accounts' saved amounts")
    groups: list[OverviewGroup] = Field(
        description="AccountCategory order, Uncategorized last, empty ones left out"
    )


class AccountsOverview(BaseModel):
    """The Accounts page. Totals are of saved amounts; the page recomputes
    them live as amounts are staged."""

    as_of: dt.date = Field(
        description="Today in the viewer's zone: the date a save now would carry"
    )
    last_saved: dt.date | None = Field(description="The latest snapshot's date")
    snapshot_is_today: bool = Field(description="A save now replaces today's snapshot")
    net_worth: Money
    retired_count: int = Field(description="Retired accounts, listed or not")
    can_edit: bool
    categories: list[CategoryOption] = Field(
        description="The account categories, for the drawer's select"
    )
    sections: list[OverviewSection] = Field(
        description="Assets, then Liabilities; retired accounts only with ?retired=true"
    )


class InputOption(BaseModel):
    id: int
    name: str
    amount: Money | None = Field(description="On the latest snapshot")


class InputGroup(BaseModel):
    kind: RecordType
    label: str = Field(description='"Assets" or "Liabilities"')
    accounts: list[InputOption]


class HistoryPoint(BaseModel):
    date: dt.date
    amount: Money


class AccountDetail(BaseModel):
    """The account drawer."""

    account: AccountOut
    can_edit: bool
    eligible_inputs: list[InputGroup] = Field(
        description="Accounts that can be formula inputs: active, plain, not "
        "this one. Empty groups left out"
    )
    retire_blocker: str | None = Field(
        description="Why Retire is refused (an active computed account uses "
        "it); null when retired"
    )
    retire_warning: str | None = Field(
        description="Shown before retiring an account last saved at non-zero; "
        "null when blocked or retired"
    )
    history: list[HistoryPoint] = Field(description="Every snapshot, newest first")


# --- request models ----------------------------------------------------------


class FormulaIn(BaseModel):
    """Makes the account computed. Text as typed in the form; the service
    parses it and reports what it cannot use."""

    rate_percent: str = Field(description='"15" for 15%')
    cost_basis: str | None = Field(
        default=None,
        description='"$82,386.74", "82386.74" or blank for zero. Left out on '
        "an update, a computed account keeps its basis",
    )
    input_ids: list[int] = Field(
        default_factory=list, description="Plain, active accounts to sum"
    )


class AccountCreate(BaseModel):
    name: str
    type: RecordType
    category: AccountCategory | None = None
    formula: FormulaIn | None = Field(default=None, description="Null: a plain account")


class AccountUpdate(BaseModel):
    """Only the fields sent change. `category: null` makes it Uncategorized;
    `formula: null` makes it plain. The type never changes."""

    name: str | None = None
    category: AccountCategory | None = None
    formula: FormulaIn | None = None


# --- views -------------------------------------------------------------------


def account_out(
    account: Account, amount: Decimal | None, by_id: dict[int, Account]
) -> AccountOut:
    """`by_id`: the workspace's accounts, for the formula's input names."""
    assert account.id is not None
    formula = account.formula
    return AccountOut(
        id=account.id,
        name=account.name,
        type=account.type,
        category=account.category,
        amount=maybe_money(amount),
        computed=account.is_computed,
        formula=None
        if formula is None
        else FormulaOut(
            rate=_plain(formula.rate),
            rate_percent=format_percent(formula.rate),
            cost_basis=money(formula.cost_basis),
            inputs=[
                InputRef(id=i, name=by_id[i].name if i in by_id else f"account {i}")
                for i in account.input_ids
            ],
            text=formula_text(account, by_id),
        ),
        retired_at=account.retired_at,
    )


def overview_view(
    accounts: list[Account],
    latest: list[Record],
    as_of: dt.date,
    *,
    include_retired: bool,
    can_edit: bool,
) -> AccountsOverview:
    """The Accounts page from accounts_view(): its groups, order and totals.
    `latest` is the latest snapshot's records; `as_of` the viewer's today."""
    view = accounts_view(accounts, latest, as_of)
    by_id = {a.id: a for a in accounts if a.id is not None}
    amounts = {r.account_id: r.amount for r in latest if r.account_id is not None}
    totals: dict[str, Decimal] = {}
    sections = []
    for section in view["sections"]:
        kind = section["kind"]
        totals[kind] = saved_total([r for r in view["rows"] if r["type"] == kind])
        groups = []
        for group in section["groups"]:
            rows = [r for r in group["rows"] if include_retired or not r["retired"]]
            if rows:
                groups.append(
                    OverviewGroup(
                        key=group["key"],
                        label=group["label"],
                        subtotal=money(saved_total(group["rows"])),
                        retired=group["retired"],
                        accounts=[
                            account_out(by_id[r["id"]], amounts.get(r["id"]), by_id)
                            for r in rows
                        ],
                    )
                )
        sections.append(
            OverviewSection(
                kind=RecordType(kind),
                title=section["title"],
                total=money(totals[kind]),
                groups=groups,
            )
        )
    return AccountsOverview(
        as_of=as_of,
        last_saved=latest[0].date if latest else None,
        snapshot_is_today=view["snapshot_is_today"],
        net_worth=money(totals["asset"] - totals["liability"]),
        retired_count=view["retired_count"],
        can_edit=can_edit,
        categories=category_options(),
        sections=sections,
    )


def _plain(number: Decimal) -> str:
    """0.150000 -> "0.15", 1.000000 -> "1", never exponent notation."""
    text = f"{number:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Account not found")


def _existing(conn: Connection, workspace_id: int, account_id: int) -> Account:
    account = get_account(conn, workspace_id, account_id)
    if account is None:
        raise _not_found()
    return account


def _saved(conn: Connection, workspace_id: int, account_id: int) -> AccountOut:
    """The account as it is now, for a write's response."""
    accounts = get_accounts(conn, workspace_id)
    by_id = {a.id: a for a in accounts if a.id is not None}
    amounts = {
        r.account_id: r.amount for r in get_latest_snapshot_records(conn, workspace_id)
    }
    return account_out(by_id[account_id], amounts.get(account_id), by_id)


def _formula(payload: FormulaIn, existing: Account | None) -> tuple[Formula, list[int]]:
    basis = payload.cost_basis
    if basis is None:
        basis = (
            str(existing.formula.cost_basis)
            if existing is not None and existing.formula is not None
            else ""
        )
    return parse_formula(payload.rate_percent, basis), payload.input_ids


def _bad_request(e: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(e))


# --- routes ------------------------------------------------------------------
# /overview is declared before /{account_id}, which would otherwise take it.


@router.get("/overview", responses=responses(404))
async def accounts_overview(
    access: ViewerAccess,
    as_of: Today,
    retired: Annotated[
        bool, Query(description="Include retired accounts, as Show retired does")
    ] = False,
) -> AccountsOverview:
    """The Accounts page's model."""
    workspace_id = access.workspace.id
    with get_connection_context() as conn:
        accounts = get_accounts(conn, workspace_id)
        latest = get_latest_snapshot_records(conn, workspace_id)
    return overview_view(
        accounts,
        latest,
        as_of,
        include_retired=retired,
        can_edit=access.role.allows(Role.EDITOR),
    )


@router.get("/{account_id}", responses=responses(404))
async def account_detail(access: ViewerAccess, account_id: int) -> AccountDetail:
    """The account drawer's model."""
    workspace_id = access.workspace.id
    with get_connection_context() as conn:
        account = _existing(conn, workspace_id, account_id)
        accounts = get_accounts(conn, workspace_id)
        latest = get_latest_snapshot_records(conn, workspace_id)
        blocker, warning = _retire_state(conn, workspace_id, account)
        history = get_account_history(conn, workspace_id, account_id)
    by_id = {a.id: a for a in accounts if a.id is not None}
    amounts = {r.account_id: r.amount for r in latest if r.account_id is not None}
    return AccountDetail(
        account=account_out(account, amounts.get(account_id), by_id),
        can_edit=access.role.allows(Role.EDITOR),
        eligible_inputs=[
            InputGroup(
                kind=INPUT_GROUP_KINDS[label],
                label=label,
                accounts=[
                    InputOption(
                        id=m["id"],
                        name=m["name"],
                        amount=money(Decimal(m["amount"])) if m["amount"] else None,
                    )
                    for m in members
                ],
            )
            for label, members in _candidate_groups(accounts, account_id, amounts)
        ],
        retire_blocker=blocker,
        retire_warning=warning,
        history=[HistoryPoint(date=r.date, amount=money(r.amount)) for r in history],
    )


@router.post("", status_code=201, responses=responses(400, 403, 404))
async def create_account_route(
    payload: AccountCreate, access: EditorAccess
) -> AccountOut:
    """A new active account, with no amount until the next save."""
    workspace_id = access.workspace.id
    with get_connection_context() as conn:
        try:
            formula, input_ids = (
                _formula(payload.formula, None) if payload.formula else (None, [])
            )
            account = create_account(
                conn,
                workspace_id,
                payload.name,
                payload.type,
                formula,
                input_ids,
                category=payload.category,
            )
        except ValueError as e:
            raise _bad_request(e) from None
        assert account.id is not None
        return _saved(conn, workspace_id, account.id)


@router.patch("/{account_id}", responses=responses(400, 403, 404))
async def update_account_route(
    account_id: int, payload: AccountUpdate, access: EditorAccess
) -> AccountOut:
    """Rename, recategorize, or switch between plain and computed."""
    workspace_id = access.workspace.id
    sent = payload.model_fields_set
    with get_connection_context() as conn:
        existing = _existing(conn, workspace_id, account_id)
        try:
            if "name" in sent and payload.name is None:
                raise AccountError("Name is required")
            if "formula" not in sent:
                formula, input_ids = existing.formula, existing.input_ids
            elif payload.formula is None:
                formula, input_ids = None, []
            else:
                formula, input_ids = _formula(payload.formula, existing)
            update_account(
                conn,
                workspace_id,
                account_id,
                payload.name if payload.name is not None else existing.name,
                formula,
                input_ids,
                category=payload.category if "category" in sent else existing.category,
            )
        except ValueError as e:
            raise _bad_request(e) from None
        return _saved(conn, workspace_id, account_id)


@router.post("/{account_id}/retire", responses=responses(400, 403, 404))
async def retire_account_route(
    account_id: int, access: EditorAccess, as_of: Today
) -> AccountOut:
    """Retired as of today in the viewer's zone. Refused while an active
    computed account uses it (the drawer's retire_blocker)."""
    workspace_id = access.workspace.id
    with get_connection_context() as conn:
        _existing(conn, workspace_id, account_id)
        try:
            retire_account(conn, workspace_id, account_id, as_of)
        except ValueError as e:
            raise _bad_request(e) from None
        return _saved(conn, workspace_id, account_id)


@router.post("/{account_id}/unretire", responses=responses(400, 403, 404))
async def unretire_account_route(account_id: int, access: EditorAccess) -> AccountOut:
    """Active again, with no amount until the next save. A computed account
    whose inputs are no longer usable is refused until its formula is edited."""
    workspace_id = access.workspace.id
    with get_connection_context() as conn:
        _existing(conn, workspace_id, account_id)
        try:
            unretire_account(conn, workspace_id, account_id)
        except ValueError as e:
            raise _bad_request(e) from None
        return _saved(conn, workspace_id, account_id)
