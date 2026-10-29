"""Cash flows: recurring income and expenses, and what they come to.

The rate functions at the top are pure. The rest is the service layer: it
raises CashFlowError with a message that is safe to show the user, and
commits on success.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import Enum
from typing import Any

from psycopg import Connection, errors

from . import repository as repo
from .accounts import MAX_AMOUNT
from .formulas import quantize_cents
from .models import (
    CashFlow,
    CashFlowCategory,
    CashFlowDirection,
    FrequencyUnit,
)

DAYS_PER_YEAR = Decimal(365)
MONTHS_PER_YEAR = Decimal(12)
# Occurrences per year of "every 1 unit", as an exact fraction. 365/7 does
# not terminate, so dividing early would make "every 2 weeks" and "every 14
# days" differ in the last digit; per_year divides once, at the end.
_PER_YEAR_FRACTION = {
    FrequencyUnit.DAY: (365, 1),
    FrequencyUnit.WEEK: (365, 7),
    FrequencyUnit.MONTH: (12, 1),
    FrequencyUnit.YEAR: (1, 1),
}
MAX_EVERY = 1000


# --- rates (pure) ----------------------------------------------------------


def per_year(flow: CashFlow) -> Decimal:
    """Unrounded yearly amount, signed: income positive, expense negative.

    "Every 1 month" is 12 a year, so per-day is amount × 12 / 365: the
    sheet's 30.4166… days per month, exactly.
    """
    numerator, denominator = _PER_YEAR_FRACTION[flow.unit]
    yearly = flow.amount * numerator / (denominator * flow.every)
    return yearly if flow.direction == CashFlowDirection.INCOME else -yearly


def rates(yearly: Decimal) -> dict[str, str]:
    """A signed yearly amount as per-day, per-month and per-year, in cents."""
    return {
        "per_day": str(quantize_cents(yearly / DAYS_PER_YEAR)),
        "per_month": str(quantize_cents(yearly / MONTHS_PER_YEAR)),
        "per_year": str(quantize_cents(yearly)),
    }


def totals(flows: Iterable[CashFlow]) -> dict[str, dict[str, str]]:
    """Income, expenses and net, each summed unrounded and rounded once."""
    income = Decimal(0)
    expenses = Decimal(0)
    for flow in flows:
        yearly = per_year(flow)
        if flow.direction == CashFlowDirection.INCOME:
            income += yearly
        else:
            expenses += yearly
    return {
        "income": rates(income),
        "expenses": rates(expenses),
        "net": rates(income + expenses),
    }


# --- per category and per period (pure) ------------------------------------


@dataclass(frozen=True)
class CategoryTotal:
    """One expense category's flows and their unrounded, signed yearly sum.

    `category` is None for Uncategorized.
    """

    category: CashFlowCategory | None
    flows: tuple[CashFlow, ...]
    yearly: Decimal

    @property
    def name(self) -> str:
        return self.category.name if self.category else "Uncategorized"


def category_totals(
    flows: Iterable[CashFlow], categories: Iterable[CashFlowCategory]
) -> list[CategoryTotal]:
    """Expense flows grouped by category, summed unrounded like totals().

    Every category comes in `position` order (empty ones too), then
    Uncategorized if any expense has no category. An expense naming a
    category not in `categories` counts as Uncategorized, so the groups
    always add up to totals()'s expenses. Income flows are left out.
    """
    ordered = sorted(categories, key=lambda c: (c.position, c.id))
    grouped: dict[int | None, list[CashFlow]] = {c.id: [] for c in ordered}
    grouped[None] = []
    for flow in flows:
        if flow.direction != CashFlowDirection.EXPENSE:
            continue
        key = flow.category_id if flow.category_id in grouped else None
        grouped[key].append(flow)

    def total(members: list[CashFlow]) -> Decimal:
        return sum((per_year(f) for f in members), Decimal(0))

    result = [
        CategoryTotal(c, tuple(grouped[c.id]), total(grouped[c.id])) for c in ordered
    ]
    if grouped[None]:
        result.append(CategoryTotal(None, tuple(grouped[None]), total(grouped[None])))
    return result


class Period(str, Enum):
    """What the Cash flows page shows amounts per."""

    DAY = "day"
    MONTH = "month"
    YEAR = "year"


DEFAULT_PERIOD = Period.MONTH
_PERIODS_PER_YEAR = {
    Period.DAY: DAYS_PER_YEAR,
    Period.MONTH: MONTHS_PER_YEAR,
    Period.YEAR: Decimal(1),
}


def parse_period(value: str | None) -> Period:
    """The `?per=` value as a Period; anything unknown is the default."""
    try:
        return Period(value)
    except ValueError:
        return DEFAULT_PERIOD


def in_period(yearly: Decimal, period: Period) -> Decimal:
    """An unrounded yearly amount per `period`, rounded once to cents."""
    return quantize_cents(yearly / _PERIODS_PER_YEAR[period])


def share(part: Decimal, whole: Decimal) -> Decimal | None:
    """|part| as an unrounded fraction of `whole`; None when whole is not
    positive, so there is never a division by zero."""
    if whole <= 0:
        return None
    return abs(part) / whole


def percent_text(fraction: Decimal) -> str:
    """0.2845 -> "28%". A share too small to round to 1% but not zero is
    "<1%", so a real expense never reads as nothing."""
    percent = (fraction * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    if percent == 0 and fraction > 0:
        return "<1%"
    return f"{percent}%"


def every_text(every: int, unit: FrequencyUnit) -> str:
    """ "every month", "every 2 weeks": the plural only when every > 1."""
    if every == 1:
        return f"every {unit.value}"
    return f"every {every} {unit.value}s"


# --- service ---------------------------------------------------------------


class CashFlowError(ValueError):
    """A rule violation with a user-facing message."""


class CashFlowNotFound(CashFlowError):
    """The cash flow or category acted on is not in this workspace (the
    API's 404). A category named in a flow's fields is a CashFlowError."""


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise CashFlowError("Name is required")
    return cleaned


def _clean_description(description: str | None) -> str | None:
    if description is None:
        return None
    return description.strip() or None


def _clean_amount(amount: Decimal) -> Decimal:
    try:
        if not amount.is_finite():
            raise CashFlowError("Amount must be a number")
        if amount < 0:
            raise CashFlowError(
                "Amount cannot be negative; set the direction to expense instead"
            )
        if amount >= MAX_AMOUNT:
            raise CashFlowError("Amount is too large")
        return quantize_cents(amount)
    except InvalidOperation:
        raise CashFlowError("Amount must be a number") from None


def _check_every(every: int) -> int:
    if not 1 <= every <= MAX_EVERY:
        raise CashFlowError(f"Every must be between 1 and {MAX_EVERY}")
    return every


def _check_category(
    conn: Connection, workspace_id: int, category_id: int | None
) -> int | None:
    if (
        category_id is not None
        and repo.get_cash_flow_category(conn, workspace_id, category_id) is None
    ):
        raise CashFlowError(f"Category {category_id} does not exist")
    return category_id


def _validated(conn: Connection, workspace_id: int, flow: CashFlow) -> CashFlow:
    return flow.model_copy(
        update={
            "name": _clean_name(flow.name),
            "amount": _clean_amount(flow.amount),
            "every": _check_every(flow.every),
            "category_id": _check_category(conn, workspace_id, flow.category_id),
            "description": _clean_description(flow.description),
        }
    )


def _name_taken(name: str) -> CashFlowError:
    return CashFlowError(f"A cash flow named {name!r} already exists")


def create_cash_flow(conn: Connection, workspace_id: int, flow: CashFlow) -> CashFlow:
    flow = _validated(conn, workspace_id, flow)
    try:
        with conn.transaction():
            created = repo.insert_cash_flow(conn, workspace_id, flow)
    except errors.UniqueViolation:
        raise _name_taken(flow.name) from None
    conn.commit()
    return created


def update_cash_flow(
    conn: Connection, workspace_id: int, cash_flow_id: int, changes: dict[str, Any]
) -> CashFlow:
    """Apply `changes` (field name to new value) to one cash flow."""
    existing = repo.get_cash_flow(conn, workspace_id, cash_flow_id)
    if existing is None:
        raise CashFlowNotFound(f"Cash flow {cash_flow_id} does not exist")
    flow = _validated(conn, workspace_id, existing.model_copy(update=changes))
    try:
        with conn.transaction():
            repo.update_cash_flow(conn, workspace_id, flow)
    except errors.UniqueViolation:
        raise _name_taken(flow.name) from None
    conn.commit()
    updated = repo.get_cash_flow(conn, workspace_id, cash_flow_id)
    assert updated is not None
    return updated


def delete_cash_flow(conn: Connection, workspace_id: int, cash_flow_id: int) -> None:
    if not repo.delete_cash_flow(conn, workspace_id, cash_flow_id):
        raise CashFlowNotFound(f"Cash flow {cash_flow_id} does not exist")
    conn.commit()


def create_category(conn: Connection, workspace_id: int, name: str) -> CashFlowCategory:
    """Added after the existing categories."""
    name = _clean_name(name)
    try:
        with conn.transaction():
            category = repo.insert_cash_flow_category(conn, workspace_id, name)
    except errors.UniqueViolation:
        raise CashFlowError(f"A category named {name!r} already exists") from None
    conn.commit()
    return category


def update_category(
    conn: Connection,
    workspace_id: int,
    category_id: int,
    *,
    name: str | None = None,
    position: int | None = None,
) -> CashFlowCategory:
    existing = repo.get_cash_flow_category(conn, workspace_id, category_id)
    if existing is None:
        raise CashFlowNotFound(f"Category {category_id} does not exist")
    updated = existing.model_copy(
        update={
            "name": existing.name if name is None else _clean_name(name),
            "position": existing.position if position is None else position,
        }
    )
    try:
        with conn.transaction():
            repo.update_cash_flow_category(conn, updated)
    except errors.UniqueViolation:
        raise CashFlowError(
            f"A category named {updated.name!r} already exists"
        ) from None
    conn.commit()
    return updated


def move_category(
    conn: Connection, workspace_id: int, category_id: int, step: int
) -> CashFlowCategory:
    """Move one place up (step -1) or down (step 1) in display order.

    Swaps with the neighbour and renumbers every category 0, 1, 2, ... so
    tied or gapped positions (the API can set any) come out tidy. At either
    end nothing moves.
    """
    if step not in (-1, 1):
        raise CashFlowError("A category moves one place at a time")
    ordered = repo.get_cash_flow_categories(conn, workspace_id)
    index = next((i for i, c in enumerate(ordered) if c.id == category_id), None)
    if index is None:
        raise CashFlowNotFound(f"Category {category_id} does not exist")
    target = index + step
    if 0 <= target < len(ordered):
        ordered[index], ordered[target] = ordered[target], ordered[index]
    with conn.transaction():
        for position, category in enumerate(ordered):
            if category.position != position:
                repo.update_cash_flow_category(
                    conn, category.model_copy(update={"position": position})
                )
    conn.commit()
    moved = next(c for c in ordered if c.id == category_id)
    return moved.model_copy(update={"position": ordered.index(moved)})


def delete_category(conn: Connection, workspace_id: int, category_id: int) -> None:
    """Its cash flows become uncategorized (the foreign key nulls them)."""
    if not repo.delete_cash_flow_category(conn, workspace_id, category_id):
        raise CashFlowNotFound(f"Category {category_id} does not exist")
    conn.commit()
