"""The MCP tools as plain functions: (connection, caller, arguments) -> result.

Each calls the service layer the pages and the JSON API use (`accounts`,
`cashflows`, the repository, `formulas` through `save_snapshot`, and the
dashboard's helpers), so no business rule lives here. What does live here
is what only an agent needs: names instead of ids, a workspace chosen by
name, and errors that say what to do next.

Raise ToolFailure with a message for the agent; `server` turns it into a
tool error. Read tools need a viewer role, write tools an editor role and
the write scope (the gate checks the scope first; this is the backstop).
"""

from __future__ import annotations

import datetime as dt
import difflib
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from psycopg import Connection
from pydantic import BaseModel, Field

from sensibility import repository as repo
from sensibility.accounts import (
    AccountError,
    create_account,
    parse_amount,
    parse_formula,
    preview_snapshot,
    retire_account,
    retire_blocker,
    retire_warning,
    save_snapshot,
    unretire_account,
    update_account,
)
from sensibility.cashflows import (
    CashFlowError,
    Period,
    category_totals,
    create_cash_flow,
    create_category,
    delete_category,
    every_text,
    in_period,
    per_year,
    percent_text,
    share,
    update_cash_flow,
)
from sensibility.cashflows import delete_cash_flow as delete_flow
from sensibility.clock import default_timezone, is_known_zone, today
from sensibility.formulas import quantize_cents
from sensibility.models import (
    Account,
    AccountCategory,
    CashFlow,
    CashFlowCategory,
    CashFlowDirection,
    FrequencyUnit,
    Record,
    RecordType,
    Role,
    User,
    Workspace,
)
from sensibility.web.accounts_model import format_percent, formula_text
from sensibility.web.dashboard import (
    account_cards,
    change_since,
    daily_totals,
    months_before,
)

from .results import (
    AccountView,
    Before,
    BalancesResult,
    CashFlowsResult,
    CategoryGroup,
    ChangeView,
    DeleteCashFlowResult,
    ExpenseCategory,
    FlowView,
    FormulaView,
    HistoryResult,
    HistoryRow,
    SaveAccountResult,
    SaveCashFlowResult,
    Side,
    Source,
    UpdateBalancesResult,
    WorkspacesResult,
    WorkspaceSummary,
    dollars,
)
from .tokens import READ_SCOPE, WRITE_SCOPE

READ_TOOLS = frozenset(
    {"list_workspaces", "get_balances", "get_history", "get_cash_flows"}
)
WRITE_TOOLS = frozenset(
    {"update_balances", "save_cash_flow", "delete_cash_flow", "save_account"}
)

# Amounts may arrive as JSON numbers or as strings ("12400.00", "$1,200").
Amount = str | float
Interval = Literal["snapshot", "month", "quarter", "year"]
CATEGORY_NAMES = ", ".join(c.label for c in AccountCategory) + ", or Uncategorized"


class ToolFailure(Exception):
    """A refusal the agent should see, with what to do about it."""


@dataclass(frozen=True)
class Caller:
    """Who is calling: the Sensibility user the token's `sub` maps to, and
    the token's scopes."""

    user: User
    scopes: frozenset[str]
    client_id: str

    @property
    def can_read(self) -> bool:
        return READ_SCOPE in self.scopes or WRITE_SCOPE in self.scopes

    @property
    def can_write(self) -> bool:
        return WRITE_SCOPE in self.scopes


def _require_write(caller: Caller) -> None:
    if not caller.can_write:
        raise ToolFailure(
            "This connection can only read. Reconnect Sensibility and grant "
            f"{WRITE_SCOPE} to make changes."
        )


# --- names -----------------------------------------------------------------


def _key(name: str) -> str:
    """How names compare: case-insensitive, runs of spaces as one."""
    return " ".join(name.split()).casefold()


def _quoted(names: list[str]) -> str:
    quoted = [repr(n) for n in names]
    if len(quoted) <= 2:
        return " or ".join(quoted)
    return ", ".join(quoted[:-1]) + ", or " + quoted[-1]


