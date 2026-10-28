"""Pieces shared by the page-model API modules (api_dashboard, api_accounts).

Money is a decimal string with two places ("12400.00", "-17.44"), as in the
MCP results; dates are ISO dates. Clients format both for display.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from sensibility.formulas import quantize_cents
from sensibility.models import AccountCategory

Money = str

UNCATEGORIZED_KEY = "uncategorized"
UNCATEGORIZED_LABEL = "Uncategorized"


class ErrorOut(BaseModel):
    """Every API error body: a message fit to show the user."""

    error: str


def responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI entries for the error statuses a route can answer."""
    return {code: {"model": ErrorOut} for code in codes}


def money(amount: Decimal) -> Money:
    """Two decimal places: "12400.00"."""
    return str(quantize_cents(amount))


def maybe_money(amount: Decimal | None) -> Money | None:
    return None if amount is None else money(amount)


def category_key(category: AccountCategory | None) -> str:
    """An account category's key: its value, or "uncategorized"."""
    return category.value if category is not None else UNCATEGORIZED_KEY


_KEYS_BY_LABEL = {c.label: c.value for c in AccountCategory} | {
    UNCATEGORIZED_LABEL: UNCATEGORIZED_KEY
}


def key_for_label(label: str) -> str:
    """The key behind a category label from web.dashboard ("Bank Accounts"
    -> "bank_accounts", "Uncategorized" -> "uncategorized")."""
    return _KEYS_BY_LABEL[label]


class CategoryOption(BaseModel):
    """An account category, in display order."""

    key: str
    label: str


def category_options() -> list[CategoryOption]:
    """Every account category in display order (Uncategorized not included:
    it is the absence of one, sent as null)."""
    return [CategoryOption(key=c.value, label=c.label) for c in AccountCategory]
