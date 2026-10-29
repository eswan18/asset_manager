"""JSON for the Cash flows page: everything it renders, and moving a category.

The overview is `cash_flows_model.cash_flows_figures`, the same computation
the Jinja page formats, so the two can't drift. Money is a string with two
decimals ("1215.48"; only `net` and `other_net` can be negative); shares are
display text ("28%", "<1%"); bar weights and the marker are unrounded
percentages; colors are CSS values naming the design tokens
("var(--liability-2)"), as the page uses them.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from sensibility import repository as repo
from sensibility.cashflows import Period, every_text, move_category, parse_period
from sensibility.db import get_connection_context
from sensibility.formulas import quantize_cents
from sensibility.models import (
    CashFlow,
    CashFlowCategory,
    CashFlowDirection,
    FrequencyUnit,
    Role,
)

from .access import EditorAccess, ViewerAccess
from .cash_flows_model import (
    EXPENSE_RAMP,
    INCOME_COLOR,
    BarState,
    Card,
    Slice,
    cash_flows_figures,
    category_figures,
    flow_in_period,
)

router = APIRouter(prefix="/api/workspaces/{workspace_id}")


def cents(amount: Decimal) -> str:
    """Two decimals, and never "-0.00"."""
    rounded = quantize_cents(amount)
    return str(rounded if rounded else abs(rounded))


def _cents_or_none(amount: Decimal | None) -> str | None:
    return None if amount is None else cents(amount)


# --- response models -----------------------------------------------------------


class FlowRowOut(BaseModel):
    """A cash flow as a card lists it, with every field its drawer edits."""

    id: int
    name: str
    direction: CashFlowDirection
    amount: str = Field(description="Each time it happens, as entered")
    every: int
    unit: FrequencyUnit
    every_text: str = Field(description='"every month", "every 2 weeks"')
    per_period: str = Field(description="Unsigned, in the overview's period")
    category_id: int | None
    description: str | None
    is_estimate: bool


class CardOut(BaseModel):
    """Income first, then each expense category with flows in position
    order, then Uncategorized."""

    direction: CashFlowDirection
    category_id: int | None = Field(description="None for Income and Uncategorized")
    name: str
    color: str
    total: str = Field(description="Unsigned, in the overview's period")
    share: str | None = Field(
        description="An expense card's share of income; None for Income or "
        "when there is no income to compare"
    )
    flows: list[FlowRowOut]


class SliceOut(BaseModel):
    """One piece of the "Where income goes" bar, in order."""

    label: str
    color: str
    weight: str = Field(description="Unrounded percentage of the bar's width")
    amount: str = Field(description="Unsigned, in the overview's period")
    share: str | None = Field(description="Of income, display-rounded")
    category_id: int | None = Field(description="None for Uncategorized and Left over")
    left_over: bool


class CategoryRowOut(BaseModel):
    """A category as the drawers show it, in display order."""

    id: int
    name: str
    position: int
    color: str = Field(
        description="The categories drawer's swatch: its expense color on the "
        "page, else income's if it holds only income, else the empty color"
    )
    expense_color: str = Field(
        description="The cash flow drawer's color for an expense in it"
    )
    flow_count: int
    expenses: str | None = Field(description="Its expenses per period, if any")
    income: str | None = Field(description="Its income per period, if any")


class CashFlowsOverview(BaseModel):
    period: Period
    can_edit: bool
    empty: bool = Field(description="No cash flows at all")
    short: bool = Field(
        description='The headline reads "Short each {period}" (expenses exceed '
        'income) rather than "Left over each {period}"'
    )
    net: str = Field(description="Income minus expenses; negative when short")
    income: str
    expenses: str
    expenses_share: str | None = Field(description="Expenses as a share of income")
    other_period: Period = Field(
        description="The headline's second figure: year, or month when the "
        "period is year"
    )
    other_net: str = Field(description="The net in other_period, in cents")
    estimates: int = Field(description="How many flows are estimates")
    bar_state: BarState
    slices: list[SliceOut]
    over_by: str | None = Field(description="How far expenses exceed income")
    over_share: str | None = Field(
        description="Over income: over_by as a share of income"
    )
    marker: str | None = Field(
        description="Over income: where income runs out, as an unrounded "
        "percentage of the (all-expenses) bar"
    )
    cards: list[CardOut]
    categories: list[CategoryRowOut]
    income_color: str
    uncategorized_color: str = Field(
        description="The cash flow drawer's color for an uncategorized expense"
    )


class CategoryOut(BaseModel):
    id: int
    name: str
    position: int


class CategoriesOut(BaseModel):
    categories: list[CategoryOut]


class CategoryMove(BaseModel):
    direction: Literal["up", "down"]


# --- conversions ---------------------------------------------------------------


def _flow_out(flow: CashFlow, period: Period) -> FlowRowOut:
    assert flow.id is not None
    return FlowRowOut(
        id=flow.id,
        name=flow.name,
        direction=flow.direction,
        amount=cents(flow.amount),
        every=flow.every,
        unit=flow.unit,
        every_text=every_text(flow.every, flow.unit),
        per_period=cents(flow_in_period(flow, period)),
        category_id=flow.category_id,
        description=flow.description,
        is_estimate=flow.is_estimate,
    )


def _card_out(card: Card, period: Period) -> CardOut:
    return CardOut(
        direction=card.direction,
        category_id=card.category.id if card.category else None,
        name=card.name,
        color=card.color,
        total=cents(card.total),
        share=card.share,
        flows=[_flow_out(f, period) for f in card.flows],
    )


def _slice_out(piece: Slice) -> SliceOut:
    return SliceOut(
        label=piece.label,
        color=piece.color,
        weight=piece.weight,
        amount=cents(piece.amount),
        share=piece.share,
        category_id=piece.category.id if piece.category else None,
        left_over=piece.left_over,
    )


def cash_flows_overview(
    flows: list[CashFlow],
    categories: list[CashFlowCategory],
    period: Period,
    *,
    can_edit: bool,
) -> CashFlowsOverview:
    figures = cash_flows_figures(flows, categories, period)
    colors = figures.colors
    return CashFlowsOverview(
        period=period,
        can_edit=can_edit,
        empty=figures.empty,
        short=figures.short,
        net=cents(figures.net),
        income=cents(figures.income),
        expenses=cents(figures.expenses),
        expenses_share=figures.expenses_share,
        other_period=figures.other_period,
        other_net=cents(figures.other_net),
        estimates=figures.estimates,
        bar_state=figures.bar_state,
        slices=[_slice_out(s) for s in figures.slices],
        over_by=_cents_or_none(figures.over_by),
        over_share=figures.over_share,
        marker=figures.marker,
        cards=[_card_out(c, period) for c in figures.cards],
        categories=[
            CategoryRowOut(
                id=row.category.id,
                name=row.category.name,
                position=row.category.position,
                color=row.color,
                expense_color=colors.get(row.category.id, EXPENSE_RAMP[0]),
                flow_count=row.count,
                expenses=_cents_or_none(row.expenses),
                income=_cents_or_none(row.income),
            )
            for row in category_figures(flows, categories, colors, period)
        ],
        income_color=INCOME_COLOR,
        uncategorized_color=colors.get(None, EXPENSE_RAMP[0]),
    )


# --- routes ----------------------------------------------------------------------


@router.get("/cash-flows/overview")
async def cash_flows_overview_route(
    access: ViewerAccess,
    per: str = Query(
        "",
        description="day, month or year; anything else is month (as on the page)",
    ),
) -> CashFlowsOverview:
    """Everything the Cash flows page renders, for one period."""
    with get_connection_context() as conn:
        flows = repo.get_cash_flows(conn, access.workspace.id)
        categories = repo.get_cash_flow_categories(conn, access.workspace.id)
    return cash_flows_overview(
        flows,
        categories,
        parse_period(per),
        can_edit=access.role.allows(Role.EDITOR),
    )


_STEPS = {"up": -1, "down": 1}


@router.post("/cash-flow-categories/{category_id}/move")
async def move_category_route(
    category_id: int, payload: CategoryMove, access: EditorAccess
) -> CategoriesOut:
    """One place up or down in display order (the cards' order). At either
    end nothing moves. Returns every category in its new order, positions
    renumbered 0, 1, 2, …"""
    workspace_id = access.workspace.id
    with get_connection_context() as conn:
        if repo.get_cash_flow_category(conn, workspace_id, category_id) is None:
            raise HTTPException(status_code=404, detail="Category not found")
        move_category(conn, workspace_id, category_id, _STEPS[payload.direction])
        categories = repo.get_cash_flow_categories(conn, workspace_id)
    return CategoriesOut(
        categories=[
            CategoryOut(id=c.id, name=c.name, position=c.position) for c in categories
        ]
    )