def suggestions(name: str, names: list[str], limit: int = 5) -> list[str]:
    """Names like `name`: those containing it (or contained in it), then
    close spellings."""
    key = _key(name)
    by_key: dict[str, str] = {}
    for n in names:
        by_key.setdefault(_key(n), n)
    found = [n for k, n in by_key.items() if key and (key in k or k in key)]
    found += [
        by_key[k]
        for k in difflib.get_close_matches(key, list(by_key), n=limit, cutoff=0.6)
    ]
    return list(dict.fromkeys(found))[:limit]


def unknown_name(kind: str, name: str, names: list[str]) -> ToolFailure:
    """ "No account named 'Chase'. Did you mean 'Chase Sapphire Reserve'?" """
    message = f"No {kind} named {name!r}."
    hints = suggestions(name, names)
    if hints:
        message += f" Did you mean {_quoted(hints)}?"
    elif names:
        listed = sorted(set(names), key=str.casefold)
        more = f" (and {len(listed) - 20} more)" if len(listed) > 20 else ""
        message += f" The {kind}s are: {', '.join(repr(n) for n in listed[:20])}{more}."
    else:
        message += f" There are no {kind}s yet."
    return ToolFailure(message)


def _workspace(
    conn: Connection, caller: Caller, name: str | None, needs: Role
) -> tuple[Workspace, Role]:
    """The workspace `name` picks among the caller's, checked for `needs`.

    With no name, the caller's only workspace; with several, an error
    listing them."""
    memberships = repo.get_memberships(conn, caller.user.id)
    names = [w.name for w, _ in memberships]
    if not memberships:
        raise ToolFailure(
            "You are not a member of any workspace yet. Create one in "
            "Sensibility (New workspace, in the user menu) or accept an invite "
            "there, then try again."
        )
    if name is None:
        if len(memberships) > 1:
            raise ToolFailure(
                f"You belong to {len(memberships)} workspaces, so say which with "
                f"`workspace`: {_quoted(names)}."
            )
        found = memberships
    else:
        found = [(w, r) for w, r in memberships if _key(w.name) == _key(name)]
        if not found:
            raise unknown_name("workspace", name, names)
        if len(found) > 1:
            raise ToolFailure(
                f"{len(found)} of your workspaces are named {found[0][0].name!r}. "
                "Rename one in its settings so they can be told apart."
            )
    workspace, role = found[0]
    if not role.allows(needs):
        raise ToolFailure(
            f"You are a {role.value} in {workspace.name!r}, and this needs the "
            f"{needs.value} role. An owner of {workspace.name!r} can change your "
            "role in its settings."
        )
    return workspace, role


_TYPE_SUFFIXES = {f" ({t.value})": t for t in RecordType}


def _match_accounts(
    accounts: list[Account], name: str, type: RecordType | None = None
) -> list[Account]:
    """Accounts named `name` (of `type`, if given). "Tax (liability)" names
    the liability when an asset shares the name."""
    found = [a for a in accounts if _key(a.name) == _key(name)]
    if not found:
        for suffix, suffix_type in _TYPE_SUFFIXES.items():
            if _key(name).endswith(suffix):
                bare = name.strip()[: -len(suffix)]
                found = [
                    a
                    for a in accounts
                    if _key(a.name) == _key(bare) and a.type == suffix_type
                ]
    if type is not None:
        found = [a for a in found if a.type == type]
    return found


def find_account(
    accounts: list[Account], name: str, type: RecordType | None = None
) -> Account:
    """The one account `name` means; an error naming candidates otherwise."""
    found = _match_accounts(accounts, name, type)
    if not found:
        pool = [a for a in accounts if type is None or a.type == type]
        raise unknown_name("account", name, [a.name for a in pool])
    if len(found) > 1:
        bare = found[0].name
        raise ToolFailure(
            f"{bare!r} names both an asset and a liability. Say "
            f"'{bare} (asset)' or '{bare} (liability)'."
        )
    return found[0]


def _label(account: Account, accounts: list[Account]) -> str:
    """The account's name, with its type when another account shares it."""
    shared = sum(1 for a in accounts if _key(a.name) == _key(account.name)) > 1
    return f"{account.name} ({account.type.value})" if shared else account.name


# --- small helpers -----------------------------------------------------------


def money(amount: Decimal) -> str:
    """Two decimal places: "12400.00"."""
    return str(quantize_cents(amount))


