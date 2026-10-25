"""Cash flows: recurring income and expenses, and what they come to.

The rate functions at the top are pure. The rest is the service layer: it
raises CashFlowError with a message that is safe to show the user, and
commits on success.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
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


# --- service ---------------------------------------------------------------


class CashFlowError(ValueError):
    """A rule violation with a user-facing message."""


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
        raise CashFlowError(f"Cash flow {cash_flow_id} does not exist")
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
        raise CashFlowError(f"Cash flow {cash_flow_id} does not exist")
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
        raise CashFlowError(f"Category {category_id} does not exist")
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


def delete_category(conn: Connection, workspace_id: int, category_id: int) -> None:
    """Its cash flows become uncategorized (the foreign key nulls them)."""
    if not repo.delete_cash_flow_category(conn, workspace_id, category_id):
        raise CashFlowError(f"Category {category_id} does not exist")
    conn.commit()
