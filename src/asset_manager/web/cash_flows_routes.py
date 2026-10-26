"""The Cash flows page: where income goes, per day, month or year.

Read-only for now; the forms for adding and editing come later. The JSON API
(`/api/workspaces/{id}/cash-flows`) already does the writes.
"""

from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from asset_manager import repository as repo
from asset_manager.cashflows import (
    CategoryTotal,
    Period,
    category_totals,
    every_text,
    in_period,
    parse_period,
    per_year,
    percent_text,
    share,
)
from asset_manager.db import get_connection_context
from asset_manager.models import CashFlow, CashFlowCategory, CashFlowDirection

from .access import ViewerAccess, shell_context
from .rendering import render

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/workspaces/{workspace_id}")

INCOME_COLOR = "var(--asset)"
LEFTOVER_COLOR = "var(--leftover)"
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
    }


# --- page ------------------------------------------------------------------


@router.get("/cash-flows", response_class=HTMLResponse)
async def cash_flows_page(request: Request, access: ViewerAccess, per: str = ""):
    """Render the Cash flows page. `per` is day, month (the default) or year."""
    period = parse_period(per)
    shell = shell_context(access, request.url.path)
    context: dict[str, Any] = {
        **shell,
        "active_tab": "cash_flows",
        "periods": [
            (p.value.title(), f"{request.url.path}?per={p.value}", p == period)
            for p in Period
        ],
    }
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