def _amount(value: Amount, what: str) -> Decimal:
    if isinstance(value, bool):
        raise ToolFailure(f"{what}: {value!r} is not an amount")
    try:
        return parse_amount(str(value))
    except AccountError as e:
        raise ToolFailure(f"{what}: {e}") from None


def _zone(timezone: str | None) -> str:
    if timezone is None:
        return default_timezone()
    if not is_known_zone(timezone):
        raise ToolFailure(
            f"{timezone!r} is not a known time zone. Use an IANA name such as "
            "America/Chicago, or leave it out to use the server's default."
        )
    return timezone


def _category(text: str) -> AccountCategory | None:
    """An account category from its value or label; "" or "Uncategorized"
    clears it."""
    key = "_".join(text.strip().casefold().replace("-", " ").split())
    if key in ("", "uncategorized", "none"):
        return None
    for category in AccountCategory:
        if category.value == key:
            return category
    raise ToolFailure(f"{text!r} is not a category. Use one of {CATEGORY_NAMES}.")


# --- views -------------------------------------------------------------------


def account_view(
    account: Account,
    amount: Decimal | None,
    accounts: list[Account],
    source: Source | None = None,
) -> AccountView:
    by_id = {a.id: a for a in accounts if a.id is not None}
    formula = account.formula
    return AccountView(
        name=account.name,
        type=account.type.value,
        category=account.category.label if account.category else None,
        amount=None if amount is None else money(amount),
        computed=account.is_computed,
        formula=None
        if formula is None
        else FormulaView(
            rate_percent=format_percent(formula.rate),
            cost_basis=money(formula.cost_basis),
            inputs=[
                by_id[i].name if i in by_id else f"account {i}"
                for i in account.input_ids
            ],
            text=formula_text(account, by_id),
        ),
        retired_on=account.retired_at,
        source=source,
    )


def balances_view(
    workspace: Workspace,
    records: list[Record],
    accounts: list[Account],
    day: dt.date,
    sources: dict[int, Source] | None = None,
) -> BalancesResult:
    """get_balances over these records and accounts: the dashboard's numbers
    and cards, with every active account."""
    points = daily_totals(records)
    latest = points[-1] if points else None
    cards = account_cards(records, accounts)
    active = {(a.type, a.name): a for a in accounts if a.is_active}
    sides = {}
    for type in RecordType:
        card = cards[type]
        groups = []
        for group in card["groups"]:
            views = []
            for row in group["rows"]:
                account = active[(type, row["name"])]
                source = None if sources is None else sources.get(account.id or 0)
                views.append(account_view(account, row["amount"], accounts, source))
            groups.append(
                CategoryGroup(
                    category=group["label"], total=money(group["total"]), accounts=views
                )
            )
        sides[type] = Side(total=money(card["total"]), categories=groups)
    change = change_since(points)
    return BalancesResult(
        workspace=workspace.name,
        as_of=latest.date if latest else None,
        days_since=(day - latest.date).days if latest else None,
        net_worth=money(latest.net_worth) if latest else None,
        change=None
        if change is None
        else ChangeView(
            since=change.since,
            amount=money(change.amount),
            percent=None
            if change.percent is None
            else str(change.percent.quantize(Decimal("0.1"))),
        ),
        assets=sides[RecordType.ASSET],
        liabilities=sides[RecordType.LIABILITY],
    )


def _flow_view(flow: CashFlow, period: Period, categories: dict[int, str]) -> FlowView:
    return FlowView(
        name=flow.name,
        direction=flow.direction.value,
        amount=money(flow.amount),
        every=flow.every,
        unit=flow.unit.value,
        every_text=every_text(flow.every, flow.unit),
        per_period=money(in_period(abs(per_year(flow)), period)),
        category=categories.get(flow.category_id)
        if flow.category_id is not None
        else None,
        note=flow.description,
        estimate=flow.is_estimate,
    )


