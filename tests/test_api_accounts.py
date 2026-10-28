"""The Accounts page and account drawer as data, and account writes, over
/api/workspaces/{id}/accounts/...

The page models are checked against the helpers the Jinja pages render from
(accounts_view, retire_warning), and every write's refusals carry the
service's own message.
"""

from datetime import date
from decimal import Decimal

import pytest

from sensibility import repository as repo
from sensibility.accounts import create_account, retire_account, retire_warning
from sensibility.clock import today
from sensibility.models import AccountCategory, ProportionalFormula, RecordType
from sensibility.web.accounts_routes import accounts_view, format_money
from sensibility.workspaces import create_workspace
from tests.support import WS
from tests.web_support import STRANGER, TZ, add_user, login, session_for

ASSET, LIABILITY = RecordType.ASSET, RecordType.LIABILITY
API = f"/api/workspaces/{WS}/accounts"
OVERVIEW = f"{API}/overview"
SAVED = date(2026, 9, 27)
ZONE = "Pacific/Kiritimati"  # UTC+14: often a day ahead of the server's


@pytest.fixture(autouse=True)
def _logged_in(client):
    """As the seeded workspace's owner, unless a test logs in as another."""
    login(client)


@pytest.fixture
def ids(db_connection):
    """Schwab (an input to Cap gains tax), Fidelity, Checking, Card, the
    computed Cap gains tax, and Old (retired), with one snapshot. Returns
    {name: id}."""
    conn = db_connection
    invest = AccountCategory.INVESTMENT_ACCOUNTS
    schwab = create_account(conn, WS, "Schwab", ASSET, category=invest)
    fidelity = create_account(conn, WS, "Fidelity", ASSET, category=invest)
    checking = create_account(
        conn, WS, "Checking", ASSET, category=AccountCategory.BANK_ACCOUNTS
    )
    card = create_account(
        conn, WS, "Card", LIABILITY, category=AccountCategory.CREDIT_CARDS
    )
    tax = create_account(
        conn,
        WS,
        "Cap gains tax",
        LIABILITY,
        ProportionalFormula(rate=Decimal("0.15"), cost_basis=Decimal("82386.74")),
        [schwab.id],
        category=AccountCategory.TAX_LIABILITY,
    )
    old = create_account(conn, WS, "Old", ASSET)
    repo.upsert_amounts(conn, WS, date(2026, 9, 1), {old.id: Decimal("50")})
    conn.commit()
    retire_account(conn, WS, old.id, date(2026, 9, 10))
    repo.upsert_amounts(
        conn,
        WS,
        SAVED,
        {
            schwab.id: Decimal("179265.00"),
            fidelity.id: Decimal("1000.00"),
            checking.id: Decimal("500.00"),
            card.id: Decimal("120.50"),
            tax.id: Decimal("14531.74"),
        },
    )
    conn.commit()
    return {a.name: a.id for a in (schwab, fidelity, checking, card, tax, old)}


def _theirs(conn) -> int:
    """Another workspace (id 2) with one account; returns that account's id."""
    add_user(conn, STRANGER)
    theirs = create_workspace(conn, STRANGER["id"], "Theirs")
    return create_account(conn, theirs.id, "Theirs", ASSET).id


def _layout(section: dict) -> list[tuple[str, list[str]]]:
    return [(g["key"], [a["name"] for a in g["accounts"]]) for g in section["groups"]]


# --- overview ----------------------------------------------------------------


