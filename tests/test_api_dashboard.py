"""GET /api/workspaces/{id}/dashboard: the dashboard page as data.

Every figure is checked against the helpers it is computed from
(web/dashboard.py, unit-tested in test_dashboard.py), and a few against
hand-worked numbers.
"""

from datetime import date
from decimal import Decimal

import pytest

from sensibility import repository as repo
from sensibility.accounts import create_account, retire_account
from sensibility.models import AccountCategory, ProportionalFormula, RecordType
from sensibility.web.dashboard import (
    account_cards,
    category_bars,
    change_since,
    daily_totals,
    filter_range,
    getting_started,
    latest_category_totals,
)
from sensibility.workspaces import create_workspace
from tests.support import WS
from tests.web_support import STRANGER, add_user, login, session_for

ASSET, LIABILITY = RecordType.ASSET, RecordType.LIABILITY
DASHBOARD = f"/api/workspaces/{WS}/dashboard"


@pytest.fixture(autouse=True)
def _logged_in(client):
    """As the seeded workspace's owner, unless a test logs in as another."""
    login(client)


@pytest.fixture
def history(db_connection):
    """Four snapshots, a computed liability, a retired account, and an
    account added after the latest snapshot."""
    conn = db_connection
    checking = create_account(
        conn, WS, "Checking", ASSET, category=AccountCategory.BANK_ACCOUNTS
    )
    schwab = create_account(
        conn, WS, "Schwab", ASSET, category=AccountCategory.INVESTMENT_ACCOUNTS
    )
    card = create_account(
        conn, WS, "Card", LIABILITY, category=AccountCategory.CREDIT_CARDS
    )
    tax = create_account(
        conn,
        WS,
        "Tax",
        LIABILITY,
        ProportionalFormula(rate=Decimal("0.15"), cost_basis=Decimal("7000")),
        [schwab.id],
        category=AccountCategory.TAX_LIABILITY,
    )
    old = create_account(conn, WS, "Old", ASSET)
    ids = [a.id for a in (checking, schwab, card, tax, old)]
    for day, amounts in {
        date(2025, 9, 1): ["1000", "5000", "200", "0", "300"],
        date(2026, 8, 20): ["2000", "8000", "300", "150", None],
        date(2026, 9, 24): ["2500", "9000", "400", "300", None],
        date(2026, 10, 24): ["3000.50", "10000", "250.25", "450", None],
    }.items():
        repo.upsert_amounts(
            conn,
            WS,
            day,
            {i: Decimal(a) for i, a in zip(ids, amounts) if a is not None},
        )
    conn.commit()
    retire_account(conn, WS, old.id, date(2026, 8, 1))
    create_account(conn, WS, "New", ASSET)
    return conn


def _expected_categories(records, accounts):
    return {
        type.value: [
            {
                "key": "uncategorized"
                if c.label == "Uncategorized"
                else c.label.lower().replace(" ", "_"),
                "label": c.label,
                "amount": str(c.amount.quantize(Decimal("0.01"))),
                "color": c.color,
            }
            for c in cats
        ]
        for type, cats in latest_category_totals(records, accounts).items()
    }