def cash_flows_view(
    workspace: Workspace,
    flows: list[CashFlow],
    categories: list[CashFlowCategory],
    period: Period,
) -> CashFlowsResult:
    """The Cash flows page's figures, unformatted: summed unrounded per year
    and rounded once per figure (`web/cash_flows_routes.cash_flows_view`)."""
    incomes = [f for f in flows if f.direction == CashFlowDirection.INCOME]
    income = sum((per_year(f) for f in incomes), Decimal(0))
    groups = [g for g in category_totals(flows, categories) if g.flows]
    expenses = sum((g.yearly for g in groups), Decimal(0))  # negative
    net = income + expenses
    names = {c.id: c.name for c in categories}

    def share_text(yearly: Decimal) -> str | None:
        fraction = share(yearly, income)
        return None if fraction is None else percent_text(fraction)

    return CashFlowsResult(
        workspace=workspace.name,
        per=period.value,
        income=money(in_period(income, period)),
        expenses=money(in_period(-expenses, period)),
        left_over=money(in_period(net, period)),
        expenses_share=share_text(expenses),
        left_over_share=share_text(net),
        estimates=sum(1 for f in flows if f.is_estimate),
        income_flows=[_flow_view(f, period, names) for f in incomes],
        expense_categories=[
            ExpenseCategory(
                name=g.name,
                total=money(in_period(-g.yearly, period)),
                share_of_income=share_text(g.yearly),
                flows=[_flow_view(f, period, names) for f in g.flows],
            )
            for g in groups
        ],
    )


def _cash_flows_now(
    conn: Connection, workspace: Workspace, period: Period = Period.MONTH
) -> CashFlowsResult:
    return cash_flows_view(
        workspace,
        repo.get_cash_flows(conn, workspace.id),
        repo.get_cash_flow_categories(conn, workspace.id),
        period,
    )


# --- read tools --------------------------------------------------------------


def list_workspaces(conn: Connection, caller: Caller) -> WorkspacesResult:
    summaries = []
    for workspace, role in repo.get_memberships(conn, caller.user.id):
        points = daily_totals(repo.get_latest_snapshot_records(conn, workspace.id))
        summaries.append(
            WorkspaceSummary(
                name=workspace.name,
                role=role.value,
                latest_snapshot=points[-1].date if points else None,
                net_worth=money(points[-1].net_worth) if points else None,
            )
        )
    return WorkspacesResult(workspaces=summaries)


def get_balances(
    conn: Connection,
    caller: Caller,
    workspace: str | None = None,
    timezone: str | None = None,
) -> BalancesResult:
    found, _ = _workspace(conn, caller, workspace, Role.VIEWER)
    day = today(_zone(timezone))
    return balances_view(
        found,
        repo.get_all_records(conn, found.id),
        repo.get_accounts(conn, found.id),
        day,
    )


def period_of(day: dt.date, interval: Interval) -> str:
    if interval == "snapshot":
        return day.isoformat()
    if interval == "month":
        return f"{day.year}-{day.month:02d}"
    if interval == "quarter":
        return f"{day.year}-Q{(day.month - 1) // 3 + 1}"
    return str(day.year)


def get_history(
    conn: Connection,
    caller: Caller,
    workspace: str | None = None,
    start: dt.date | None = None,
    end: dt.date | None = None,
    interval: Interval = "month",
    accounts: list[str] | None = None,
) -> HistoryResult:
    found, _ = _workspace(conn, caller, workspace, Role.VIEWER)
    all_accounts = repo.get_accounts(conn, found.id)
    named = _resolve_all(all_accounts, accounts or [])
    records = repo.get_all_records(conn, found.id)
    if not records:
        return HistoryResult(
            workspace=found.name, interval=interval, start=start, end=end, rows=[]
        )
    # Ranges count back from the latest snapshot, not today, as the
    # dashboard's do.
    latest = max(r.date for r in records)
    end = end or latest
    start = start or months_before(latest, 12)
    if start > end:
        raise ToolFailure(f"start ({start}) is after end ({end}).")
    in_range = [r for r in records if start <= r.date <= end]
    period_end = {}
    for point in daily_totals(in_range):  # oldest first, so the last one wins
        period_end[period_of(point.date, interval)] = point
    amounts = {(r.account_id, r.date): r.amount for r in in_range}
    rows = [
        HistoryRow(
            period=period,
            date=point.date,
            net_worth=money(point.net_worth),
            assets=money(point.assets),
            liabilities=money(point.liabilities),
            accounts={
                _label(a, all_accounts): None
                if (amount := amounts.get((a.id, point.date))) is None
                else money(amount)
                for a in named
            },
        )
        for period, point in period_end.items()
    ]
    return HistoryResult(
        workspace=found.name, interval=interval, start=start, end=end, rows=rows
    )


