"""Pure tests for the Accounts page's facts (web/accounts_model.py), which the
API serves (test_api_accounts.py) and the MCP tools share."""

from datetime import date
from decimal import Decimal

from sensibility.models import Account, ProportionalFormula, Record, RecordType
from sensibility.web.accounts_model import (
    account_rows,
    accounts_view,
    candidate_groups,
    category_groups,
    format_percent,
    formula_text,
    saved_total,
)

A, L = RecordType.ASSET, RecordType.LIABILITY
SCHWAB = Account(id=1, name="Schwab", type=A)
TAX = Account(
    id=2,
    name="Cap Gains Tax",
    type=L,
    formula=ProportionalFormula(rate=Decimal("0.15"), cost_basis=Decimal("70634")),
    input_ids=[1],
)
OLD = Account(id=3, name="Old", type=A, retired_at=date(2026, 1, 1))


def record(account: Account, amount: str, day: date = date(2026, 9, 1)) -> Record:
    return Record(
        date=day,
        account_id=account.id,
        type=account.type,
        description=account.name,
        amount=Decimal(amount),
    )


def test_format_percent():
    assert format_percent(Decimal("0.15")) == "15"
    assert format_percent(Decimal("0.325")) == "32.5"
    assert format_percent(Decimal("0")) == "0"
    assert format_percent(Decimal("1")) == "100"


def test_formula_text():
    by_id = {1: SCHWAB, 2: TAX}
    assert formula_text(TAX, by_id) == "15% × (Schwab − basis)"
    assert formula_text(TAX, {}) == "15% × (account 1 − basis)"
    assert formula_text(SCHWAB, by_id) == ""


def test_account_rows():
    latest = [record(SCHWAB, "163202.77"), record(TAX, "13885.32")]

    rows = account_rows([SCHWAB, TAX, OLD], latest)

    assert rows == [
        {
            "id": 1,
            "name": "Schwab",
            "type": "asset",
            "category": None,
            "amount": Decimal("163202.77"),
            "retired": False,
        },
        {
            "id": 2,
            "name": "Cap Gains Tax",
            "type": "liability",
            "category": None,
            "amount": Decimal("13885.32"),
            "retired": False,
        },
        # No row on the latest date: no amount.
        {
            "id": 3,
            "name": "Old",
            "type": "asset",
            "category": None,
            "amount": None,
            "retired": True,
        },
    ]


def test_saved_total_skips_retired_and_missing_amounts():
    def row(name, category, amount, retired=False):
        return {
            "name": name,
            "category": category,
            "amount": None if amount is None else Decimal(amount),
            "retired": retired,
        }

    rows = [
        row("Chase", "bank_accounts", "100.10"),
        row("Ally", "bank_accounts", "-0.10"),
        row("Old", "bank_accounts", "999", retired=True),
        row("New", "investment_accounts", None),
        row("House", None, "400000"),
    ]

    assert saved_total([]) == Decimal("0")
    assert saved_total(rows) == Decimal("400100.00")
    assert [(g["label"], saved_total(g["rows"])) for g in category_groups(rows)] == [
        ("Bank Accounts", Decimal("100.00")),
        ("Investment Accounts", Decimal("0")),
        ("Uncategorized", Decimal("400000")),
    ]


def test_category_groups_orders_categories_and_puts_uncategorized_last():
    def row(name, category, retired=False):
        return {"name": name, "category": category, "retired": retired}

    rows = [
        row("Mystery", None),
        row("Schwab", "investment_accounts"),
        row("Chase", "bank_accounts"),
        row("Old Ally", "bank_accounts", retired=True),
        row("Old 401k", "investment_accounts", retired=True),
    ]
    groups = category_groups(rows)

    assert [(g["label"], [r["name"] for r in g["rows"]]) for g in groups] == [
        ("Bank Accounts", ["Chase", "Old Ally"]),
        ("Investment Accounts", ["Schwab", "Old 401k"]),
        ("Uncategorized", ["Mystery"]),
    ]
    assert [g["key"] for g in groups] == [
        "bank_accounts",
        "investment_accounts",
        "uncategorized",
    ]
    assert [g["retired"] for g in groups] == [False, False, False]
    assert category_groups([row("Gone", "credit_cards", retired=True)])[0]["retired"]


def test_accounts_view_puts_active_first_then_by_name():
    accounts = [
        Account(id=1, name="zeta", type=A),
        Account(id=2, name="Alpha", type=A, retired_at=date(2026, 1, 1)),
        Account(id=3, name="beta", type=A),
        Account(id=4, name="Card", type=L),
    ]

    view = accounts_view(accounts, [], date(2026, 10, 28))

    assets, liabilities = view["sections"]
    assert (assets["kind"], assets["title"]) == ("asset", "Assets")
    assert (liabilities["kind"], liabilities["title"]) == ("liability", "Liabilities")
    assert [r["name"] for r in assets["groups"][0]["rows"]] == ["beta", "zeta", "Alpha"]
    assert [r["name"] for r in liabilities["groups"][0]["rows"]] == ["Card"]
    assert view["retired_count"] == 1
    assert view["snapshot_is_today"] is False


def test_accounts_view_knows_a_save_today_replaces():
    today = date(2026, 9, 1)
    view = accounts_view([SCHWAB], [record(SCHWAB, "1", today)], today)
    assert view["snapshot_is_today"] is True
    view = accounts_view([SCHWAB], [record(SCHWAB, "1", today)], date(2026, 9, 2))
    assert view["snapshot_is_today"] is False


def test_candidate_groups_are_active_plain_accounts_but_this_one():
    card = Account(id=4, name="Card", type=L)
    groups = candidate_groups(
        [SCHWAB, TAX, OLD, card], exclude_id=None, amounts={1: Decimal("5")}
    )
    assert groups == [
        ("Assets", [{"id": 1, "name": "Schwab", "amount": Decimal("5")}]),
        ("Liabilities", [{"id": 4, "name": "Card", "amount": None}]),
    ]
    # Never its own input; an empty group is left out.
    assert candidate_groups([SCHWAB, TAX, OLD, card], exclude_id=4, amounts={}) == [
        ("Assets", [{"id": 1, "name": "Schwab", "amount": None}])
    ]
