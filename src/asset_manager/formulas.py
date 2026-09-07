"""Evaluate account formulas. Pure functions, no database access."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from .models import Account, Formula, ProportionalFormula

CENTS = Decimal("0.01")


def quantize_cents(amount: Decimal) -> Decimal:
    return amount.quantize(CENTS, rounding=ROUND_HALF_UP)


class MissingValueError(ValueError):
    """A plain account that a snapshot needs has no value."""

    def __init__(self, account_name: str) -> None:
        self.account_name = account_name
        super().__init__(f"Missing value for {account_name}")


def compute_snapshot(
    accounts: list[Account],
    values: dict[int, Decimal],
    as_of: date,
) -> dict[int, Decimal]:
    """Return the amount for every account.

    Args:
        accounts: the active accounts, plain and computed.
        values: the amount for every active plain account, keyed by id.
        as_of: the snapshot date. Unused by the proportional kind; a
            time-driven kind would need it.

    Raises MissingValueError if a plain account or a formula input has no value.
    """
    by_id = {a.id: a for a in accounts if a.id is not None}
    result: dict[int, Decimal] = {}
    for account in accounts:
        if account.id is None:
            raise ValueError(f"Account {account.name!r} has no id")
        if account.formula is None:
            if account.id not in values:
                raise MissingValueError(account.name)
            result[account.id] = quantize_cents(values[account.id])
        else:
            result[account.id] = _evaluate(
                account, account.formula, values, by_id, as_of
            )
    return result


def _evaluate(
    account: Account,
    formula: Formula,
    values: dict[int, Decimal],
    by_id: dict[int, Account],
    as_of: date,
) -> Decimal:
    if isinstance(formula, ProportionalFormula):
        total = Decimal("0")
        for input_id in account.input_ids:
            if input_id not in values:
                name = (
                    by_id[input_id].name if input_id in by_id else f"account {input_id}"
                )
                raise MissingValueError(name)
            total += values[input_id]
        return quantize_cents(formula.rate * (total - formula.cost_basis))
    raise TypeError(f"Unsupported formula kind: {formula.kind}")
