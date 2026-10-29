"""The Accounts page's facts, unformatted: its sections and category groups,
the saved totals, the account drawer's formula inputs and retire state.

The JSON API (api_accounts.py) serves these and the React app formats them;
the MCP tools share `format_percent` and `formula_text`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from psycopg import Connection

from sensibility.accounts import retire_blocker, retire_warning
from sensibility.models import Account, AccountCategory, Record, RecordType

UNCATEGORIZED = "uncategorized"


def format_percent(rate: Decimal) -> str:
    """0.15 -> "15", 0.325 -> "32.5"."""
    text = f"{rate * 100:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def formula_text(account: Account, by_id: dict[int, Account]) -> str:
    """Human-readable formula, e.g. "15% × (Schwab + Fidelity − basis)"."""
    formula = account.formula
    if formula is None:
        return ""
    names = [by_id[i].name if i in by_id else f"account {i}" for i in account.input_ids]
    return f"{format_percent(formula.rate)}% × ({' + '.join(names)} − basis)"


def account_rows(accounts: list[Account], latest: list[Record]) -> list[dict[str, Any]]:
    """One dict per account for grouping and totals.

    `amount` is the account's value on the latest snapshot date, or None if it
    has no row on that date (new or just unretired).
    """
    amounts = {r.account_id: r.amount for r in latest}
    return [
        {
            "id": account.id,
            "name": account.name,
            "type": account.type.value,
            "category": account.category.value if account.category else None,
            "amount": amounts.get(account.id),
            "retired": not account.is_active,
        }
        for account in accounts
    ]


def saved_total(rows: list[dict[str, Any]]) -> Decimal:
    """Sum of the active rows' amounts on the latest snapshot date. The page
    recomputes every total live as amounts are staged; these are what it
    starts from."""
    return sum(
        (r["amount"] for r in rows if not r["retired"] and r["amount"] is not None),
        Decimal("0"),
    )


def category_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Split one section's rows under category subheadings.

    Categories come in AccountCategory order with Uncategorized last, and only
    those with rows appear. Row order within a group is preserved. `retired`
    marks a group whose rows are all retired, so it hides with them.
    """
    order = [(c.value, c.label) for c in AccountCategory]
    order.append((UNCATEGORIZED, "Uncategorized"))
    groups = []
    for key, label in order:
        members = [r for r in rows if (r["category"] or UNCATEGORIZED) == key]
        if members:
            groups.append(
                {
                    "key": key,
                    "label": label,
                    "rows": members,
                    "retired": all(r["retired"] for r in members),
                }
            )
    return groups


def accounts_view(
    accounts: list[Account], latest: list[Record], as_of: date
) -> dict[str, Any]:
    """The Accounts page: its rows, and the Assets and Liabilities sections
    with their category groups. `as_of` is today in the viewer's time zone."""
    rows = account_rows(accounts, latest)
    # Active rows first, retired rows last, alphabetical within each group
    rows.sort(key=lambda r: (r["retired"], r["name"].lower()))
    last_saved = latest[0].date if latest else None
    return {
        "rows": rows,
        "sections": [
            {
                "kind": kind,
                "title": title,
                "groups": category_groups([r for r in rows if r["type"] == kind]),
            }
            for kind, title in (("asset", "Assets"), ("liability", "Liabilities"))
        ],
        "retired_count": sum(1 for r in rows if r["retired"]),
        "snapshot_is_today": last_saved == as_of,
    }


def retire_state(
    conn: Connection, workspace_id: int, account: Account
) -> tuple[str | None, str | None]:
    """(blocker, warning) for the drawer's Retire button; both None when retired."""
    if not account.is_active:
        return None, None
    blocker = retire_blocker(conn, workspace_id, account)
    warning = None if blocker else retire_warning(conn, workspace_id, account)
    return blocker, warning


def candidate_groups(
    accounts: list[Account], exclude_id: int | None, amounts: dict[int, Decimal]
) -> list[tuple[str, list[dict[str, Any]]]]:
    """The drawer's formula inputs, under Assets and Liabilities (empty groups
    dropped): active, plain, not the account itself. Each carries its latest
    saved amount (None without one) for the live computed-value line."""
    candidates = [
        a for a in accounts if a.is_active and not a.is_computed and a.id != exclude_id
    ]
    groups = []
    for label, kind in (
        ("Assets", RecordType.ASSET),
        ("Liabilities", RecordType.LIABILITY),
    ):
        members = [
            {
                "id": c.id,
                "name": c.name,
                "amount": amounts[c.id] if c.id in amounts else None,
            }
            for c in candidates
            if c.type == kind
        ]
        if members:
            groups.append((label, members))
    return groups
