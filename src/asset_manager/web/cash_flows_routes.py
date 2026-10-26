"""The Cash flows page, and its two drawers: a cash flow's form (board R)
and category management (board T).

Like the account form, each drawer is rendered by its own route over the
real page, which keeps its `?per=` period. Writes go through the service
layer in `cashflows.py`, as the JSON API's do.
"""

from __future__ import annotations

import logging
import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from psycopg import Connection

from asset_manager import repository as repo
from asset_manager.accounts import MAX_AMOUNT
from asset_manager.cashflows import (
    MAX_EVERY,
    CashFlowError,
    CategoryTotal,
    Period,
    category_totals,
    create_cash_flow,
    create_category,
    delete_cash_flow,
    delete_category,
    every_text,
    in_period,
    move_category,
    parse_period,
    per_year,
    percent_text,
    rates,
    share,
    update_cash_flow,
    update_category,
)
from asset_manager.db import get_connection_context
from asset_manager.formulas import quantize_cents
from asset_manager.models import (
    CashFlow,
    CashFlowCategory,
    CashFlowDirection,
    FrequencyUnit,
    Role,
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
router = APIRouter(prefix="/workspaces/{workspace_id}")

INCOME_COLOR = "var(--asset)"
LEFTOVER_COLOR = "var(--leftover)"
# A category with no flows has no color on the page.
EMPTY_CATEGORY_COLOR = "var(--rule-strong)"
# Expense categories take the liability ramp by size, largest strongest.
# Past four, the smaller ones share the palest step: color strength always
# means size, so a small category never looks like the largest one.
EXPENSE_RAMP = (
    "var(--liability)",
    "var(--liability-2)",
    "var(--liability-3)",
    "var(--liability-4)",
)
MINUS = "−"


# --- view helpers ----------------------------------------------------------


def money(amount: Decimal, *, cents: bool = True, sign: bool = False) -> str:
    """ "$1,234.56"; negatives get a minus sign, and `sign` adds "+" to
    positives. Without cents it rounds half up to whole dollars."""
    if not cents:
        amount = amount.quantize(Decimal(1), rounding=ROUND_HALF_UP)
    body = f"${abs(amount):,.2f}" if cents else f"${abs(amount):,.0f}"
    if amount < 0:
        return MINUS + body
    if sign and amount > 0:
        return "+" + body
    return body


def expense_colors(groups: list[CategoryTotal]) -> list[str]:
    """One ramp color per group, in the groups' order, assigned by size."""
    by_size = sorted(range(len(groups)), key=lambda i: (groups[i].yearly, i))
    colors = [""] * len(groups)
    for rank, index in enumerate(by_size):
        colors[index] = EXPENSE_RAMP[min(rank, len(EXPENSE_RAMP) - 1)]
    return colors


def _flow_row(flow: CashFlow, period: Period) -> dict[str, Any]:
    return {
        "id": flow.id,
        "name": flow.name,
        "estimate": flow.is_estimate,
        "amount": money(flow.amount),
        "every": every_text(flow.every, flow.unit),
        "value": money(in_period(abs(per_year(flow)), period)),
    }


def _width(part: Decimal, whole: Decimal) -> str:
    """A slice's flex weight: its unrounded percentage of `whole`."""
    return f"{abs(part) * 100 / whole:.4f}"


def cash_flows_view(
    flows: list[CashFlow], categories: list[CashFlowCategory], period: Period
) -> dict[str, Any]:
    """Everything the page shows, for one period.

    Amounts are summed unrounded per year and rounded once per figure, so a
    category's total is its flows' exact sum, not a sum of rounded rows.
    Shares are of income and display-rounded; bar widths are unrounded.
    """
    incomes = [f for f in flows if f.direction == CashFlowDirection.INCOME]
    income = sum((per_year(f) for f in incomes), Decimal(0))
    # A card per category with expenses: a category holding only income
    # (or nothing yet) is not an expense category on this page.
    groups = [g for g in category_totals(flows, categories) if g.flows]
    expenses = sum((g.yearly for g in groups), Decimal(0))  # negative
    net = income + expenses
    colors = expense_colors(groups)

    def share_text(yearly: Decimal) -> str | None:
        fraction = share(yearly, income)
        return None if fraction is None else percent_text(fraction)

    # The bar. 100% is income, unless expenses are more than income: then
    # it is all expenses, scaled to their total.
    if income <= 0:
        bar_state = "no_income"
    elif net < 0:
        bar_state = "over"
    else:
        bar_state = "normal"
    slices = []
    if bar_state != "no_income":
        whole = income if bar_state == "normal" else -expenses
        for group, color in zip(groups, colors):
            if group.yearly:
                slices.append(
                    {
                        "label": group.name,
                        "color": color,
                        "weight": _width(group.yearly, whole),
                        "amount": money(in_period(-group.yearly, period)),
                        "share": share_text(group.yearly),
                    }
                )
        if bar_state == "normal" and net > 0:
            slices.append(
                {
                    "label": "Left over",
                    "color": LEFTOVER_COLOR,
                    "weight": _width(net, whole),
                    "amount": money(in_period(net, period)),
                    "share": share_text(net),
                }
            )

    income_card = {
        "name": "Income",
        "color": INCOME_COLOR,
        "total": money(in_period(income, period)),
        "note": "All income",
        "rows": [_flow_row(f, period) for f in incomes],
        "empty": "No income yet",
        "add_query": "direction=income",
    }
    expense_cards = [
        {
            "name": group.name,
            "color": color,
            "total": money(in_period(-group.yearly, period)),
            "note": f"{text} of income"
            if (text := share_text(group.yearly))
            else "No income to compare",
            "rows": [_flow_row(f, period) for f in group.flows],
            "empty": "No expenses yet",
            "add_query": "direction=expense"
            + (f"&category_id={group.category.id}" if group.category else ""),
        }
        for group, color in zip(groups, colors)
    ]

    # The headline's second figure: the net over a year, or over a month
    # when the page already shows a year.
    other = Period.MONTH if period == Period.YEAR else Period.YEAR
    estimates = sum(1 for f in flows if f.is_estimate)
    return {
        "period": period.value,
        "empty": not flows,
        "net": money(in_period(net, period), sign=True),
        "income": money(in_period(income, period)),
        "other": f"{money(in_period(net, other), cents=False)} a {other.value}",
        "estimates": estimates,
        "expenses": money(in_period(-expenses, period)),
        "expenses_share": share_text(expenses),
        "bar_state": bar_state,
        "slices": slices,
        "over_by": money(in_period(-net, period)) if net < 0 else None,
        "cards": [income_card, *expense_cards],
        # Each expense category's color on this page, by category id (None
        # for Uncategorized), so the drawers can match it.
        "colors": {
            (group.category.id if group.category else None): color
            for group, color in zip(groups, colors)
        },
    }


# --- page ------------------------------------------------------------------


def _page_url(access: WorkspaceAccess, period: Period) -> str:
    return f"{page_prefix(access.workspace.id)}/cash-flows?per={period.value}"


def _categories_url(access: WorkspaceAccess, period: Period, extra: str = "") -> str:
    prefix = page_prefix(access.workspace.id)
    return f"{prefix}/cash-flow-categories?per={period.value}{extra}"


def _page_context(access: WorkspaceAccess, period: Period) -> dict[str, Any]:
    """What every render of cash_flows.html needs besides the view: the
    shell, and the period toggle. The toggle always links to the page
    itself, so it works the same under a drawer or after a failed save."""
    page = f"{page_prefix(access.workspace.id)}/cash-flows"
    return {
        # The page's path, not a drawer's: the picker maps to Cash flows.
        **shell_context(access, page),
        "active_tab": "cash_flows",
        "can_edit": access.role.allows(Role.EDITOR),
        "period": period.value,
        "periods": [
            (p.value.title(), f"{page}?per={p.value}", p == period) for p in Period
        ],
    }


@router.get("/cash-flows", response_class=HTMLResponse)
async def cash_flows_page(request: Request, access: ViewerAccess, per: str = ""):
    """Render the Cash flows page. `per` is day, month (the default) or year."""
    period = parse_period(per)
    context = _page_context(access, period)
    try:
        with get_connection_context() as conn:
            flows = repo.get_cash_flows(conn, access.workspace.id)
            categories = repo.get_cash_flow_categories(conn, access.workspace.id)
    except Exception:
        logger.exception("Database error in cash flows")
        return render(
            request,
            "cash_flows.html",
            {
                **context,
                "error": "An error occurred while loading your data. Please try again later.",
                "view": None,
            },
        )
    return render(
        request,
        "cash_flows.html",
        {**context, "view": cash_flows_view(flows, categories, period)},
    )


def _drawer_context(
    access: WorkspaceAccess, conn: Connection, period: Period
) -> tuple[dict[str, Any], list[CashFlow], list[CashFlowCategory]]:
    """The page under a drawer, rendered as it is on its own."""
    flows = repo.get_cash_flows(conn, access.workspace.id)
    categories = repo.get_cash_flow_categories(conn, access.workspace.id)
    context = {
        **_page_context(access, period),
        "view": cash_flows_view(flows, categories, period),
        "drawer_open": True,
        "close_href": _page_url(access, period),
    }
    return context, flows, categories


# --- the cash flow drawer (board R) -----------------------------------------


def _form_defaults(direction: str, category_id: int | None) -> dict[str, Any]:
    return {
        "name": "",
        "direction": direction,
        "amount": "",
        "every": "1",
        "unit": FrequencyUnit.MONTH.value,
        "category_id": "" if category_id is None else str(category_id),
        "is_estimate": False,
        "description": "",
    }


def _form_from_flow(flow: CashFlow) -> dict[str, Any]:
    return {
        "name": flow.name,
        "direction": flow.direction.value,
        "amount": str(flow.amount),
        "every": str(flow.every),
        "unit": flow.unit.value,
        "category_id": "" if flow.category_id is None else str(flow.category_id),
        "is_estimate": flow.is_estimate,
        "description": flow.description or "",
    }


_AMOUNT = re.compile(r"-?(?:[0-9]+\.?[0-9]*|\.[0-9]+)")


def _parse_amount(text: str) -> Decimal:
    """ "$1,234.50" -> Decimal. Plain digits only (no exponents or NaN), the
    same text the drawer's script reads. A minus sign gets through so the
    service can say why it is refused; the service also rounds to cents
    and refuses amounts too large."""
    cleaned = re.sub(r"[$,\s]", "", text)
    if not _AMOUNT.fullmatch(cleaned):
        raise CashFlowError("Amount must be a number")
    return Decimal(cleaned)


def _parse_form(form: dict[str, Any]) -> dict[str, Any]:
    """The form's text as CashFlow fields. Raises CashFlowError for text
    that is not one of the choices or not a number; the service checks
    everything else (name, sign, size, range, category)."""
    try:
        direction = CashFlowDirection(form["direction"])
    except ValueError:
        raise CashFlowError("Choose income or expense") from None
    try:
        unit = FrequencyUnit(form["unit"])
    except ValueError:
        raise CashFlowError("Choose day, week, month or year") from None
    every = form["every"].strip()
    if not re.fullmatch(r"[0-9]+", every):
        raise CashFlowError("Every must be a whole number, e.g. 2 for every 2 weeks")
    category = form["category_id"].strip()
    if category and not re.fullmatch(r"[0-9]+", category):
        raise CashFlowError("Choose a category from the list")
    return {
        "name": form["name"],
        "direction": direction,
        "amount": _parse_amount(form["amount"]),
        "every": int(every),
        "unit": unit,
        "category_id": int(category) if category else None,
        "description": form["description"],
        "is_estimate": form["is_estimate"],
    }


def form_rates(form: dict[str, Any]) -> dict[str, str] | None:
    """The drawer's rates strip: the form's amount a day, a month and a
    year, as `rates()` gives them (so they match the page), unsigned. None
    while the amount or frequency is not one the service would accept."""
    try:
        fields = _parse_form(form)
    except CashFlowError:
        return None
    amount, every = fields["amount"], fields["every"]
    if amount < 0 or amount >= MAX_AMOUNT:
        return None
    if not 1 <= every <= MAX_EVERY:
        return None
    flow = CashFlow(
        name="",
        direction=CashFlowDirection.INCOME,
        amount=quantize_cents(amount),
        every=every,
        unit=fields["unit"],
    )
    return {
        period: money(Decimal(value)) for period, value in rates(per_year(flow)).items()
    }


def _heading(
    flow: CashFlow | None,
    form: dict[str, Any],
    categories: list[CashFlowCategory],
    colors: dict[int | None, str],
) -> dict[str, str]:
    """The drawer's eyebrow ("Edit expense · Food") and its rule's color:
    the category's color on the page, or blue for income."""
    direction = form["direction"]
    if direction not in ("income", "expense"):
        direction = "expense"
    by_id = {str(c.id): c for c in categories}
    category = by_id.get(form["category_id"])
    eyebrow = f"{'Edit' if flow else 'New'} {direction}"
    if category is not None:
        eyebrow += f" · {category.name}"
    if direction == "income":
        color = INCOME_COLOR
    else:
        key = category.id if category is not None else None
        color = colors.get(key, EXPENSE_RAMP[0])
    return {"eyebrow": eyebrow, "color": color}


def _render_flow_form(
    request: Request,
    access: WorkspaceAccess,
    conn: Connection,
    period: Period,
    *,
    flow: CashFlow | None,
    form: dict[str, Any],
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """The cash flow form: a drawer over the Cash flows page."""
    context, _, categories = _drawer_context(access, conn, period)
    colors = context["view"]["colors"]
    return render(
        request,
        "cash_flow_form.html",
        {
            **context,
            "flow": flow,
            "form": form,
            "heading": _heading(flow, form, categories, colors),
            "income_color": INCOME_COLOR,
            # Each option carries its color, so the header follows the
            # select. A category with no expenses yet has none on the page.
            "uncategorized_color": colors.get(None, EXPENSE_RAMP[0]),
            "category_options": [
                {
                    "id": str(c.id),
                    "name": c.name,
                    "color": colors.get(c.id, EXPENSE_RAMP[0]),
                }
                for c in categories
            ],
            "units": [u.value for u in FrequencyUnit],
            "rates": form_rates(form),
            # Not `error`: base.html shows that in the page behind the scrim.
            "form_error": error,
        },
        status_code=status_code,
    )


def _submitted(
    name: str,
    direction: str,
    amount: str,
    every: str,
    unit: str,
    category_id: str,
    is_estimate: bool,
    description: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "direction": direction,
        "amount": amount,
        "every": every,
        "unit": unit,
        "category_id": category_id,
        "is_estimate": is_estimate,
        "description": description,
    }


@router.get("/cash-flows/new", response_class=HTMLResponse)
async def new_cash_flow_page(
    request: Request,
    access: EditorAccess,
    per: str = "",
    direction: str = "expense",
    category_id: int | None = None,
):
    """`direction` and `category_id` prefill the form, so each card's
    + Add starts in that card. Anything unknown falls back to an
    uncategorized expense."""
    period = parse_period(per)
    if direction not in ("income", "expense"):
        direction = "expense"
    with get_connection_context() as conn:
        if (
            category_id is not None
            and repo.get_cash_flow_category(conn, access.workspace.id, category_id)
            is None
        ):
            category_id = None
        return _render_flow_form(
            request,
            access,
            conn,
            period,
            flow=None,
            form=_form_defaults(direction, category_id),
        )


@router.post("/cash-flows")
async def create_cash_flow_route(
    request: Request,
    access: EditorAccess,
    per: str = "",
    name: Annotated[str, Form()] = "",
    direction: Annotated[str, Form()] = "",
    amount: Annotated[str, Form()] = "",
    every: Annotated[str, Form()] = "",
    unit: Annotated[str, Form()] = "",
    category_id: Annotated[str, Form()] = "",
    is_estimate: Annotated[bool, Form()] = False,
    description: Annotated[str, Form()] = "",
):
    period = parse_period(per)
    form = _submitted(
        name, direction, amount, every, unit, category_id, is_estimate, description
    )
    with get_connection_context() as conn:
        try:
            flow = create_cash_flow(
                conn, access.workspace.id, CashFlow(**_parse_form(form))
            )
        except CashFlowError as e:
            return _render_flow_form(
                request,
                access,
                conn,
                period,
                flow=None,
                form=form,
                error=str(e),
                status_code=400,
            )
    set_flash(request, "success", f"Added {flow.name}")
    return RedirectResponse(_page_url(access, period), status_code=303)


def _get_flow(conn: Connection, access: WorkspaceAccess, flow_id: int) -> CashFlow:
    flow = repo.get_cash_flow(conn, access.workspace.id, flow_id)
    if flow is None:
        raise HTTPException(status_code=404, detail="Cash flow not found")
    return flow


@router.get("/cash-flows/{flow_id}/edit", response_class=HTMLResponse)
async def edit_cash_flow_page(
    request: Request, access: EditorAccess, flow_id: int, per: str = ""
):
    period = parse_period(per)
    with get_connection_context() as conn:
        flow = _get_flow(conn, access, flow_id)
        return _render_flow_form(
            request, access, conn, period, flow=flow, form=_form_from_flow(flow)
        )


@router.post("/cash-flows/{flow_id}")
async def update_cash_flow_route(
    request: Request,
    access: EditorAccess,
    flow_id: int,
    per: str = "",
    name: Annotated[str, Form()] = "",
    direction: Annotated[str, Form()] = "",
    amount: Annotated[str, Form()] = "",
    every: Annotated[str, Form()] = "",
    unit: Annotated[str, Form()] = "",
    category_id: Annotated[str, Form()] = "",
    is_estimate: Annotated[bool, Form()] = False,
    description: Annotated[str, Form()] = "",
):
    period = parse_period(per)
    form = _submitted(
        name, direction, amount, every, unit, category_id, is_estimate, description
    )
    with get_connection_context() as conn:
        flow = _get_flow(conn, access, flow_id)
        try:
            updated = update_cash_flow(
                conn, access.workspace.id, flow_id, _parse_form(form)
            )
        except CashFlowError as e:
            return _render_flow_form(
                request,
                access,
                conn,
                period,
                flow=flow,
                form=form,
                error=str(e),
                status_code=400,
            )
    set_flash(request, "success", f"Saved {updated.name}")
    return RedirectResponse(_page_url(access, period), status_code=303)


@router.post("/cash-flows/{flow_id}/delete")
async def delete_cash_flow_route(
    request: Request, access: EditorAccess, flow_id: int, per: str = ""
):
    period = parse_period(per)
    with get_connection_context() as conn:
        flow = _get_flow(conn, access, flow_id)
        delete_cash_flow(conn, access.workspace.id, flow_id)
    set_flash(request, "success", f"Deleted {flow.name}")
    return RedirectResponse(_page_url(access, period), status_code=303)


# --- the categories drawer (board T) ----------------------------------------

_PER_SUFFIX = {Period.DAY: "/day", Period.MONTH: "/mo", Period.YEAR: "/yr"}


def category_rows(
    flows: list[CashFlow],
    categories: list[CashFlowCategory],
    colors: dict[int | None, str],
    period: Period,
) -> list[dict[str, Any]]:
    """One row per category, in display order: its color on the page and
    a meta line ("4 flows · $3,376.67/mo"). Income in a category is shown
    apart from its expenses; an empty category is "No flows yet"."""
    suffix = _PER_SUFFIX[period]
    rows = []
    for index, category in enumerate(categories):
        members = [f for f in flows if f.category_id == category.id]
        expenses = [f for f in members if f.direction == CashFlowDirection.EXPENSE]
        incomes = [f for f in members if f.direction == CashFlowDirection.INCOME]
        parts = []
        if expenses:
            spent = -sum((per_year(f) for f in expenses), Decimal(0))
            parts.append(money(in_period(spent, period)) + suffix)
        if incomes:
            earned = sum((per_year(f) for f in incomes), Decimal(0))
            parts.append("income " + money(in_period(earned, period)) + suffix)
        count = len(members)
        if count:
            meta = " · ".join([f"{count} flow{'' if count == 1 else 's'}", *parts])
        else:
            meta = "No flows yet"
        if category.id in colors:
            color = colors[category.id]
        elif incomes:
            color = INCOME_COLOR
        else:
            color = EMPTY_CATEGORY_COLOR
        rows.append(
            {
                "id": category.id,
                "name": category.name,
                "value": category.name,
                "color": color,
                "meta": meta,
                "count": count,
                "first": index == 0,
                "last": index == len(categories) - 1,
            }
        )
    return rows


def _render_categories(
    request: Request,
    access: WorkspaceAccess,
    conn: Connection,
    period: Period,
    *,
    confirm: int | None = None,
    focus_new: bool = False,
    error: str | None = None,
    new_name: str = "",
    renamed: tuple[int, str] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """The categories drawer. `confirm` asks about deleting that category
    in its row; `renamed` keeps a failed rename's text in its row."""
    context, flows, categories = _drawer_context(access, conn, period)
    rows = category_rows(flows, categories, context["view"]["colors"], period)
    for row in rows:
        if renamed is not None and row["id"] == renamed[0]:
            row["value"] = renamed[1]
            row["invalid"] = True
    return render(
        request,
        "cash_flow_categories.html",
        {
            **context,
            "rows": rows,
            "confirm": confirm,
            "focus_new": focus_new,
            "new_name": new_name,
            "form_error": error,
            "categories_url": _categories_url(access, period),
        },
        status_code=status_code,
    )


def _get_category(
    conn: Connection, access: WorkspaceAccess, category_id: int
) -> CashFlowCategory:
    category = repo.get_cash_flow_category(conn, access.workspace.id, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    return category


@router.get("/cash-flow-categories", response_class=HTMLResponse)
async def categories_page(
    request: Request,
    access: EditorAccess,
    per: str = "",
    confirm: int | None = None,
    add: bool = False,
):
    """`confirm` shows the delete confirmation in that category's row, so
    deleting works without JS; `add` puts focus in the new-name field."""
    period = parse_period(per)
    with get_connection_context() as conn:
        return _render_categories(
            request, access, conn, period, confirm=confirm, focus_new=add
        )


@router.post("/cash-flow-categories")
async def create_category_route(
    request: Request,
    access: EditorAccess,
    per: str = "",
    name: Annotated[str, Form()] = "",
):
    """Added last. Back to the drawer, ready for the next one."""
    period = parse_period(per)
    with get_connection_context() as conn:
        try:
            category = create_category(conn, access.workspace.id, name)
        except CashFlowError as e:
            return _render_categories(
                request,
                access,
                conn,
                period,
                focus_new=True,
                error=str(e),
                new_name=name,
                status_code=400,
            )
    set_flash(request, "success", f"Added {category.name}")
    return RedirectResponse(_categories_url(access, period, "&add=1"), status_code=303)


@router.post("/cash-flow-categories/{category_id}")
async def rename_category_route(
    request: Request,
    access: EditorAccess,
    category_id: int,
    per: str = "",
    name: Annotated[str, Form()] = "",
):
    period = parse_period(per)
    with get_connection_context() as conn:
        _get_category(conn, access, category_id)
        try:
            category = update_category(
                conn, access.workspace.id, category_id, name=name
            )
        except CashFlowError as e:
            return _render_categories(
                request,
                access,
                conn,
                period,
                error=str(e),
                renamed=(category_id, name),
                status_code=400,
            )
    set_flash(request, "success", f"Saved {category.name}")
    return RedirectResponse(_categories_url(access, period), status_code=303)


_STEPS = {"up": -1, "down": 1}


@router.post("/cash-flow-categories/{category_id}/move")
async def move_category_route(
    request: Request,
    access: EditorAccess,
    category_id: int,
    per: str = "",
    direction: Annotated[str, Form()] = "",
):
    """`direction` is up or down: one place in the order of the cards."""
    period = parse_period(per)
    if direction not in _STEPS:
        raise HTTPException(status_code=400, detail="Move up or down")
    with get_connection_context() as conn:
        category = _get_category(conn, access, category_id)
        move_category(conn, access.workspace.id, category_id, _STEPS[direction])
    set_flash(request, "success", f"Moved {category.name} {direction}")
    return RedirectResponse(_categories_url(access, period), status_code=303)


@router.post("/cash-flow-categories/{category_id}/delete")
async def delete_category_route(
    request: Request, access: EditorAccess, category_id: int, per: str = ""
):
    """Its cash flows become Uncategorized; nothing else is deleted."""
    period = parse_period(per)
    with get_connection_context() as conn:
        category = _get_category(conn, access, category_id)
        delete_category(conn, access.workspace.id, category_id)
    set_flash(request, "success", f"Deleted {category.name}")
    return RedirectResponse(_categories_url(access, period), status_code=303)