@pytest.mark.db
class TestWithSnapshots:
    def test_headline_change_and_last_snapshot(self, client, history):
        body = client.get(DASHBOARD).json()

        assert body["has_data"] is True
        assert body["can_edit"] is True
        assert body["onboarding"] is None
        # 3000.50 + 10000 − 250.25 − 450
        assert body["net_worth"] == "12300.25"
        assert body["last_snapshot"] == "2026-10-24"
        # Against Sep 24, exactly 30 days before: 12300.25 − 10800.
        assert body["change"] == {
            "since": "2026-09-24",
            "amount": "1500.25",
            "percent": "13.9",
        }

    def test_matches_the_pages_helpers(self, client, history):
        records = repo.get_all_records(history, WS)
        accounts = repo.get_accounts(history, WS)
        points = daily_totals(records)
        change = change_since(points)
        assert change is not None

        body = client.get(DASHBOARD).json()

        assert Decimal(body["net_worth"]) == points[-1].net_worth
        assert Decimal(body["change"]["amount"]) == change.amount
        assert body["categories"] == _expected_categories(records, accounts)
        bars = category_bars(latest_category_totals(records, accounts))
        assert {
            kind: [(s["label"], s["color"], Decimal(s["share"])) for s in segments]
            for kind, segments in body["bars"].items()
        } == {
            type.value: [(s.label, s.color, s.share) for s in segments]
            for type, segments in bars.items()
        }
        cards = account_cards(records, accounts)
        for card in body["cards"]:
            expected = cards[RecordType(card["kind"])]
            assert Decimal(card["total"]) == expected["total"]
            assert [
                (
                    g["label"],
                    Decimal(g["total"]),
                    [(a["name"], a["amount"]) for a in g["accounts"]],
                )
                for g in card["groups"]
            ] == [
                (
                    g["label"],
                    g["total"],
                    [
                        (r["name"], None if r["amount"] is None else str(r["amount"]))
                        for r in g["rows"]
                    ],
                )
                for g in expected["groups"]
            ]

    def test_categories_largest_first_with_their_colors(self, client, history):
        body = client.get(DASHBOARD).json()

        assert body["categories"] == {
            "asset": [
                {
                    "key": "investment_accounts",
                    "label": "Investment Accounts",
                    "amount": "10000.00",
                    "color": "var(--asset)",
                },
                {
                    "key": "bank_accounts",
                    "label": "Bank Accounts",
                    "amount": "3000.50",
                    "color": "var(--asset-2)",
                },
            ],
            "liability": [
                {
                    "key": "tax_liability",
                    "label": "Tax Liability",
                    "amount": "450.00",
                    "color": "var(--liability)",
                },
                {
                    "key": "credit_cards",
                    "label": "Credit Cards",
                    "amount": "250.25",
                    "color": "var(--liability-2)",
                },
            ],
        }
        # One scale: assets (13000.50) fill the track.
        assert sum(Decimal(s["share"]) for s in body["bars"]["asset"]) == 100

    def test_cards_list_active_accounts_with_ids(self, client, history):
        accounts = {a.name: a.id for a in repo.get_accounts(history, WS)}

        assets, liabilities = client.get(DASHBOARD).json()["cards"]

        assert (assets["kind"], assets["title"]) == ("asset", "Assets")
        assert assets["total"] == "13000.50"
        assert [
            (
                g["key"],
                g["total"],
                [(a["id"], a["name"], a["amount"]) for a in g["accounts"]],
            )
            for g in assets["groups"]
        ] == [
            (
                "bank_accounts",
                "3000.50",
                [(accounts["Checking"], "Checking", "3000.50")],
            ),
            (
                "investment_accounts",
                "10000.00",
                [(accounts["Schwab"], "Schwab", "10000.00")],
            ),
            # Added since the latest snapshot: no amount; Old is retired.
            ("uncategorized", "0.00", [(accounts["New"], "New", None)]),
        ]
        assert liabilities["total"] == "700.25"
        tax = liabilities["groups"][1]["accounts"][0]
        assert (tax["name"], tax["computed"]) == ("Tax", "15% of gains, computed")
        assert liabilities["groups"][0]["accounts"][0]["computed"] is None
        assert assets.get("empty") is None and assets.get("add") is None

    @pytest.mark.parametrize(
        "range_key, applied, dates",
        [
            (None, "1y", ["2026-08-20", "2026-09-24", "2026-10-24"]),
            ("1y", "1y", ["2026-08-20", "2026-09-24", "2026-10-24"]),
            ("6m", "6m", ["2026-08-20", "2026-09-24", "2026-10-24"]),
            ("all", "all", ["2025-09-01", "2026-08-20", "2026-09-24", "2026-10-24"]),
            ("bogus", "1y", ["2026-08-20", "2026-09-24", "2026-10-24"]),
        ],
    )
    def test_ranges(self, client, history, range_key, applied, dates):
        params = {} if range_key is None else {"range": range_key}
        body = client.get(DASHBOARD, params=params).json()

        assert body["range"] == applied
        assert body["ranges"] == [
            {"key": "6m", "label": "6M"},
            {"key": "1y", "label": "1Y"},
            {"key": "all", "label": "All"},
        ]
        assert [p["date"] for p in body["history"]] == dates
        points = filter_range(daily_totals(repo.get_all_records(history, WS)), applied)
        assert body["history"] == [
            {
                "date": p.date.isoformat(),
                "assets": str(p.assets),
                "liabilities": str(p.liabilities),
                "net_worth": str(p.net_worth),
            }
            for p in points
        ]

    def test_the_range_counts_back_from_the_latest_snapshot(self, client, history):
        # 6m from Oct 24 starts Apr 24: Aug 20 is in, Sep 1 2025 is not.
        body = client.get(DASHBOARD, params={"range": "6m"}).json()
        assert body["history"][0]["date"] == "2026-08-20"
        assert body["history"][0] == {
            "date": "2026-08-20",
            "assets": "10000.00",
            "liabilities": "450.00",
            "net_worth": "9550.00",
        }

    def test_the_range_leaves_the_headline_and_columns_alone(self, client, history):
        """Only the history follows ?range=: the rest is the latest snapshot."""
        short = client.get(f"{DASHBOARD}?range=6m").json()
        everything = client.get(f"{DASHBOARD}?range=all").json()

        assert short["history"] != everything["history"]
        for key in (
            "net_worth",
            "change",
            "last_snapshot",
            "categories",
            "bars",
            "cards",
        ):
            assert short[key] == everything[key], key

    def test_only_this_workspaces_snapshots_count(self, client, db_connection, history):
        add_user(db_connection, STRANGER)
        theirs = create_workspace(db_connection, STRANGER["id"], "Theirs")
        elsewhere = create_account(db_connection, theirs.id, "Elsewhere", ASSET)
        repo.upsert_amounts(
            db_connection,
            theirs.id,
            date(2026, 12, 1),
            {elsewhere.id: Decimal("123456")},
        )
        db_connection.commit()

        body = client.get(f"{DASHBOARD}?range=all").json()

        assert body["last_snapshot"] == "2026-10-24"
        assert body["net_worth"] == "12300.25"
        assert "2026-12-01" not in [p["date"] for p in body["history"]]
        names = [
            a["name"]
            for card in body["cards"]
            for group in card["groups"]
            for a in group["accounts"]
        ]
        assert "Elsewhere" not in names

    def test_one_snapshot_has_no_change(self, client, db_connection):
        cash = create_account(db_connection, WS, "Cash", ASSET)
        repo.upsert_amounts(
            db_connection, WS, date(2026, 10, 1), {cash.id: Decimal("0")}
        )
        db_connection.commit()

        body = client.get(DASHBOARD).json()

        assert body["change"] is None
        assert body["net_worth"] == "0.00"
        # Categories totalling zero are left out, and so draw no bars.
        assert body["categories"] == {"asset": [], "liability": []}
        assert body["bars"] == {"asset": [], "liability": []}

    def test_percent_is_null_from_a_zero_net_worth(self, client, db_connection):
        cash = create_account(db_connection, WS, "Cash", ASSET)
        repo.upsert_amounts(
            db_connection, WS, date(2026, 9, 1), {cash.id: Decimal("0")}
        )
        repo.upsert_amounts(
            db_connection, WS, date(2026, 10, 1), {cash.id: Decimal("5")}
        )
        db_connection.commit()

        change = client.get(DASHBOARD).json()["change"]

        assert change == {"since": "2026-09-01", "amount": "5.00", "percent": None}