def _resolve_all(accounts: list[Account], names: list[str]) -> list[Account]:
    """Every named account, or one error covering every name that failed."""
    resolved, errors = [], []
    for name in names:
        try:
            resolved.append(find_account(accounts, name))
        except ToolFailure as e:
            errors.append(str(e))
    if errors:
        raise ToolFailure(" ".join(errors))
    return _unique(resolved)


def _unique(accounts: list[Account]) -> list[Account]:
    seen: set[int | None] = set()
    unique = []
    for account in accounts:
        if account.id not in seen:
            seen.add(account.id)
            unique.append(account)
    return unique


def get_cash_flows(
    conn: Connection,
    caller: Caller,
    workspace: str | None = None,
    per: Literal["day", "month", "year"] = "month",
) -> CashFlowsResult:
    found, _ = _workspace(conn, caller, workspace, Role.VIEWER)
    return _cash_flows_now(conn, found, Period(per))


# --- update_balances ---------------------------------------------------------


def _computed_refusal(account: Account, accounts: list[Account]) -> str:
    by_id = {a.id: a for a in accounts if a.id is not None}
    inputs = [by_id[i].name for i in account.input_ids if i in by_id]
    return (
        f"{account.name!r} is computed ({formula_text(account, by_id)}), so it "
        f"cannot be set directly. Set its inputs ({', '.join(inputs)}) in "
        "balances, or its cost basis in cost_bases, instead."
    )


def _already_saved(
    workspace: Workspace,
    day: dt.date,
    earlier: list[Record],
    accounts: list[Account],
    saved_at: dt.datetime | None,
    zone: str,
) -> ToolFailure:
    point = daily_totals(earlier)[0]
    when = (
        f", saved at {saved_at.astimezone(ZoneInfo(zone)):%-I:%M %p %Z}"
        if saved_at
        else ""
    )
    by_id = {a.id: a for a in accounts}
    holds = "; ".join(
        f"{_label(by_id[r.account_id], accounts) if r.account_id in by_id else r.description} "
        f"{dollars(r.amount)}"
        for r in earlier
    )
    return ToolFailure(
        f"{workspace.name!r} already has a snapshot for today ({day}){when}: net "
        f"worth {dollars(point.net_worth)} (assets {dollars(point.assets)}, "
        f"liabilities {dollars(point.liabilities)}). It holds: {holds}. Saving "
        "again replaces it. Check with the user, then call update_balances again "
        "with overwrite: true (or preview: true to show the result first)."
    )


