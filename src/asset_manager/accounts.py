"""Account rules and the snapshot save transaction.

Everything here raises AccountError with a message that is safe to show the
user. Functions commit on success.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal, InvalidOperation

from psycopg import Connection

from . import repository as repo
from .formulas import MissingValueError, compute_snapshot, quantize_cents
from .models import Account, Formula, RecordType


class AccountError(ValueError):
    """A rule violation with a user-facing message."""


def parse_amount(text: str) -> Decimal:
    """Parse "$1,234.56", "-17.44", or "(17.44)" into a Decimal with two places."""
    cleaned = text.replace("$", "").replace(",", "").replace(" ", "").strip()
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    if negative:
        cleaned = cleaned[1:-1]
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        raise AccountError(f"{text.strip()!r} is not a number") from None
    if not amount.is_finite():
        raise AccountError(f"{text.strip()!r} is not a number")
    return quantize_cents(-amount if negative else amount)


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise AccountError("Name is required")
    return cleaned


def _get_or_error(conn: Connection, account_id: int) -> Account:
    account = repo.get_account(conn, account_id)
    if account is None:
        raise AccountError(f"Account {account_id} does not exist")
    return account


def _check_name_free(
    conn: Connection, type: RecordType, name: str, *, except_id: int | None = None
) -> None:
    other = repo.get_account_by_name(conn, type, name)
    if other is not None and other.id != except_id:
        raise AccountError(f"A {type.value} named {name!r} already exists")


def _validate_inputs(
    conn: Connection,
    account_id: int | None,
    formula: Formula | None,
    input_ids: Iterable[int],
) -> list[int]:
    if formula is None:
        return []
    ids = sorted(set(input_ids))
    if not ids:
        raise AccountError("A computed account needs at least one input")
    for input_id in ids:
        if input_id == account_id:
            raise AccountError("An account cannot be its own input")
        candidate = repo.get_account(conn, input_id)
        if candidate is None:
            raise AccountError(f"Input account {input_id} does not exist")
        if not candidate.is_active:
            raise AccountError(f"{candidate.name} is retired and cannot be an input")
        if candidate.is_computed:
            raise AccountError(f"{candidate.name} is computed and cannot be an input")
    return ids


def _dependents_message(account: Account, dependents: list[Account]) -> str:
    names = ", ".join(d.name for d in dependents)
    return f"{account.name} is an input to {names}"


def create_account(
    conn: Connection,
    name: str,
    type: RecordType,
    formula: Formula | None = None,
    input_ids: Iterable[int] = (),
) -> Account:
    name = _clean_name(name)
    _check_name_free(conn, type, name)
    ids = _validate_inputs(conn, None, formula, input_ids)
    account = repo.insert_account(
        conn, Account(name=name, type=type, formula=formula, input_ids=ids)
    )
    conn.commit()
    return account


def update_account(
    conn: Connection,
    account_id: int,
    name: str,
    formula: Formula | None = None,
    input_ids: Iterable[int] = (),
) -> Account:
    existing = _get_or_error(conn, account_id)
    name = _clean_name(name)
    _check_name_free(conn, existing.type, name, except_id=account_id)
    if formula is not None:
        dependents = repo.get_dependents(conn, account_id)
        if dependents:
            raise AccountError(
                f"{_dependents_message(existing, dependents)} and cannot be computed"
            )
    ids = _validate_inputs(conn, account_id, formula, input_ids)
    updated = existing.model_copy(
        update={"name": name, "formula": formula, "input_ids": ids}
    )
    repo.update_account(conn, updated)
    conn.commit()
    return updated


def retire_blocker(conn: Connection, account: Account) -> str | None:
    """Why this account cannot be retired right now, or None if it can."""
    if account.id is None:
        return "Account has not been saved"
    latest = repo.get_latest_amount(conn, account.id)
    if latest is not None and latest != 0:
        return (
            f"{account.name} was ${latest:,.2f} in its latest snapshot. "
            "Set it to zero and save before retiring."
        )
    dependents = repo.get_dependents(conn, account.id)
    if dependents:
        return (
            f"{_dependents_message(account, dependents)}. Retire or edit those first."
        )
    return None


def retire_account(conn: Connection, account_id: int, on: date) -> Account:
    account = _get_or_error(conn, account_id)
    if not account.is_active:
        raise AccountError(f"{account.name} is already retired")
    blocker = retire_blocker(conn, account)
    if blocker is not None:
        raise AccountError(blocker)
    repo.set_retired_at(conn, account_id, on)
    conn.commit()
    return account.model_copy(update={"retired_at": on})


def unretire_account(conn: Connection, account_id: int) -> Account:
    account = _get_or_error(conn, account_id)
    if account.is_active:
        raise AccountError(f"{account.name} is not retired")
    repo.set_retired_at(conn, account_id, None)
    conn.commit()
    return account.model_copy(update={"retired_at": None})


def save_snapshot(
    conn: Connection,
    values: dict[int, Decimal],
    cost_bases: dict[int, Decimal],
    as_of: date,
) -> int:
    """Write a complete snapshot for `as_of`: every active account gets a row.

    `values` must hold an amount for every active plain account. `cost_bases`
    updates the formula document of computed accounts before evaluation.
    All or nothing.
    """
    try:
        with conn.transaction():
            accounts = repo.get_accounts(conn, include_retired=False)
            by_id = {a.id: a for a in accounts if a.id is not None}

            for account_id, amount in values.items():
                account = by_id.get(account_id)
                if account is None:
                    raise AccountError(f"Account {account_id} is not an active account")
                if account.is_computed:
                    raise AccountError(
                        f"{account.name} is computed and cannot be set directly"
                    )
                if not amount.is_finite():
                    raise AccountError(f"{account.name} has an invalid amount")

            for account_id, basis in cost_bases.items():
                account = by_id.get(account_id)
                if account is None or account.formula is None:
                    raise AccountError(
                        f"Account {account_id} is not an active computed account"
                    )
                if not basis.is_finite():
                    raise AccountError(f"{account.name} has an invalid cost basis")
                formula = account.formula.model_copy(
                    update={"cost_basis": quantize_cents(basis)}
                )
                repo.set_formula(conn, account_id, formula)
                by_id[account_id] = account.model_copy(update={"formula": formula})

            amounts = compute_snapshot(list(by_id.values()), values, as_of)
            return repo.upsert_amounts(conn, as_of, amounts)
    except MissingValueError as e:
        raise AccountError(str(e)) from e