@pytest.mark.db
class TestOverview:
    def test_sections_groups_and_totals(self, client, ids):
        body = client.get(OVERVIEW).json()

        assets, liabilities = body["sections"]
        assert (assets["kind"], assets["title"]) == ("asset", "Assets")
        assert _layout(assets) == [
            ("bank_accounts", ["Checking"]),
            ("investment_accounts", ["Fidelity", "Schwab"]),
        ]
        assert _layout(liabilities) == [
            ("credit_cards", ["Card"]),
            ("tax_liability", ["Cap gains tax"]),
        ]
        assert assets["total"] == "180765.00"
        assert assets["groups"][1]["subtotal"] == "180265.00"
        assert liabilities["total"] == "14652.24"
        assert body["net_worth"] == "166112.76"
        assert body["retired_count"] == 1
        assert body["can_edit"] is True
        assert body["last_saved"] == "2026-09-27"
        assert body["categories"] == [
            {"key": c.value, "label": c.label} for c in AccountCategory
        ]

    def test_matches_the_page(self, client, db_connection, ids):
        accounts = repo.get_accounts(db_connection, WS)
        latest = repo.get_latest_snapshot_records(db_connection, WS)
        as_of = today(TZ)
        view = accounts_view(accounts, latest, as_of)

        body = client.get(OVERVIEW, params={"retired": "true"}).json()

        assert body["as_of"] == as_of.isoformat()
        assert body["snapshot_is_today"] is view["snapshot_is_today"]
        assert format_money(Decimal(body["net_worth"])) == view["net_worth"]
        for ours, theirs in zip(body["sections"], view["sections"]):
            assert format_money(Decimal(ours["total"])) == theirs["total"]
            assert [
                (
                    g["key"],
                    g["label"],
                    format_money(Decimal(g["subtotal"])),
                    g["retired"],
                )
                for g in ours["groups"]
            ] == [
                (g["key"], g["label"], g["subtotal"], g["retired"])
                for g in theirs["groups"]
            ]
            assert [[a["id"] for a in g["accounts"]] for g in ours["groups"]] == [
                [r["id"] for r in g["rows"]] for g in theirs["groups"]
            ]

    def test_retired_accounts_only_when_asked(self, client, ids):
        hidden = client.get(OVERVIEW).json()
        shown = client.get(OVERVIEW, params={"retired": "true"}).json()

        assert "uncategorized" not in [
            g["key"] for g in hidden["sections"][0]["groups"]
        ]
        group = shown["sections"][0]["groups"][-1]
        assert (group["key"], group["label"], group["retired"]) == (
            "uncategorized",
            "Uncategorized",
            True,
        )
        old = group["accounts"][0]
        assert (old["name"], old["retired_at"], old["amount"]) == (
            "Old",
            "2026-09-10",
            None,
        )
        assert group["subtotal"] == "0.00"
        # Retired accounts never count, shown or not.
        assert shown["net_worth"] == hidden["net_worth"]
        assert shown["retired_count"] == hidden["retired_count"] == 1

    def test_accounts_carry_their_formula(self, client, ids):
        body = client.get(OVERVIEW).json()
        rows = {
            a["name"]: a
            for s in body["sections"]
            for g in s["groups"]
            for a in g["accounts"]
        }

        assert rows["Cap gains tax"] == {
            "id": ids["Cap gains tax"],
            "name": "Cap gains tax",
            "type": "liability",
            "category": "tax_liability",
            "amount": "14531.74",
            "computed": True,
            "formula": {
                "kind": "proportional",
                "rate": "0.15",
                "rate_percent": "15",
                "cost_basis": "82386.74",
                "inputs": [{"id": ids["Schwab"], "name": "Schwab"}],
                "text": "15% × (Schwab − basis)",
            },
            "retired_at": None,
        }
        assert rows["Schwab"]["computed"] is False
        assert rows["Schwab"]["formula"] is None
        assert rows["Schwab"]["amount"] == "179265.00"

    def test_as_of_is_the_viewers_today(self, client, ids):
        body = client.get(OVERVIEW, headers={"X-Timezone": ZONE}).json()
        assert body["as_of"] == today(ZONE).isoformat()

    def test_a_new_workspace(self, client):
        body = client.get(OVERVIEW).json()

        assert body["last_saved"] is None
        assert body["snapshot_is_today"] is False
        assert body["net_worth"] == "0.00"
        assert [(s["total"], s["groups"]) for s in body["sections"]] == [
            ("0.00", []),
            ("0.00", []),
        ]

    def test_saved_today(self, client, db_connection, ids):
        repo.upsert_amounts(
            db_connection, WS, today(TZ), {ids["Checking"]: Decimal("1")}
        )
        db_connection.commit()

        body = client.get(OVERVIEW).json()

        assert body["snapshot_is_today"] is True
        # Only Checking has a row on the latest date now.
        assert body["sections"][0]["total"] == "1.00"

    def test_a_viewer_reads_but_cannot_edit(self, client, db_connection, ids):
        add_user(db_connection, STRANGER, "viewer")
        session_for(client, STRANGER)

        body = client.get(OVERVIEW).json()

        assert body["can_edit"] is False
        assert body["net_worth"] == "166112.76"