def update_balances(
    conn: Connection,
    caller: Caller,
    balances: dict[str, Amount],
    workspace: str | None = None,
    cost_bases: dict[str, Amount] | None = None,
    preview: bool = False,
    overwrite: bool = False,
    timezone: str | None = None,
) -> UpdateBalancesResult:
    _require_write(caller)
    found, _ = _workspace(conn, caller, workspace, Role.EDITOR)
    zone = _zone(timezone)
    day = today(zone)
    accounts = repo.get_accounts(conn, found.id)

    errors: list[str] = []
    values: dict[int, Decimal] = {}
    bases: dict[int, Decimal] = {}
    for name, amount in balances.items():
        try:
            account = find_account(accounts, name)
            if account.is_computed:
                raise ToolFailure(_computed_refusal(account, accounts))
            if not account.is_active:
                raise ToolFailure(
                    f"{account.name!r} is retired. Leave it out, or unretire it "
                    "with save_account first."
                )
            if account.id in values:
                raise ToolFailure(f"{account.name!r} is named twice in balances.")
            assert account.id is not None
            values[account.id] = _amount(amount, account.name)
        except ToolFailure as e:
            errors.append(str(e))
    for name, amount in (cost_bases or {}).items():
        try:
            account = find_account(accounts, name)
            if not account.is_computed:
                raise ToolFailure(
                    f"{account.name!r} is not a computed account, so it has no "
                    "cost basis."
                )
            assert account.id is not None
            bases[account.id] = _amount(amount, f"{account.name} cost basis")
        except ToolFailure as e:
            errors.append(str(e))
    if errors:
        raise ToolFailure(" ".join(errors))

    records = repo.get_all_records(conn, found.id)
    earlier = [r for r in records if r.date == day]
    if earlier and not overwrite and not preview:
        saved_at = repo.get_snapshot_saved_at(conn, found.id, day)
        raise _already_saved(found, day, earlier, accounts, saved_at, zone)
    points = daily_totals(records)
    before = (
        Before(date=points[-1].date, net_worth=money(points[-1].net_worth))
        if points
        else None
    )

    try:
        if preview:
            amounts = preview_snapshot(
                conn, found.id, values, bases, day, carry_forward=True
            )
            by_id = {a.id: a for a in accounts}
            after = [r for r in records if r.date != day] + [
                Record(
                    date=day,
                    account_id=account_id,
                    type=by_id[account_id].type,
                    description=by_id[account_id].name,
                    amount=amount,
                )
                for account_id, amount in amounts.items()
            ]
            shown = [_with_basis(a, bases) for a in accounts]
        else:
            save_snapshot(conn, found.id, values, bases, day, carry_forward=True)
            after = repo.get_all_records(conn, found.id)
            shown = repo.get_accounts(conn, found.id)
    except AccountError as e:
        raise ToolFailure(f"{e}. Nothing was saved.") from None

    sources: dict[int, Source] = {}
    for account in shown:
        if account.id is not None:
            sources[account.id] = (
                "computed"
                if account.is_computed
                else "updated"
                if account.id in values
                else "carried_forward"
            )
    return UpdateBalancesResult(
        saved=not preview,
        date=day,
        replaced=bool(earlier),
        before=before,
        balances=balances_view(found, after, shown, day, sources),
    )


def _with_basis(account: Account, bases: dict[int, Decimal]) -> Account:
    """The account as a preview shows it: with its new cost basis, if sent."""
    if account.formula is None or account.id not in bases:
        return account
    formula = account.formula.model_copy(
        update={"cost_basis": quantize_cents(bases[account.id])}
    )
    return account.model_copy(update={"formula": formula})


# --- cash flows --------------------------------------------------------------


def _find_flow(flows: list[CashFlow], name: str) -> CashFlow | None:
    """The flow `name` means, or None. Names are unique as stored, so a
    case-insensitive tie prefers the exact spelling."""
    found = [f for f in flows if _key(f.name) == _key(name)]
    if len(found) > 1:
        exact = [f for f in found if f.name == " ".join(name.split())]
        if len(exact) == 1:
            return exact[0]
        raise ToolFailure(
            f"Several cash flows are named like {name!r}: "
            f"{_quoted([f.name for f in found])}. Use the exact spelling."
        )
    return found[0] if found else None


