"""The Cash flows page's figures, unformatted.

`api_cash_flows` serializes them for the JSON API, and the React app
(frontend/src/routes/cash-flows.tsx) turns them into the page's text. Pure:
no database, no request.

Amounts are summed unrounded per year and rounded once per figure (to cents,
in the page's period), so a category's total is its flows' exact sum, not a
sum of rounded rows. Shares are of income and display-rounded text ("28%",
"<1%"); bar weights and the marker are unrounded percentages.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from sensibility.cashflows import (
    CategoryTotal,
    Period,
    category_totals,
    in_period,
    per_year,
    percent_text,
    share,
)
from sensibility.models import CashFlow, CashFlowCategory, CashFlowDirection

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


def expense_colors(groups: list[CategoryTotal]) -> list[str]:
    """One ramp color per group, in the groups' order, assigned by size."""
    by_size = sorted(range(len(groups)), key=lambda i: (groups[i].yearly, i))
    colors = [""] * len(groups)
    for rank, index in enumerate(by_size):
        colors[index] = EXPENSE_RAMP[min(rank, len(EXPENSE_RAMP) - 1)]
    return colors


def flow_in_period(flow: CashFlow, period: Period) -> Decimal:
    """One flow's amount per `period`, unsigned, rounded once to cents."""
    return in_period(abs(per_year(flow)), period)


def width(part: Decimal, whole: Decimal) -> str:
    """A slice's flex weight: its unrounded percentage of `whole`."""
    return f"{abs(part) * 100 / whole:.4f}"


class BarState(str, Enum):
    """What the "Where income goes" bar measures against."""

    NORMAL = "normal"  # 100% is income
    OVER = "over"  # expenses exceed income: 100% is all expenses
    NO_INCOME = "no_income"  # no bar


@dataclass(frozen=True)
class Slice:
    """One piece of the bar: an expense category, or what is left over."""

    label: str
    color: str
    weight: str  # unrounded percentage of the bar
    amount: Decimal  # per period, unsigned
    share: str | None  # of income, display-rounded
    category: CashFlowCategory | None  # None for Uncategorized and Left over
    left_over: bool = False


@dataclass(frozen=True)
class Card:
    """Income, or one expense category with flows (Uncategorized last)."""

    direction: CashFlowDirection
    category: CashFlowCategory | None  # None for Income and Uncategorized
    name: str
    color: str
    total: Decimal  # per period, unsigned
    share: str | None  # an expense card's share of income; None without income
    flows: tuple[CashFlow, ...]


@dataclass(frozen=True)
class CashFlowsFigures:
    period: Period
    empty: bool
    income: Decimal  # per period
    expenses: Decimal  # per period, unsigned
    net: Decimal  # per period, signed: negative when short
    expenses_share: str | None
    # The headline's second figure: the net over a year, or over a month
    # when the page already shows a year.
    other_period: Period
    other_net: Decimal
    estimates: int
    bar_state: BarState
    slices: tuple[Slice, ...]
    over_by: Decimal | None  # -net, when net is negative
    over_share: str | None  # over income: how far, as a share of income
    marker: str | None  # over income: where income runs out on the bar
    cards: tuple[Card, ...]
    # Each expense category's color on this page, by category id (None for
    # Uncategorized), so the drawers can match it.
    colors: dict[int | None, str]

    @property
    def short(self) -> bool:
        """The headline reads "Short each …" rather than "Left over each …"."""
        return self.bar_state == BarState.OVER


def cash_flows_figures(
    flows: list[CashFlow], categories: list[CashFlowCategory], period: Period
) -> CashFlowsFigures:
    """Everything the Cash flows page shows, for one period, unformatted."""
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
        bar_state = BarState.NO_INCOME
    elif net < 0:
        bar_state = BarState.OVER
    else:
        bar_state = BarState.NORMAL
    slices: list[Slice] = []
    if bar_state != BarState.NO_INCOME:
        whole = income if bar_state == BarState.NORMAL else -expenses
        for group, color in zip(groups, colors):
            if group.yearly:
                slices.append(
                    Slice(
                        label=group.name,
                        color=color,
                        weight=width(group.yearly, whole),
                        amount=in_period(-group.yearly, period),
                        share=share_text(group.yearly),
                        category=group.category,
                    )
                )
        if bar_state == BarState.NORMAL and net > 0:
            slices.append(
                Slice(
                    label="Left over",
                    color=LEFTOVER_COLOR,
                    weight=width(net, whole),
                    amount=in_period(net, period),
                    share=share_text(net),
                    category=None,
                    left_over=True,
                )
            )

    income_card = Card(
        direction=CashFlowDirection.INCOME,
        category=None,
        name="Income",
        color=INCOME_COLOR,
        total=in_period(income, period),
        share=None,
        flows=tuple(incomes),
    )
    expense_cards = [
        Card(
            direction=CashFlowDirection.EXPENSE,
            category=group.category,
            name=group.name,
            color=color,
            total=in_period(-group.yearly, period),
            share=share_text(group.yearly),
            flows=group.flows,
        )
        for group, color in zip(groups, colors)
    ]

    other = Period.MONTH if period == Period.YEAR else Period.YEAR
    over = bar_state == BarState.OVER
    return CashFlowsFigures(
        period=period,
        empty=not flows,
        income=in_period(income, period),
        expenses=in_period(-expenses, period),
        net=in_period(net, period),
        expenses_share=share_text(expenses),
        other_period=other,
        other_net=in_period(net, other),
        estimates=sum(1 for f in flows if f.is_estimate),
        bar_state=bar_state,
        slices=tuple(slices),
        over_by=in_period(-net, period) if net < 0 else None,
        # Over income (board AA): the bar is all expenses, and the marker is
        # where income runs out on it, unrounded like the slices' widths;
        # the share it is over by is of income, display-rounded.
        over_share=share_text(net) if over else None,
        marker=width(income, -expenses) if over else None,
        cards=(income_card, *expense_cards),
        colors={
            (group.category.id if group.category else None): color
            for group, color in zip(groups, colors)
        },
    )


# --- the categories drawer ----------------------------------------------------


@dataclass(frozen=True)
class CategoryFigures:
    """One category's row in the categories drawer."""

    category: CashFlowCategory
    color: str
    count: int  # its flows, income and expense
    expenses: Decimal | None  # per period, unsigned; None with no expenses
    income: Decimal | None  # per period; None with no income


def category_figures(
    flows: list[CashFlow],
    categories: list[CashFlowCategory],
    colors: dict[int | None, str],
    period: Period,
) -> list[CategoryFigures]:
    """Every category in display order, with its color on the page (from
    `colors`; else blue if it holds only income, else the empty color) and
    what its flows come to. Income in a category is kept apart from its
    expenses."""

    def total(members: list[CashFlow]) -> Decimal | None:
        """Unsigned, per period; None when there are none."""
        if not members:
            return None
        return in_period(abs(sum((per_year(f) for f in members), Decimal(0))), period)

    rows = []
    # Display order, as category_totals orders the cards.
    for category in sorted(categories, key=lambda c: (c.position, c.id)):
        members = [f for f in flows if f.category_id == category.id]
        expenses = [f for f in members if f.direction == CashFlowDirection.EXPENSE]
        incomes = [f for f in members if f.direction == CashFlowDirection.INCOME]
        if category.id in colors:
            color = colors[category.id]
        elif incomes:
            color = INCOME_COLOR
        else:
            color = EMPTY_CATEGORY_COLOR
        rows.append(
            CategoryFigures(
                category=category,
                color=color,
                count=len(members),
                expenses=total(expenses),
                income=total(incomes),
            )
        )
    return rows