@pytest.mark.db
class TestGettingStarted:
    def test_a_new_workspace(self, client):
        body = client.get(DASHBOARD).json()

        assert body["has_data"] is False
        assert body["can_edit"] is True
        assert (body["net_worth"], body["last_snapshot"], body["change"]) == (
            None,
            None,
            None,
        )
        assert body["history"] == []
        assert body["categories"] == {"asset": [], "liability": []}
        assert body["onboarding"] == {
            "has_accounts": False,
            "steps": [
                {
                    "title": s["title"],
                    "text": s["text"],
                    "done": s["done"],
                    "action": None
                    if s["action"] is None
                    else {"label": s["action"][0], "path": s["action"][1]},
                }
                for s in getting_started(0)
            ],
        }
        assert body["onboarding"]["steps"][0]["action"] == {
            "label": "+ Add an account",
            "path": "/accounts/new?type=asset",
        }
        assets, liabilities = body["cards"]
        assert assets == {
            "kind": "asset",
            "title": "Assets",
            "total": "0.00",
            "groups": [],
            "empty": "No assets yet.",
            "add": {"label": "+ Add an asset", "path": "/accounts/new?type=asset"},
        }
        assert liabilities["add"] == {
            "label": "+ Add a liability",
            "path": "/accounts/new?type=liability",
        }

    def test_accounts_but_no_snapshot(self, client, db_connection):
        create_account(
            db_connection, WS, "Checking", ASSET, category=AccountCategory.BANK_ACCOUNTS
        )
        gone = create_account(db_connection, WS, "Gone", LIABILITY)
        retire_account(db_connection, WS, gone.id, date(2026, 10, 1))

        body = client.get(DASHBOARD).json()

        steps = body["onboarding"]["steps"]
        assert body["onboarding"]["has_accounts"] is True
        assert steps[0]["done"] is True
        assert steps[0]["text"] == "Done: 1 account added. Add more any time."
        assert steps[1]["action"] == {"label": "Enter balances", "path": "/accounts"}
        assets, liabilities = body["cards"]
        # A card listing accounts shows "—" for its total; an empty one $0.
        assert assets["total"] is None
        assert assets["groups"][0]["accounts"][0]["amount"] is None
        assert liabilities["total"] == "0.00"
        assert liabilities["groups"] == []

    def test_a_viewer_cannot_edit(self, client, db_connection):
        add_user(db_connection, STRANGER, "viewer")
        session_for(client, STRANGER)

        body = client.get(DASHBOARD).json()

        assert body["can_edit"] is False
        assert body["onboarding"]["has_accounts"] is False


@pytest.mark.db
def test_another_workspace_is_not_found(client, db_connection, history):
    add_user(db_connection, STRANGER)
    theirs = create_workspace(db_connection, STRANGER["id"], "Theirs")

    assert client.get(f"/api/workspaces/{theirs.id}/dashboard").status_code == 404
    session_for(client, STRANGER)
    response = client.get(DASHBOARD)
    assert (response.status_code, response.json()) == (
        404,
        {"error": "Workspace not found"},
    )