def save_cash_flow(
    conn: Connection,
    caller: Caller,
    name: str,
    workspace: str | None = None,
    amount: Amount | None = None,
    direction: Literal["income", "expense"] | None = None,
    every: int | None = None,
    unit: Literal["day", "week", "month", "year"] | None = None,
    category: str | None = None,
    note: str | None = None,
    estimate: bool | None = None,
    new_name: str | None = None,
) -> SaveCashFlowResult:
    _require_write(caller)
    found, _ = _workspace(conn, caller, workspace, Role.EDITOR)
    flows = repo.get_cash_flows(conn, found.id)
    existing = _find_flow(flows, name)

    changes: dict = {}
    if amount is not None:
        changes["amount"] = _amount(amount, "amount")
    if direction is not None:
        changes["direction"] = CashFlowDirection(direction)
    if every is not None:
        changes["every"] = every
    if unit is not None:
        changes["unit"] = FrequencyUnit(unit)
    if note is not None:
        changes["description"] = note.strip() or None
    if estimate is not None:
        changes["is_estimate"] = estimate

    if existing is None:
        if new_name is not None:
            raise unknown_name("cash flow", name, [f.name for f in flows])
        missing = [
            field
            for field, value in (
                ("amount", amount),
                ("direction", direction),
                ("unit", unit),
            )
            if value is None
        ]
        if missing:
            message = (
                f"There is no cash flow named {name!r} yet. To create it, also "
                f"give {', '.join(missing)}."
            )
            hints = suggestions(name, [f.name for f in flows])
            if hints:
                message += f" To change an existing one, did you mean {_quoted(hints)}?"
            raise ToolFailure(message)
    elif new_name is None and category is None and not changes:
        raise ToolFailure(
            f"Nothing to change in {existing.name!r}: give at least one of "
            "amount, direction, every, unit, category, note, estimate or new_name."
        )

    created: CashFlowCategory | None = None
    if category is not None:
        changes["category_id"], created = _flow_category(conn, found, category)
    try:
        if existing is None:
            flow = create_cash_flow(
                conn,
                found.id,
                CashFlow(
                    name=name,
                    direction=changes["direction"],
                    amount=changes["amount"],
                    every=changes.get("every", 1),
                    unit=changes["unit"],
                    category_id=changes.get("category_id"),
                    description=changes.get("description"),
                    is_estimate=changes.get("is_estimate", False),
                ),
            )
        else:
            if new_name is not None:
                changes["name"] = new_name
            assert existing.id is not None
            flow = update_cash_flow(conn, found.id, existing.id, changes)
    except CashFlowError as e:
        if created is not None:
            # Created for this flow only; don't leave it behind.
            delete_category(conn, found.id, created.id)
        raise ToolFailure(f"{e}. Nothing was saved.") from None

    categories = repo.get_cash_flow_categories(conn, found.id)
    return SaveCashFlowResult(
        action="created" if existing is None else "updated",
        flow=_flow_view(flow, Period.MONTH, {c.id: c.name for c in categories}),
        created_category=created.name if created else None,
        cash_flows=_cash_flows_now(conn, found),
    )


def _flow_category(
    conn: Connection, workspace: Workspace, name: str
) -> tuple[int | None, CashFlowCategory | None]:
    """(category id, the category if it was just created). "" or
    "Uncategorized" (when no category has that name) clears it."""
    categories = repo.get_cash_flow_categories(conn, workspace.id)
    matches = [c for c in categories if _key(c.name) == _key(name)]
    if matches:
        return matches[0].id, None
    if _key(name) in ("", "uncategorized"):
        return None, None
    try:
        created = create_category(conn, workspace.id, name)
    except CashFlowError as e:
        raise ToolFailure(str(e)) from None
    return created.id, created


def delete_cash_flow(
    conn: Connection, caller: Caller, name: str, workspace: str | None = None
) -> DeleteCashFlowResult:
    _require_write(caller)
    found, _ = _workspace(conn, caller, workspace, Role.EDITOR)
    flows = repo.get_cash_flows(conn, found.id)
    flow = _find_flow(flows, name)
    if flow is None:
        raise unknown_name("cash flow", name, [f.name for f in flows])
    assert flow.id is not None
    try:
        delete_flow(conn, found.id, flow.id)
    except CashFlowError as e:
        raise ToolFailure(str(e)) from None
    return DeleteCashFlowResult(
        deleted=flow.name, cash_flows=_cash_flows_now(conn, found)
    )


# --- save_account ------------------------------------------------------------


class FormulaInput(BaseModel):
    """Makes the account computed: rate_percent × (sum of inputs − cost_basis)."""

    rate_percent: Amount = Field(description="The rate in percent: 15 means 15%")
    inputs: list[str] = Field(
        description="Names of the plain, active accounts it sums", min_length=1
    )
    cost_basis: Amount | None = Field(
        default=None,
        description="Subtracted from the inputs' sum; defaults to the current "
        "basis (or 0 for an account that is not computed yet)",
    )


def _formula(formula: FormulaInput, accounts: list[Account], existing: Account | None):
    if isinstance(formula.rate_percent, bool):
        raise ToolFailure("rate_percent must be a number, e.g. 15 for 15%")
    if formula.cost_basis is not None:
        basis = str(_amount(formula.cost_basis, "cost_basis"))
    elif existing is not None and existing.formula is not None:
        basis = str(existing.formula.cost_basis)
    else:
        basis = ""
    try:
        parsed = parse_formula(str(formula.rate_percent), basis)
    except AccountError as e:
        raise ToolFailure(str(e)) from None
    inputs = _resolve_all(accounts, formula.inputs)
    return parsed, [a.id for a in inputs if a.id is not None]