# --- detail ------------------------------------------------------------------


@pytest.mark.db
class TestDetail:
    def test_an_input_is_blocked_from_retiring(self, client, ids):
        body = client.get(f"{API}/{ids['Schwab']}").json()

        assert body["account"]["name"] == "Schwab"
        assert body["can_edit"] is True
        assert body["retire_blocker"] == (
            "Schwab is an input to Cap gains tax. Retire or edit those first."
        )
        assert body["retire_warning"] is None
        assert body["history"] == [{"date": "2026-09-27", "amount": "179265.00"}]
        # Active, plain, not itself: Cap gains tax is computed, Old retired.
        assert body["eligible_inputs"] == [
            {
                "kind": "asset",
                "label": "Assets",
                "accounts": [
                    {"id": ids["Checking"], "name": "Checking", "amount": "500.00"},
                    {"id": ids["Fidelity"], "name": "Fidelity", "amount": "1000.00"},
                ],
            },
            {
                "kind": "liability",
                "label": "Liabilities",
                "accounts": [{"id": ids["Card"], "name": "Card", "amount": "120.50"}],
            },
        ]

    def test_a_non_zero_account_warns(self, client, db_connection, ids):
        account = repo.get_account(db_connection, WS, ids["Fidelity"])
        assert account is not None

        body = client.get(f"{API}/{ids['Fidelity']}").json()

        assert body["retire_blocker"] is None
        assert body["retire_warning"] == retire_warning(db_connection, WS, account)
        assert body["retire_warning"].startswith(
            "Last saved at $1,000.00 on September 27, 2026."
        )

    def test_a_computed_account(self, client, ids):
        body = client.get(f"{API}/{ids['Cap gains tax']}").json()

        assert body["account"]["formula"]["inputs"] == [
            {"id": ids["Schwab"], "name": "Schwab"}
        ]
        names = [a["name"] for g in body["eligible_inputs"] for a in g["accounts"]]
        assert names == ["Checking", "Fidelity", "Schwab", "Card"]

    def test_a_retired_account(self, client, ids):
        body = client.get(f"{API}/{ids['Old']}").json()

        assert body["account"]["retired_at"] == "2026-09-10"
        assert (body["retire_blocker"], body["retire_warning"]) == (None, None)
        assert body["history"] == [{"date": "2026-09-01", "amount": "50.00"}]

    def test_an_input_with_no_saved_amount(self, client, db_connection, ids):
        new = create_account(db_connection, WS, "New", ASSET)

        body = client.get(f"{API}/{ids['Schwab']}").json()

        assert {"id": new.id, "name": "New", "amount": None} in body["eligible_inputs"][
            0
        ]["accounts"]
        assert client.get(f"{API}/{new.id}").json()["history"] == []

    def test_unknown_and_foreign_ids_are_not_found(self, client, db_connection, ids):
        foreign = _theirs(db_connection)
        for account_id in (999, foreign):
            response = client.get(f"{API}/{account_id}")
            assert (response.status_code, response.json()) == (
                404,
                {"error": "Account not found"},
            )


# --- create ------------------------------------------------------------------