def save_account(
    conn: Connection,
    caller: Caller,
    name: str,
    workspace: str | None = None,
    type: Literal["asset", "liability"] | None = None,
    new_name: str | None = None,
    category: str | None = None,
    formula: FormulaInput | None = None,
    make_plain: bool = False,
    retired: bool | None = None,
    timezone: str | None = None,
) -> SaveAccountResult:
    _require_write(caller)
    found, _ = _workspace(conn, caller, workspace, Role.EDITOR)
    zone = _zone(timezone)
    accounts = repo.get_accounts(conn, found.id)
    record_type = RecordType(type) if type is not None else None
    if formula is not None and make_plain:
        raise ToolFailure("Give formula or make_plain, not both.")
    new_category = _category(category) if category is not None else None

    matches = _match_accounts(accounts, name, record_type)
    if len(matches) > 1:
        find_account(accounts, name, record_type)  # raises the ambiguity error
    existing = matches[0] if matches else None
    if existing is None and record_type is None:
        message = (
            f"There is no account named {name!r}. To create it, give type "
            "(asset or liability)."
        )
        hints = suggestions(name, [a.name for a in accounts])
        if hints:
            message += f" To change an existing one, did you mean {_quoted(hints)}?"
        raise ToolFailure(message)

    actions: list = []
    warnings: list[str] = []
    try:
        if existing is None:
            assert record_type is not None
            if new_name is not None:
                raise unknown_name(
                    "account", name, [a.name for a in accounts if a.type == record_type]
                )
            if retired:
                raise ToolFailure("A new account cannot start out retired.")
            parsed, input_ids = (
                _formula(formula, accounts, None) if formula else (None, [])
            )
            account = create_account(
                conn, found.id, name, record_type, parsed, input_ids, new_category
            )
            actions.append("created")
            for other in _match_accounts(accounts, name):
                warnings.append(
                    f"There is also {'an' if other.type == RecordType.ASSET else 'a'} "
                    f"{other.type.value} named {other.name!r}; "
                    "an account's type never changes, so this is a separate "
                    f"account. Refer to them as '{name} (asset)' and "
                    f"'{name} (liability)'."
                )
            if retired is False:
                warnings.append(f"{account.name!r} is new, so it was not retired.")
        else:
            account = existing
            assert existing.id is not None
            if retired and not existing.is_active:
                raise ToolFailure(f"{existing.name!r} is already retired.")
            if retired is False and existing.is_active:
                raise ToolFailure(f"{existing.name!r} is not retired.")
            if retired:
                # Before changing anything, so a blocked retire changes nothing.
                blocker = retire_blocker(conn, found.id, existing)
                if blocker:
                    raise ToolFailure(blocker)
            if retired is False:
                account = unretire_account(conn, found.id, existing.id)
                actions.append("unretired")
            changed = (
                new_name is not None
                or category is not None
                or formula is not None
                or make_plain
            )
            if changed:
                if formula is not None:
                    parsed, input_ids = _formula(formula, accounts, existing)
                elif make_plain:
                    parsed, input_ids = None, []
                else:
                    parsed, input_ids = existing.formula, existing.input_ids
                account = update_account(
                    conn,
                    found.id,
                    existing.id,
                    new_name if new_name is not None else existing.name,
                    parsed,
                    input_ids,
                    new_category if category is not None else existing.category,
                )
                actions.append("updated")
            if retired:
                warning = retire_warning(conn, found.id, account)
                if warning:
                    warnings.append(warning)
                account = retire_account(conn, found.id, existing.id, today(zone))
                actions.append("retired")
            if not actions:
                raise ToolFailure(
                    f"Nothing to change in {existing.name!r}: give new_name, "
                    "category, formula, make_plain or retired."
                )
    except AccountError as e:
        raise ToolFailure(str(e)) from None

    accounts = repo.get_accounts(conn, found.id)
    saved = next(a for a in accounts if a.id == account.id)
    latest = {
        r.account_id: r.amount for r in repo.get_latest_snapshot_records(conn, found.id)
    }
    return SaveAccountResult(
        actions=actions,
        account=account_view(saved, latest.get(saved.id), accounts),
        warnings=warnings,
    )