@pytest.mark.db
class TestCreate:
    def test_a_plain_account(self, client, db_connection, ids):
        response = client.post(
            API,
            json={
                "name": "  Ally   Savings ",
                "type": "asset",
                "category": "bank_accounts",
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body == {
            "id": body["id"],
            "name": "Ally Savings",
            "type": "asset",
            "category": "bank_accounts",
            "amount": None,
            "computed": False,
            "formula": None,
            "retired_at": None,
        }
        saved = repo.get_account(db_connection, WS, body["id"])
        assert saved is not None and saved.name == "Ally Savings"

    def test_a_computed_account(self, client, db_connection, ids):
        response = client.post(
            API,
            json={
                "name": "State tax",
                "type": "liability",
                "formula": {
                    "rate_percent": "4.95",
                    "cost_basis": "$1,000",
                    "input_ids": [ids["Fidelity"], ids["Schwab"]],
                },
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["category"] is None
        assert body["formula"] == {
            "kind": "proportional",
            "rate": "0.0495",
            "rate_percent": "4.95",
            "cost_basis": "1000.00",
            "inputs": [
                {"id": ids["Schwab"], "name": "Schwab"},
                {"id": ids["Fidelity"], "name": "Fidelity"},
            ],
            "text": "4.95% × (Schwab + Fidelity − basis)",
        }

    def test_the_same_name_on_the_other_side_is_fine(self, client, ids):
        response = client.post(API, json={"name": "Schwab", "type": "liability"})
        assert response.status_code == 201

    @pytest.mark.parametrize(
        "body, message",
        [
            ({"name": "  ", "type": "asset"}, "Name is required"),
            (
                {"name": "Schwab", "type": "asset"},
                "A asset named 'Schwab' already exists",
            ),
            (
                {"name": "T", "type": "liability", "formula": {"rate_percent": "15"}},
                "A computed account needs at least one input",
            ),
            (
                {
                    "name": "T",
                    "type": "liability",
                    "formula": {"rate_percent": "15", "input_ids": ["Cap gains tax"]},
                },
                "Cap gains tax is computed and cannot be an input",
            ),
            (
                {
                    "name": "T",
                    "type": "liability",
                    "formula": {"rate_percent": "15", "input_ids": ["Old"]},
                },
                "Old is retired and cannot be an input",
            ),
            (
                {
                    "name": "T",
                    "type": "liability",
                    "formula": {"rate_percent": "15", "input_ids": [999]},
                },
                "Input account 999 does not exist",
            ),
            (
                {
                    "name": "T",
                    "type": "liability",
                    "formula": {"rate_percent": "lots", "input_ids": ["Schwab"]},
                },
                "Rate must be a number, e.g. 15 for 15%",
            ),
            (
                {
                    "name": "T",
                    "type": "liability",
                    "formula": {"rate_percent": "-5", "input_ids": ["Schwab"]},
                },
                "Rate must be zero or more",
            ),
            (
                {
                    "name": "T",
                    "type": "liability",
                    "formula": {
                        "rate_percent": "15",
                        "cost_basis": "some",
                        "input_ids": ["Schwab"],
                    },
                },
                "'some' is not a number",
            ),
        ],
    )
    def test_refusals(self, client, db_connection, ids, body, message):
        if body.get("formula"):
            body["formula"]["input_ids"] = [
                ids.get(i, i) for i in body["formula"].get("input_ids", [])
            ]
        before = repo.get_accounts(db_connection, WS)

        response = client.post(API, json=body)

        assert (response.status_code, response.json()) == (400, {"error": message})
        assert repo.get_accounts(db_connection, WS) == before

    def test_another_workspaces_account_is_no_input(self, client, db_connection, ids):
        foreign = _theirs(db_connection)
        response = client.post(
            API,
            json={
                "name": "T",
                "type": "liability",
                "formula": {"rate_percent": "15", "input_ids": [foreign]},
            },
        )
        assert response.json() == {"error": f"Input account {foreign} does not exist"}

    @pytest.mark.parametrize(
        "body",
        [
            {"type": "asset"},
            {"name": "X", "type": "equity"},
            {"name": "X", "type": "asset", "category": "cash"},
        ],
    )
    def test_malformed_bodies_are_422(self, client, db_connection, body):
        assert client.post(API, json=body).status_code == 422
        assert repo.get_accounts(db_connection, WS) == []


# --- update ------------------------------------------------------------------


@pytest.mark.db
class TestUpdate:
    def _patch(self, client, account_id: int, body: dict):
        return client.patch(f"{API}/{account_id}", json=body)

    def test_rename_keeps_everything_else(self, client, ids):
        response = self._patch(client, ids["Cap gains tax"], {"name": "Federal tax"})

        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "Federal tax"
        assert body["category"] == "tax_liability"
        assert body["amount"] == "14531.74"
        assert body["formula"]["cost_basis"] == "82386.74"
        assert body["formula"]["inputs"] == [{"id": ids["Schwab"], "name": "Schwab"}]

    def test_renaming_an_input_renames_it_in_formulas(self, client, ids):
        self._patch(client, ids["Schwab"], {"name": "Schwab brokerage"})

        tax = client.get(f"{API}/{ids['Cap gains tax']}").json()["account"]
        assert tax["formula"]["text"] == "15% × (Schwab brokerage − basis)"

    def test_category_set_and_cleared(self, client, ids):
        set_ = self._patch(client, ids["Card"], {"category": "bank_accounts"}).json()
        cleared = self._patch(client, ids["Card"], {"category": None}).json()

        assert set_["category"] == "bank_accounts"
        assert cleared["category"] is None
        assert cleared["name"] == "Card"

    def test_formula_null_makes_it_plain(self, client, db_connection, ids):
        body = self._patch(client, ids["Cap gains tax"], {"formula": None}).json()

        assert (body["computed"], body["formula"]) == (False, None)
        saved = repo.get_account(db_connection, WS, ids["Cap gains tax"])
        assert saved is not None and saved.input_ids == []
        # Schwab is nobody's input now, so it may retire.
        assert client.get(f"{API}/{ids['Schwab']}").json()["retire_blocker"] is None

    def test_plain_becomes_computed_with_a_zero_basis(self, client, ids):
        body = self._patch(
            client,
            ids["Checking"],
            {"formula": {"rate_percent": "10", "input_ids": [ids["Fidelity"]]}},
        ).json()

        assert body["computed"] is True
        assert body["formula"]["cost_basis"] == "0.00"
        assert body["formula"]["rate_percent"] == "10"

    def test_a_new_formula_keeps_the_basis_unless_sent(self, client, ids):
        kept = self._patch(
            client,
            ids["Cap gains tax"],
            {
                "formula": {
                    "rate_percent": "20",
                    "input_ids": [ids["Schwab"], ids["Fidelity"]],
                }
            },
        ).json()
        blanked = self._patch(
            client,
            ids["Cap gains tax"],
            {
                "formula": {
                    "rate_percent": "20",
                    "cost_basis": "",
                    "input_ids": [ids["Schwab"]],
                }
            },
        ).json()

        assert kept["formula"]["cost_basis"] == "82386.74"
        assert kept["formula"]["rate"] == "0.2"
        assert [i["name"] for i in kept["formula"]["inputs"]] == ["Schwab", "Fidelity"]
        assert blanked["formula"]["cost_basis"] == "0.00"

    def test_the_type_never_changes(self, client, ids):
        body = self._patch(client, ids["Checking"], {"type": "liability"}).json()
        assert body["type"] == "asset"

    @pytest.mark.parametrize(
        "account, body, message",
        [
            ("Schwab", {"name": None}, "Name is required"),
            ("Schwab", {"name": ""}, "Name is required"),
            ("Schwab", {"name": "Fidelity"}, "A asset named 'Fidelity' already exists"),
            (
                "Schwab",
                {"formula": {"rate_percent": "15", "input_ids": ["Fidelity"]}},
                "Schwab is an input to Cap gains tax and cannot be computed",
            ),
            (
                "Cap gains tax",
                {"formula": {"rate_percent": "15", "input_ids": ["Cap gains tax"]}},
                "An account cannot be its own input",
            ),
            (
                "Checking",
                {"formula": {"rate_percent": "15", "input_ids": ["Cap gains tax"]}},
                "Cap gains tax is computed and cannot be an input",
            ),
            (
                "Checking",
                {"formula": {"rate_percent": "15", "input_ids": []}},
                "A computed account needs at least one input",
            ),
            (
                "Checking",
                {"formula": {"rate_percent": "x", "input_ids": ["Fidelity"]}},
                "Rate must be a number, e.g. 15 for 15%",
            ),
        ],
    )
    def test_refusals(self, client, db_connection, ids, account, body, message):
        if body.get("formula"):
            body["formula"]["input_ids"] = [
                ids[i] for i in body["formula"]["input_ids"]
            ]
        before = repo.get_accounts(db_connection, WS)

        response = self._patch(client, ids[account], body)

        assert (response.status_code, response.json()) == (400, {"error": message})
        assert repo.get_accounts(db_connection, WS) == before

    def test_unknown_and_foreign_ids_are_not_found(self, client, db_connection, ids):
        foreign = _theirs(db_connection)
        theirs_before = repo.get_accounts(db_connection, 2)
        for account_id in (999, foreign):
            response = self._patch(client, account_id, {"name": "Mine now"})
            assert (response.status_code, response.json()) == (
                404,
                {"error": "Account not found"},
            )
        assert repo.get_accounts(db_connection, 2) == theirs_before


# --- retire and unretire -----------------------------------------------------


@pytest.mark.db
class TestRetire:
    def test_retire_as_of_the_viewers_today(self, client, ids):
        response = client.post(
            f"{API}/{ids['Fidelity']}/retire", headers={"X-Timezone": ZONE}
        )

        assert response.status_code == 200
        assert response.json()["retired_at"] == today(ZONE).isoformat()
        overview = client.get(OVERVIEW).json()
        assert "Fidelity" not in _layout(overview["sections"][0])[1][1]
        assert overview["retired_count"] == 2

    def test_retire_refusals(self, client, db_connection, ids):
        blocked = client.post(f"{API}/{ids['Schwab']}/retire")
        again = client.post(f"{API}/{ids['Old']}/retire")

        assert (blocked.status_code, blocked.json()) == (
            400,
            {
                "error": "Schwab is an input to Cap gains tax. Retire or edit those first."
            },
        )
        assert again.json() == {"error": "Old is already retired"}
        schwab = repo.get_account(db_connection, WS, ids["Schwab"])
        assert schwab is not None and schwab.is_active

    def test_unretire(self, client, ids):
        response = client.post(f"{API}/{ids['Old']}/unretire")

        assert response.status_code == 200
        assert (response.json()["retired_at"], response.json()["amount"]) == (
            None,
            None,
        )
        assert client.get(OVERVIEW).json()["retired_count"] == 0

    def test_unretire_refusals(self, client, ids):
        # Retire the tax, then its input (now free), then try to bring the
        # tax back: its formula names a retired account.
        tax, schwab = ids["Cap gains tax"], ids["Schwab"]
        assert client.post(f"{API}/{tax}/retire").status_code == 200
        assert client.post(f"{API}/{schwab}/retire").status_code == 200

        stale = client.post(f"{API}/{tax}/unretire")
        active = client.post(f"{API}/{ids['Checking']}/unretire")

        assert (stale.status_code, stale.json()) == (
            400,
            {
                "error": "Cannot unretire Cap gains tax: Schwab is retired and "
                "cannot be an input. Edit its formula first."
            },
        )
        assert active.json() == {"error": "Checking is not retired"}

    def test_unknown_and_foreign_ids_are_not_found(self, client, db_connection, ids):
        foreign = _theirs(db_connection)
        for action in ("retire", "unretire"):
            for account_id in (999, foreign):
                response = client.post(f"{API}/{account_id}/{action}")
                assert response.status_code == 404
        theirs = repo.get_account(db_connection, 2, foreign)
        assert theirs is not None and theirs.is_active


# --- roles -------------------------------------------------------------------


@pytest.mark.db
def test_a_viewer_reads_but_cannot_write(client, db_connection, ids):
    add_user(db_connection, STRANGER, "viewer")
    session_for(client, STRANGER)
    before = repo.get_accounts(db_connection, WS)

    assert client.get(OVERVIEW).status_code == 200
    assert client.get(f"{API}/{ids['Schwab']}").json()["can_edit"] is False
    writes = [
        client.post(API, json={"name": "X", "type": "asset"}),
        client.patch(f"{API}/{ids['Schwab']}", json={"name": "X"}),
        client.post(f"{API}/{ids['Fidelity']}/retire"),
        client.post(f"{API}/{ids['Old']}/unretire"),
    ]

    assert [(r.status_code, r.json()) for r in writes] == [
        (403, {"error": "This needs the editor role or higher"})
    ] * 4
    assert repo.get_accounts(db_connection, WS) == before


@pytest.mark.db
def test_an_editor_can_write(client, db_connection, ids):
    add_user(db_connection, STRANGER, "editor")
    session_for(client, STRANGER)

    assert client.post(API, json={"name": "X", "type": "asset"}).status_code == 201
    assert client.post(f"{API}/{ids['Fidelity']}/retire").status_code == 200
