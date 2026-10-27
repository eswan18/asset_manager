"""Web tests: real database container plus a signed session cookie."""

import re
from datetime import date
from decimal import Decimal

import pytest
from itsdangerous import URLSafeTimedSerializer

from asset_manager.accounts import create_account, retire_account
from asset_manager.clock import today
from asset_manager.models import Account, Record, RecordType
from asset_manager.repository import upsert_amounts
from tests.support import WS
from tests.web_support import (
    PAGES,
    ACCOUNTS,
    SECRET,
    SNAPSHOTS,
    STRANGER,
    TZ,
    USER,
    FakeIdp,
    add_user,
    claims,
    login,
    protected_routes,
    session_for,
    sweep,
)


@pytest.mark.db
class TestAuth:
    def test_dashboard_redirects_when_logged_out(self, client):
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/login"

    def test_json_clients_get_401_when_logged_out(self, client):
        response = client.get("/", headers={"Accept": "application/json"})
        assert response.status_code == 401
        assert response.json() == {"error": "Login required"}


class TestIsEmailAllowed:
    @pytest.fixture(autouse=True)
    def _clean(self, monkeypatch):
        monkeypatch.delenv("ALLOWED_EMAILS", raising=False)
        monkeypatch.delenv("ENV", raising=False)

    @staticmethod
    def allowed(email):
        from asset_manager.web.auth import is_email_allowed

        return is_email_allowed(email)

    def test_dev_with_no_allowlist_is_open(self, monkeypatch):
        monkeypatch.setenv("ENV", "dev")
        assert self.allowed("anyone@example.com")
        assert self.allowed(None)

    @pytest.mark.parametrize(
        "env",
        [None, "", "prod", "staging", "Dev", "DEV", " dev", "dev ", "development"],
    )
    @pytest.mark.parametrize("raw", [None, "", " ", ",", " , "])
    def test_anything_but_exactly_dev_with_no_allowlist_is_closed(
        self, monkeypatch, env, raw
    ):
        if env is not None:
            monkeypatch.setenv("ENV", env)
        if raw is not None:
            monkeypatch.setenv("ALLOWED_EMAILS", raw)
        assert not self.allowed("me@example.com")
        assert not self.allowed(None)

    @pytest.mark.parametrize("env", ["dev", "prod"])
    def test_a_set_allowlist_applies_in_dev_too(self, monkeypatch, env):
        monkeypatch.setenv("ENV", env)
        monkeypatch.setenv("ALLOWED_EMAILS", "me@example.com")
        assert self.allowed("me@example.com")
        assert not self.allowed("stranger@example.com")

    @pytest.mark.parametrize(
        "email", ["me@example.com", "ME@EXAMPLE.COM", "other@example.com"]
    )
    def test_listed_emails_match_case_insensitively(self, monkeypatch, email):
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.setenv("ALLOWED_EMAILS", " Me@Example.com ,other@example.com,")
        assert self.allowed(email)

    @pytest.mark.parametrize(
        "email",
        [
            None,
            "",
            "stranger@example.com",
            "me@example.co",
            "me@example.com.evil.com",
            "evil-me@example.com",
            "me@example",
            "me",
            "example.com",
            "me@example.com,other@example.com",
            "me@example.com ",
            " me@example.com",
        ],
    )
    def test_only_exact_matches_are_allowed(self, monkeypatch, email):
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.setenv("ALLOWED_EMAILS", "me@example.com,other@example.com")
        assert not self.allowed(email)


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_deployed_environments_set_an_allowlist(env):
    """Without it a deployed app refuses everyone, so it must stay in config."""
    import re
    from pathlib import Path

    manifest = Path(__file__).parent.parent / "k8s" / env / "configmap-env.yaml"
    match = re.search(r'^\s+ALLOWED_EMAILS:\s*"([^"]*)"', manifest.read_text(), re.M)
    assert match is not None
    assert "ethanpswan@gmail.com" in match.group(1).split(",")


@pytest.mark.db
class TestTheme:
    def test_pages_carry_both_themes(self, client, db_connection):
        cash = create_account(db_connection, WS, "Cash", RecordType.ASSET)
        upsert_amounts(db_connection, WS, date(2026, 9, 1), {cash.id: Decimal("1")})
        db_connection.commit()
        login(client)
        for path in (PAGES, f"{PAGES}/accounts", f"{PAGES}/accounts/{cash.id}/edit"):
            text = client.get(path).text
            assert "color-scheme: light" in text, path
            assert "@media (prefers-color-scheme: dark)" in text, path
            assert "color-scheme: dark" in text, path
        login_page = client.get("/login").text
        assert "color-scheme: light" in login_page
        assert "color-scheme: dark" in login_page

    def test_templates_name_tokens_not_colors(self):
        """Page templates take their colors from base.html's tokens, so light
        and dark stay in step. base.html defines them."""
        import re
        from importlib import resources

        templates = resources.files("asset_manager.web").joinpath("templates")
        pages = [
            t
            for t in templates.iterdir()
            if t.name.endswith(".html") and t.name != "base.html"
        ]
        assert len(pages) >= 4
        for page in pages:
            colors = re.findall(
                r"#[0-9A-Fa-f]{6}\b|#[0-9A-Fa-f]{3}\b", page.read_text()
            )
            assert colors == [], page.name

    def test_dashboard_retheme_script_targets_plotly(self, client, db_connection):
        cash = create_account(db_connection, WS, "Cash", RecordType.ASSET)
        upsert_amounts(db_connection, WS, date(2026, 9, 1), {cash.id: Decimal("1")})
        db_connection.commit()
        login(client)
        text = client.get(PAGES).text
        assert "Plotly.react" in text
        assert "matchMedia('(prefers-color-scheme: dark)')" in text
        assert "getComputedStyle" in text


def _figure(text: str) -> dict:
    """The Plotly figure the dashboard embeds."""
    import json

    start = text.index("const figure = ") + len("const figure = ")
    end = text.index(";\n", start)
    return json.loads(text[start:end])


@pytest.mark.db
class TestDashboard:
    def test_empty_state(self, client):
        login(client)
        response = client.get(PAGES)
        assert response.status_code == 200
        assert "Let's get your first net worth on the board." in response.text
        assert f'href="{PAGES}/accounts/new?type=asset"' in response.text
        assert "const figure" not in response.text
        assert "Net worth" not in response.text

    def test_accounts_but_no_snapshot_is_still_empty(self, client, db_connection):
        create_account(db_connection, WS, "Cash", RecordType.ASSET)
        login(client)
        text = client.get(PAGES).text
        assert "Let's get your first net worth on the board." in text
        assert "const figure" not in text

    def test_renders_with_data(self, client, db_connection):
        savings = create_account(db_connection, WS, "Savings Account", RecordType.ASSET)
        upsert_amounts(
            db_connection, WS, date(2026, 9, 1), {savings.id: Decimal("1000")}
        )
        db_connection.commit()
        login(client)
        response = client.get(PAGES)
        assert response.status_code == 200
        assert "Savings Account" in response.text
        assert "$1,000" in response.text

    @pytest.fixture
    def seeded(self, db_connection):
        """Two assets, a card and a computed tax, saved on four dates."""
        from asset_manager.models import AccountCategory, ProportionalFormula

        conn = db_connection
        bank = create_account(
            conn,
            WS,
            "Checking",
            RecordType.ASSET,
            category=AccountCategory.BANK_ACCOUNTS,
        )
        schwab = create_account(
            conn,
            WS,
            "Schwab",
            RecordType.ASSET,
            category=AccountCategory.INVESTMENT_ACCOUNTS,
        )
        card = create_account(
            conn,
            WS,
            "Visa",
            RecordType.LIABILITY,
            category=AccountCategory.CREDIT_CARDS,
        )
        tax = create_account(
            conn,
            WS,
            "Cap gains tax",
            RecordType.LIABILITY,
            ProportionalFormula(rate=Decimal("0.15"), cost_basis=Decimal("0")),
            [schwab.id],
            category=AccountCategory.TAX_LIABILITY,
        )
        rows = {
            date(2025, 1, 10): ("1000", "50000", "100", "7500"),
            date(2026, 6, 1): ("2000", "90000", "300", "13500"),
            date(2026, 9, 20): ("3000", "100000", "400", "15000"),
            date(2026, 10, 24): ("4000", "110000", "500", "16500"),
        }
        for day, amounts in rows.items():
            values = [Decimal(a) for a in amounts]
            upsert_amounts(
                conn, WS, day, dict(zip([bank.id, schwab.id, card.id, tax.id], values))
            )
        conn.commit()
        return {"bank": bank, "schwab": schwab, "card": card, "tax": tax}

    def test_headline(self, client, seeded):
        login(client)
        text = client.get(PAGES).text
        # 4,000 + 110,000 - 500 - 16,500
        assert '<span class="net-worth">$97,000</span>' in text
        # Closest to Sep 24 is Sep 20: 3,000 + 100,000 - 400 - 15,000 = 87,600
        assert "<strong>+$9,400 (+10.7%)</strong> since Sep 20</span>" in text
        assert "Last snapshot Oct 24, 2026" in text
        assert (
            f'<a class="btn btn-primary" href="{PAGES}/accounts">Update balances</a>'
            in text
        )

    def test_one_snapshot_has_no_change_line(self, client, db_connection):
        cash = create_account(db_connection, WS, "Cash", RecordType.ASSET)
        upsert_amounts(db_connection, WS, date(2026, 9, 1), {cash.id: Decimal("5")})
        db_connection.commit()
        login(client)
        text = client.get(PAGES).text
        assert "Last snapshot Sep 1, 2026" in text
        assert " since " not in text

    def test_change_from_zero_has_no_percent(self, client, db_connection):
        cash = create_account(db_connection, WS, "Cash", RecordType.ASSET)
        upsert_amounts(db_connection, WS, date(2025, 8, 1), {cash.id: Decimal("0")})
        upsert_amounts(db_connection, WS, date(2026, 9, 1), {cash.id: Decimal("5")})
        db_connection.commit()
        login(client)
        text = client.get(PAGES).text
        # A different year from the latest snapshot's, so it is named.
        assert "<strong>+$5</strong> since Aug 1, 2025</span>" in text

    def test_category_key_and_columns(self, client, seeded):
        login(client)
        text = client.get(PAGES).text
        for label, amount in [
            ("Investment Accounts", "$110,000"),
            ("Bank Accounts", "$4,000"),
            ("Tax Liability", "$16,500"),
            ("Credit Cards", "$500"),
        ]:
            assert f"{label} {amount}" in text
        assert text.index("Investment Accounts $110,000") < text.index(
            "Bank Accounts $4,000"
        )
        bars = [t for t in _figure(text)["data"] if t["type"] == "bar"]
        assert [(t["name"], t["y"], t["meta"]["color"]) for t in bars] == [
            ("Investment Accounts", [110000.0], "var(--asset)"),
            ("Bank Accounts", [4000.0], "var(--asset-2)"),
            ("Tax Liability", [16500.0], "var(--liability)"),
            ("Credit Cards", [500.0], "var(--liability-2)"),
        ]

    def test_cards_list_accounts_under_categories(self, client, seeded):
        login(client)
        text = client.get(PAGES).text
        assets = text[
            text.index("<h2>Assets</h2>") : text.index("<h2>Liabilities</h2>")
        ]
        liabilities = text[text.index("<h2>Liabilities</h2>") : text.index("</main>")]
        assert '<span class="total">$114,000</span>' in assets
        assert assets.index("Bank Accounts") < assets.index("Checking")
        assert assets.index("Checking") < assets.index("Investment Accounts")
        assert '<span class="total">$17,000</span>' in liabilities
        assert "15% of gains, computed" in liabilities
        assert "$97,000" not in liabilities

    def test_range_defaults_to_one_year(self, client, seeded):
        login(client)
        text = client.get(PAGES).text
        assert f'<a href="{PAGES}?range=1y" aria-current="true">1Y</a>' in text
        assert f'<a href="{PAGES}?range=6m">6M</a>' in text
        assert f'<a href="{PAGES}?range=all">All</a>' in text
        dates = _figure(text)["data"][0]["x"]
        assert dates == ["2026-06-01", "2026-09-20", "2026-10-24"]

    def test_range_toggle(self, client, seeded):
        login(client)
        text = client.get(f"{PAGES}?range=6m").text
        assert f'<a href="{PAGES}?range=6m" aria-current="true">6M</a>' in text
        assert f'<a href="{PAGES}?range=1y">1Y</a>' in text
        assert _figure(text)["data"][0]["x"] == [
            "2026-06-01",
            "2026-09-20",
            "2026-10-24",
        ]

        text = client.get(f"{PAGES}?range=all").text
        assert f'<a href="{PAGES}?range=all" aria-current="true">All</a>' in text
        assert _figure(text)["data"][0]["x"] == [
            "2025-01-10",
            "2026-06-01",
            "2026-09-20",
            "2026-10-24",
        ]

    @pytest.mark.parametrize("value", ["bogus", "6M", "", "1y%00"])
    def test_an_invalid_range_falls_back_to_one_year(self, client, seeded, value):
        login(client)
        response = client.get(PAGES, params={"range": value})
        assert response.status_code == 200
        assert f'<a href="{PAGES}?range=1y" aria-current="true">1Y</a>' in response.text
        assert len(_figure(response.text)["data"][0]["x"]) == 3

    def test_the_range_leaves_headline_and_columns_alone(self, client, seeded):
        login(client)
        short = client.get(f"{PAGES}?range=6m").text
        full = client.get(f"{PAGES}?range=all").text
        for text in (short, full):
            assert "<strong>+$9,400 (+10.7%)</strong> since Sep 20" in text
        bars = [[t["y"] for t in _figure(x)["data"][3:]] for x in (short, full)]
        assert bars[0] == bars[1]

    def test_retired_accounts_are_excluded(self, client, db_connection, seeded):
        retire_account(db_connection, WS, seeded["bank"].id, date(2026, 10, 25))
        login(client)
        text = client.get(PAGES).text
        cards = text[text.index("<h2>Assets</h2>") : text.index("</main>")]
        assert "Checking" not in cards
        assert "Bank Accounts" not in cards
        assert '<span class="total">$110,000</span>' in cards
        # Its row is still part of the latest snapshot, so the chart keeps it
        # until the next save; the columns still meet the lines' ends.
        bars = {t["name"]: t["y"] for t in _figure(text)["data"] if t["type"] == "bar"}
        assert bars["Bank Accounts"] == [4000.0]

    def test_retired_before_the_latest_snapshot_leaves_no_trace(
        self, client, db_connection, seeded
    ):
        conn = db_connection
        retire_account(conn, WS, seeded["bank"].id, date(2026, 10, 24))
        ids = [seeded[k].id for k in ("schwab", "card", "tax")]
        upsert_amounts(
            conn,
            WS,
            date(2026, 10, 25),
            dict(zip(ids, [Decimal("110000"), Decimal("500"), Decimal("16500")])),
        )
        conn.commit()
        login(client)
        text = client.get(PAGES).text
        assert "Checking" not in text
        assert "Bank Accounts" not in text
        assert '<span class="net-worth">$93,000</span>' in text

    def test_account_names_are_escaped(self, client, db_connection):
        evil = create_account(db_connection, WS, "<b>bold</b>", RecordType.ASSET)
        upsert_amounts(db_connection, WS, date(2026, 9, 1), {evil.id: Decimal("5")})
        db_connection.commit()
        login(client)
        text = client.get(PAGES).text
        assert "<b>bold</b>" not in text
        assert "&lt;b&gt;bold&lt;/b&gt;" in text

    def test_only_this_workspaces_snapshots_count(self, client, db_connection, seeded):
        """Another workspace's later snapshot moves nothing here."""
        with db_connection.cursor() as cur:
            cur.execute("INSERT INTO workspaces (name) VALUES ('Other') RETURNING id")
            row = cur.fetchone()
        assert row is not None
        other = create_account(db_connection, row[0], "Elsewhere", RecordType.ASSET)
        upsert_amounts(
            db_connection, row[0], date(2026, 12, 1), {other.id: Decimal("123456")}
        )
        db_connection.commit()
        login(client)
        text = client.get(PAGES).text
        assert "Last snapshot Oct 24, 2026" in text
        assert '<span class="net-worth">$97,000</span>' in text
        assert "Elsewhere" not in text


def test_format_percent():
    from asset_manager.web.accounts_routes import format_percent

    assert format_percent(Decimal("0.15")) == "15"
    assert format_percent(Decimal("0.325")) == "32.5"
    assert format_percent(Decimal("0")) == "0"
    assert format_percent(Decimal("1")) == "100"


def test_account_rows_view_model():
    from asset_manager.models import ProportionalFormula
    from asset_manager.web.accounts_routes import account_rows

    schwab = Account(id=1, name="Schwab", type=RecordType.ASSET)
    tax = Account(
        id=2,
        name="Cap Gains Tax",
        type=RecordType.LIABILITY,
        formula=ProportionalFormula(rate=Decimal("0.15"), cost_basis=Decimal("70634")),
        input_ids=[1],
    )
    old = Account(id=3, name="Old", type=RecordType.ASSET, retired_at=date(2026, 1, 1))
    latest = [
        Record(
            date=date(2026, 9, 1),
            account_id=1,
            type=RecordType.ASSET,
            description="Schwab",
            amount=Decimal("163202.77"),
        ),
        Record(
            date=date(2026, 9, 1),
            account_id=2,
            type=RecordType.LIABILITY,
            description="Cap Gains Tax",
            amount=Decimal("13885.32"),
        ),
    ]

    rows = account_rows([schwab, tax, old], latest)

    assert rows[0] == {
        "id": 1,
        "name": "Schwab",
        "type": "asset",
        "category": None,
        "computed": False,
        "formula": None,
        "input_ids": [],
        "amount": "163202.77",
        "amount_display": "163,202.77",
        "basis_display": "",
        "retired": False,
        "retired_at": None,
        "formula_text": "",
        "value_display": "$163,202.77",
        "was_display": "$163,202.77",
        "retired_display": None,
    }
    assert rows[1]["computed"] is True
    assert rows[1]["formula"] == {
        "kind": "proportional",
        "rate": "0.15",
        "cost_basis": "70634",
    }
    assert rows[1]["basis_display"] == "70,634.00"
    assert rows[1]["formula_text"] == "15% × (Schwab − basis)"
    assert rows[1]["value_display"] == "$13,885.32"
    assert rows[1]["was_display"] == "$13,885.32"
    assert rows[2]["retired"] is True
    assert rows[2]["retired_at"] == "2026-01-01"
    assert rows[2]["retired_display"] == "Jan 1, 2026"
    assert rows[2]["amount"] is None
    assert rows[2]["amount_display"] == ""
    # No row on the latest date: nothing to show, and nothing to have been.
    assert rows[2]["value_display"] == "—"
    assert rows[2]["was_display"] == "nothing yet"


def test_was_and_value_display_show_negative_amounts_as_money():
    from asset_manager.web.accounts_routes import account_rows

    card = Account(id=1, name="Card", type=RecordType.LIABILITY)
    latest = [
        Record(
            date=date(2026, 9, 1),
            account_id=1,
            type=RecordType.LIABILITY,
            description="Card",
            amount=Decimal("-63.30"),
        )
    ]
    (row,) = account_rows([card], latest)
    assert row["was_display"] == "-$63.30"
    assert row["value_display"] == "-$63.30"
    assert row["amount_display"] == "-63.30"


def test_snapshot_line():
    from asset_manager.web.accounts_routes import snapshot_line

    today_ = date(2026, 10, 26)
    head = "Saving writes today's snapshot, Oct 26, 2026."
    assert snapshot_line(today_, None) == f"{head} Nothing saved yet."
    assert (
        snapshot_line(today_, today_)
        == f"{head} Last saved today; saving again replaces it."
    )
    assert snapshot_line(today_, date(2026, 10, 24)) == f"{head} Last saved Oct 24."
    assert (
        snapshot_line(today_, date(2025, 12, 31)) == f"{head} Last saved Dec 31, 2025."
    )
    assert (
        snapshot_line(date(2027, 1, 2), date(2026, 9, 1))
        == "Saving writes today's snapshot, Jan 2, 2027. Last saved Sep 1, 2026."
    )


def test_section_view_totals_skip_retired_and_missing_amounts():
    from asset_manager.web.accounts_routes import saved_total, section_view

    def row(name, category, amount, retired=False):
        return {
            "name": name,
            "category": category,
            "amount": amount,
            "retired": retired,
        }

    rows = [
        row("Chase", "bank_accounts", "100.10"),
        row("Ally", "bank_accounts", "-0.10"),
        row("Old", "bank_accounts", "999", retired=True),
        row("New", "investment_accounts", None),
        row("House", None, "400000"),
    ]
    section = section_view("asset", "Assets", rows)

    assert section["kind"] == "asset"
    assert section["title"] == "Assets"
    assert section["total"] == "$400,100.00"
    assert [(g["label"], g["subtotal"]) for g in section["groups"]] == [
        ("Bank Accounts", "$100.00"),
        ("Investment Accounts", "$0.00"),
        ("Uncategorized", "$400,000.00"),
    ]
    assert saved_total([]) == Decimal("0")
    assert saved_total(rows) == Decimal("400100.00")


def test_category_groups_orders_categories_and_puts_uncategorized_last():
    from asset_manager.web.accounts_routes import category_groups

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
    assert [g["retired"] for g in groups] == [False, False, False]
    assert category_groups([row("Gone", "credit_cards", retired=True)])[0]["retired"]


@pytest.mark.db
class TestAccountsPage:
    def test_empty_state(self, client):
        login(client)
        response = client.get(f"{PAGES}/accounts")
        assert response.status_code == 200
        assert "No accounts yet" in response.text

    def test_renders_rows_and_embeds_json(self, client, db_connection):
        from asset_manager.models import ProportionalFormula

        schwab = create_account(db_connection, WS, "Schwab Trading", RecordType.ASSET)
        create_account(
            db_connection,
            WS,
            "Cap Gains Tax",
            RecordType.LIABILITY,
            ProportionalFormula(rate=Decimal("0.15"), cost_basis=Decimal("100")),
            [schwab.id],
        )
        old = create_account(db_connection, WS, "Old 401k", RecordType.ASSET)
        retire_account(db_connection, WS, old.id, date(2026, 1, 1))
        upsert_amounts(
            db_connection, WS, date(2026, 9, 1), {schwab.id: Decimal("1000")}
        )
        db_connection.commit()
        login(client)

        response = client.get(f"{PAGES}/accounts")

        assert response.status_code == 200
        text = response.text
        assert 'id="accounts-data"' in text
        assert 'value="1,000.00"' in text
        assert "Cap Gains Tax" in text
        assert "Show retired (1)" in text
        assert "Last saved Sep 1" in text
        # The save bar's hooks the script updates
        assert 'id="dirty-status"' in text
        assert 'id="save-label"' in text
        assert f'href="{PAGES}/accounts/{schwab.id}/edit"' in text

    def test_redirects_when_logged_out(self, client):
        response = client.get(f"{PAGES}/accounts", follow_redirects=False)
        assert response.status_code == 302

    def test_rows_are_alphabetical_with_retired_last(self, client, db_connection):
        import re

        create_account(db_connection, WS, "zeta", RecordType.ASSET)
        old = create_account(db_connection, WS, "Alpha", RecordType.ASSET)
        create_account(db_connection, WS, "beta", RecordType.ASSET)
        retire_account(db_connection, WS, old.id, date(2026, 1, 1))
        login(client)
        text = client.get(f"{PAGES}/accounts").text
        names = re.findall(
            r'class="account-name" href="/workspaces/1/accounts/\d+/edit">([^<]+)</a>',
            text,
        )
        assert names == ["beta", "zeta", "Alpha"]

    def test_rows_sit_under_category_subheadings(self, client, db_connection):
        import re

        from asset_manager.models import AccountCategory

        create_account(db_connection, WS, "Mystery", RecordType.ASSET)
        create_account(
            db_connection,
            WS,
            "Chase",
            RecordType.ASSET,
            category=AccountCategory.BANK_ACCOUNTS,
        )
        create_account(
            db_connection,
            WS,
            "Visa",
            RecordType.LIABILITY,
            category=AccountCategory.CREDIT_CARDS,
        )
        login(client)
        text = client.get(f"{PAGES}/accounts").text
        cells = re.findall(
            r'<div class="group-head"><span>([^<]+)</span>'
            r'|class="account-name" href="/workspaces/1/accounts/\d+/edit">([^<]+)</a>',
            text,
        )
        assert [heading or name for heading, name in cells] == [
            "Bank Accounts",
            "Chase",
            "Uncategorized",
            "Mystery",
            "Credit Cards",
            "Visa",
        ]
        assert 'data-group="asset:bank_accounts"' in text

    def test_header_says_today_when_latest_snapshot_is_today(
        self, client, db_connection
    ):
        from asset_manager.clock import today

        cash = create_account(db_connection, WS, "Cash", RecordType.ASSET)
        upsert_amounts(db_connection, WS, today(TZ), {cash.id: Decimal("1")})
        db_connection.commit()
        login(client)
        text = client.get(f"{PAGES}/accounts").text
        assert 'id="snapshot-saved" data-today="1"' in text
        assert "Last saved today; saving again replaces it." in text

    def test_header_carries_date_when_latest_snapshot_is_older(
        self, client, db_connection
    ):
        cash = create_account(db_connection, WS, "Cash", RecordType.ASSET)
        upsert_amounts(db_connection, WS, date(2026, 9, 1), {cash.id: Decimal("1")})
        db_connection.commit()
        login(client)
        text = client.get(f"{PAGES}/accounts").text
        assert 'id="snapshot-saved" data-today="0"' in text
        assert "Last saved Sep 1" in text
        assert "Last saved today" not in text

    def test_snapshot_line_with_nothing_saved(self, client, db_connection):
        create_account(db_connection, WS, "Cash", RecordType.ASSET)
        login(client)
        text = client.get(f"{PAGES}/accounts").text
        assert "Nothing saved yet." in text
        assert 'data-today="0"' in text

    def test_edited_rows_carry_their_saved_value_as_was(self, client, db_connection):
        import re

        from asset_manager.models import ProportionalFormula

        schwab = create_account(db_connection, WS, "Schwab", RecordType.ASSET)
        tax = create_account(
            db_connection,
            WS,
            "Tax",
            RecordType.LIABILITY,
            ProportionalFormula(rate=Decimal("0.15"), cost_basis=Decimal("100")),
            [schwab.id],
        )
        new = create_account(db_connection, WS, "Brand New", RecordType.ASSET)
        upsert_amounts(
            db_connection,
            WS,
            date(2026, 9, 1),
            {schwab.id: Decimal("2140"), tax.id: Decimal("306")},
        )
        db_connection.commit()
        login(client)
        text = client.get(f"{PAGES}/accounts").text

        def was(account_id):
            found = re.findall(
                rf'<span class="was" data-account-id="{account_id}" hidden>([^<]*)</span>',
                text,
            )
            assert len(found) == 1, account_id
            return found[0]

        # Hidden until the script sees an edit; one per row, plain or computed.
        assert was(schwab.id) == "was $2,140.00"
        assert was(tax.id) == "was $306.00"
        assert was(new.id) == "was nothing yet"
        # The computed row shows its saved value, labelled, until recomputed.
        assert re.search(
            rf'<span class="computed-amount" data-account-id="{tax.id}">\$306.00</span>\s*'
            r'<span class="computed-label">computed</span>',
            text,
        )
        assert "15% × (Schwab − basis)" in text
        assert re.search(
            rf'<input class="basis-input" data-field="basis" data-account-id="{tax.id}"\s+'
            r'value="100.00"',
            text,
        )

    def test_plain_rows_get_one_money_input(self, client, db_connection):
        import re

        cash = create_account(db_connection, WS, "Cash", RecordType.ASSET)
        upsert_amounts(db_connection, WS, date(2026, 9, 1), {cash.id: Decimal("12.5")})
        db_connection.commit()
        login(client)
        text = client.get(f"{PAGES}/accounts").text
        inputs = re.findall(r'<input class="money-input[^"]*"[^>]*>', text)
        assert len(inputs) == 1
        (tag,) = inputs
        assert 'aria-label="Amount for Cash"' in tag
        assert 'value="12.50"' in tag
        assert 'data-field="amount"' in tag
        assert f'data-account-id="{cash.id}"' in tag
        assert 'inputmode="decimal"' in tag
        # Nothing is edited when the page loads.
        assert "edited" not in tag

    def test_save_bar_starts_clean_with_the_saved_net_worth(
        self, client, db_connection
    ):
        from asset_manager.models import AccountCategory

        cash = create_account(
            db_connection,
            WS,
            "Cash",
            RecordType.ASSET,
            category=AccountCategory.BANK_ACCOUNTS,
        )
        house = create_account(db_connection, WS, "House", RecordType.ASSET)
        card = create_account(db_connection, WS, "Card", RecordType.LIABILITY)
        old = create_account(db_connection, WS, "Old", RecordType.ASSET)
        upsert_amounts(
            db_connection,
            WS,
            date(2026, 9, 1),
            {
                cash.id: Decimal("1000.25"),
                house.id: Decimal("400000"),
                card.id: Decimal("250.25"),
                old.id: Decimal("5000"),
            },
        )
        retire_account(db_connection, WS, old.id, date(2026, 9, 2))
        db_connection.commit()
        login(client)
        text = client.get(f"{PAGES}/accounts").text

        assert (
            '<strong id="dirty-status" class="clean">No unsaved changes</strong>'
            in text
        )
        # Retired accounts count for nothing, as in a save.
        assert 'Net worth <span id="net-worth">$400,750.00</span>' in text
        assert '<span id="net-change" hidden></span>' in text
        assert '<span class="total">$401,000.25</span>' in text
        assert '<span class="total">$250.25</span>' in text
        assert (
            '<div class="group-head"><span>Bank Accounts</span><span>$1,000.25</span></div>'
            in text
        )
        assert 'id="discard-button"' in text
        assert ">Save snapshot</span>" in text

    def test_cards_link_to_add_each_type(self, client, db_connection):
        create_account(db_connection, WS, "Cash", RecordType.ASSET)
        login(client)
        text = client.get(f"{PAGES}/accounts").text
        assert 'class="card section-asset"' in text
        assert 'class="card section-liability"' in text
        assert f'href="{PAGES}/accounts/new?type=asset">+ Add</a>' in text
        assert f'href="{PAGES}/accounts/new?type=liability">+ Add</a>' in text

    def test_retired_rows_hide_behind_the_toggle(self, client, db_connection):
        import re

        from asset_manager.models import AccountCategory

        create_account(db_connection, WS, "Cash", RecordType.ASSET)
        gone = create_account(
            db_connection,
            WS,
            "Gone Card",
            RecordType.LIABILITY,
            category=AccountCategory.CREDIT_CARDS,
        )
        retire_account(db_connection, WS, gone.id, date(2026, 3, 4))
        db_connection.commit()
        login(client)
        text = client.get(f"{PAGES}/accounts").text

        assert '<input type="checkbox" id="show-retired"> Show retired (1)' in text
        row = re.search(
            rf'<div class="row account-row retired-row" data-account-id="{gone.id}">'
            r"(.*?)\n                </div>",
            text,
            re.S,
        )
        assert row is not None
        assert "Retired Mar 4, 2026" in row.group(1)
        # A retired row has nothing to edit and no "was" line.
        assert "<input" not in row.group(1)
        assert 'class="was"' not in row.group(1)
        # A group with only retired rows hides with them.
        assert 'class="group retired-row" data-group="liability:credit_cards"' in text
        assert 'class="group" data-group="asset:uncategorized"' in text
        # The stylesheet hides them until the toggle adds the body class.
        assert re.search(r"\.retired-row \{\s*display: none;", text)
        assert "body.show-retired .row.retired-row" in text
        assert "classList.toggle('show-retired', toggle.checked)" in text

    def test_no_retired_toggle_without_retired_accounts(self, client, db_connection):
        create_account(db_connection, WS, "Cash", RecordType.ASSET)
        login(client)
        text = client.get(f"{PAGES}/accounts").text
        assert "Show retired" not in text
        assert 'id="show-retired"' not in text

    def test_script_hooks_exist_in_the_markup(self, client, db_connection):
        """Every element the script looks up by id or data-field is on the
        page, so a markup change cannot silently disconnect the script."""
        import re

        from asset_manager.models import ProportionalFormula

        schwab = create_account(db_connection, WS, "Schwab", RecordType.ASSET)
        create_account(
            db_connection,
            WS,
            "Tax",
            RecordType.LIABILITY,
            ProportionalFormula(rate=Decimal("0.15"), cost_basis=Decimal("1")),
            [schwab.id],
        )
        old = create_account(db_connection, WS, "Old", RecordType.ASSET)
        retire_account(db_connection, WS, old.id, date(2026, 1, 1))
        db_connection.commit()
        login(client)
        text = client.get(f"{PAGES}/accounts").text
        markup = text.split("<script")[0]

        ids = set(re.findall(r"getElementById\('([^']+)'\)", text))
        assert {"dirty-status", "net-worth", "net-change", "save-button"} <= ids
        for element_id in ids:
            assert f'id="{element_id}"' in text, element_id
        assert "querySelectorAll('input[data-field=\"amount\"]')" in text
        assert "querySelectorAll('input[data-field=\"basis\"]')" in text
        assert 'data-field="amount"' in markup
        assert 'data-field="basis"' in markup
        for hook in (
            'class="was"',
            'class="computed-amount"',
            'class="group-head"',
            'class="total"',
            "data-group=",
        ):
            assert hook in markup, hook
        # The edited state is the shared component's class.
        assert "classList.toggle('edited', dirty)" in text
        assert "sessionStorage.setItem(STORAGE_KEY" in text
        assert f"fetch('{PAGES}/snapshots'" in text
        assert "res.status === 401" in text and "'/login'" in text


@pytest.mark.db
class TestSaveSnapshot:
    def test_writes_computed_rows(self, client, db_connection):
        from asset_manager.models import ProportionalFormula
        from asset_manager.repository import get_all_records

        schwab = create_account(db_connection, WS, "Schwab", RecordType.ASSET)
        tax = create_account(
            db_connection,
            WS,
            "Tax",
            RecordType.LIABILITY,
            ProportionalFormula(rate=Decimal("0.15"), cost_basis=Decimal("100")),
            [schwab.id],
        )
        login(client)

        response = client.post(
            f"{PAGES}/snapshots",
            json={
                "values": {str(schwab.id): "1000.00"},
                "cost_bases": {str(tax.id): "400.00"},
            },
            headers={"Accept": "application/json"},
        )

        assert response.status_code == 200
        assert response.json() == {"date": today(TZ).isoformat(), "count": 2}
        rows = {(r.description, r.amount) for r in get_all_records(db_connection, WS)}
        assert rows == {("Schwab", Decimal("1000.00")), ("Tax", Decimal("90.00"))}

    def test_rounds_more_than_two_decimals_half_up_on_the_server(
        self, client, db_connection
    ):
        """The server, not the browser, decides the final cent (ROUND_HALF_UP)."""
        from asset_manager.repository import get_all_records

        schwab = create_account(db_connection, WS, "Schwab", RecordType.ASSET)
        login(client)

        response = client.post(
            f"{PAGES}/snapshots",
            json={"values": {str(schwab.id): "10.005"}, "cost_bases": {}},
            headers={"Accept": "application/json"},
        )

        assert response.status_code == 200
        records = get_all_records(db_connection, WS)
        assert [r.amount for r in records] == [Decimal("10.01")]

    def test_oversized_amount_returns_400_and_writes_nothing(
        self, client, db_connection
    ):
        from asset_manager.repository import get_all_records

        schwab = create_account(db_connection, WS, "Schwab", RecordType.ASSET)
        login(client)

        response = client.post(
            f"{PAGES}/snapshots",
            json={"values": {str(schwab.id): "1e999"}, "cost_bases": {}},
            headers={"Accept": "application/json"},
        )

        assert response.status_code == 400
        assert get_all_records(db_connection, WS) == []

    def test_missing_value_returns_400_and_writes_nothing(self, client, db_connection):
        from asset_manager.repository import get_all_records

        create_account(db_connection, WS, "Schwab", RecordType.ASSET)
        create_account(db_connection, WS, "Cash", RecordType.ASSET)
        login(client)

        response = client.post(
            f"{PAGES}/snapshots", json={"values": {}, "cost_bases": {}}
        )

        assert response.status_code == 400
        assert "Missing value for" in response.json()["error"]
        assert get_all_records(db_connection, WS) == []

    def test_requires_login(self, client):
        response = client.post(
            f"{PAGES}/snapshots",
            json={"values": {}},
            headers={"Accept": "application/json"},
        )
        assert response.status_code == 401


@pytest.mark.db
class TestApi:
    def _setup(self, conn):
        from asset_manager.models import ProportionalFormula

        schwab = create_account(conn, WS, "Schwab", RecordType.ASSET)
        cash = create_account(conn, WS, "Cash", RecordType.ASSET)
        tax = create_account(
            conn,
            WS,
            "Tax",
            RecordType.LIABILITY,
            ProportionalFormula(rate=Decimal("0.15"), cost_basis=Decimal("100")),
            [schwab.id],
        )
        old = create_account(conn, WS, "Old", RecordType.ASSET)
        upsert_amounts(
            conn,
            WS,
            date(2026, 9, 1),
            {
                schwab.id: Decimal("1000"),
                cash.id: Decimal("50"),
                tax.id: Decimal("135"),
                old.id: Decimal("7"),
            },
        )
        retire_account(conn, WS, old.id, date(2026, 9, 2))
        conn.commit()
        return schwab, cash, tax

    def test_accounts_lists_active_accounts_with_latest_amounts(
        self, client, db_connection
    ):
        schwab, cash, tax = self._setup(db_connection)
        login(client)

        response = client.get(ACCOUNTS)

        assert response.status_code == 200
        body = response.json()
        assert body["as_of"] == "2026-09-01"
        by_name = {a["name"]: a for a in body["accounts"]}
        assert set(by_name) == {"Schwab", "Cash", "Tax"}
        assert by_name["Schwab"] == {
            "id": schwab.id,
            "name": "Schwab",
            "type": "asset",
            "category": None,
            "computed": False,
            "formula": None,
            "input_ids": [],
            "amount": "1000.00",
        }
        assert by_name["Tax"]["computed"] is True
        assert by_name["Tax"]["input_ids"] == [schwab.id]
        assert by_name["Tax"]["formula"]["cost_basis"] == "100"

    def test_accounts_with_no_snapshots(self, client, db_connection):
        create_account(db_connection, WS, "Cash", RecordType.ASSET)
        login(client)
        body = client.get(ACCOUNTS).json()
        assert body["as_of"] is None
        assert [a["amount"] for a in body["accounts"]] == [None]

    def test_snapshot_merges_with_latest_and_reports_sources(
        self, client, db_connection
    ):
        schwab, cash, tax = self._setup(db_connection)
        login(client)

        response = client.post(SNAPSHOTS, json={"values": {str(schwab.id): "2000"}})

        assert response.status_code == 200
        body = response.json()
        assert body["date"] == today(TZ).isoformat()
        assert body["count"] == 3
        got = {a["name"]: (a["amount"], a["source"]) for a in body["accounts"]}
        assert got == {
            "Schwab": ("2000.00", "updated"),
            "Cash": ("50.00", "carried_forward"),
            "Tax": ("285.00", "computed"),
        }

    def test_snapshot_error_returns_400_and_writes_nothing(self, client, db_connection):
        from asset_manager.repository import get_all_records

        _, _, tax = self._setup(db_connection)
        before = get_all_records(db_connection, WS)
        login(client)

        response = client.post(SNAPSHOTS, json={"values": {str(tax.id): "1"}})

        assert response.status_code == 400
        assert "is computed" in response.json()["error"]
        assert get_all_records(db_connection, WS) == before

    def test_require_login_without_json_accept_header(self, client):
        assert client.get(ACCOUNTS).status_code == 401
        assert client.post(SNAPSHOTS, json={}).status_code == 401

    def test_snapshot_accepts_json_numbers_without_float_error(
        self, client, db_connection
    ):
        schwab, cash, _ = self._setup(db_connection)
        login(client)
        response = client.post(
            SNAPSHOTS,
            json={"values": {str(schwab.id): 2000.1, str(cash.id): 0.29}},
        )
        assert response.status_code == 200
        got = {a["name"]: a["amount"] for a in response.json()["accounts"]}
        assert got["Schwab"] == "2000.10"
        assert got["Cash"] == "0.29"

    @pytest.mark.parametrize(
        ("body", "status"),
        [
            ({"values": {"abc": "1"}}, 422),
            ({"values": {"SCHWAB": "lots"}}, 422),
            ({"values": {"SCHWAB": None}}, 422),
            ({"values": ["SCHWAB", "1"]}, 422),
            ({"values": {"SCHWAB": "NaN"}}, 422),
            ({"values": {"SCHWAB": "Infinity"}}, 422),
            ({"values": {"999999": "1"}}, 400),
            ({"cost_bases": {"TAX": "-Infinity"}}, 422),
        ],
    )
    def test_snapshot_rejects_bad_payloads_and_writes_nothing(
        self, client, db_connection, body, status
    ):
        import json

        from asset_manager.repository import get_account, get_all_records

        schwab, _, tax = self._setup(db_connection)
        text = json.dumps(body)
        text = text.replace("SCHWAB", str(schwab.id)).replace("TAX", str(tax.id))
        before = get_all_records(db_connection, WS)
        login(client)

        response = client.post(
            SNAPSHOTS,
            content=text,
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == status
        assert get_all_records(db_connection, WS) == before
        loaded = get_account(db_connection, WS, tax.id)
        assert loaded is not None and loaded.formula is not None
        assert loaded.formula.cost_basis == Decimal("100")


@pytest.mark.db
def test_api_docs_are_public(client):
    for path in ("/docs", "/redoc"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "/openapi.json" in response.text, path
    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    assert {
        "/api/workspaces/{workspace_id}/accounts",
        "/api/workspaces/{workspace_id}/snapshots",
    } <= set(schema.json()["paths"])


def assert_nothing_written(conn, account_id: int) -> None:
    from asset_manager.repository import get_account, get_all_records

    assert get_all_records(conn, WS) == []
    loaded = get_account(conn, WS, account_id)
    assert loaded is not None and loaded.is_active and loaded.name == "Cash"


@pytest.mark.db
class TestEveryRouteRequiresLogin:
    def test_the_sweep_sees_every_route_family(self, client):
        paths = {path for _, path in protected_routes()}
        assert {
            "/",
            f"{PAGES}/accounts",
            f"{PAGES}/snapshots",
            ACCOUNTS,
            SNAPSHOTS,
            f"{PAGES}/accounts/1/retire",
        } <= paths

    def test_logged_out_requests_are_refused_and_write_nothing(
        self, client, db_connection
    ):
        cash = create_account(db_connection, WS, "Cash", RecordType.ASSET)
        db_connection.commit()
        assert cash.id == 1  # the sweep substitutes 1 for {account_id}

        statuses = sweep(client)

        assert {k: v for k, v in statuses.items() if v != 401} == {}
        assert_nothing_written(db_connection, cash.id)

    def test_pages_redirect_to_login_when_logged_out(self, client):
        for method, path in protected_routes():
            if path.startswith("/api/"):
                continue
            response = client.request(method, path, follow_redirects=False)
            assert response.status_code == 302, (method, path)
            assert response.headers["location"] == "/login"

    def test_cookie_signed_with_another_key_is_refused(self, client):
        forged = URLSafeTimedSerializer("not-the-secret").dumps(USER)
        client.cookies.set("session", forged)
        assert client.get(ACCOUNTS).status_code == 401

    def test_tampered_cookie_is_refused(self, client):
        good = URLSafeTimedSerializer(SECRET).dumps(USER)
        payload, rest = good.split(".", 1)
        client.cookies.set("session", payload[:-1] + "A" + "." + rest)
        assert client.get(ACCOUNTS).status_code == 401

    def test_expired_cookie_is_refused(self, client, monkeypatch):
        import time

        from itsdangerous import TimestampSigner

        from asset_manager.web.auth import SESSION_MAX_AGE

        old = int(time.time()) - SESSION_MAX_AGE - 60
        # A scoped patch: monkeypatch.undo() would also revert the client
        # fixture's environment, including DATABASE_URL.
        with monkeypatch.context() as clock:
            clock.setattr(TimestampSigner, "get_timestamp", lambda self: old)
            cookie = URLSafeTimedSerializer(SECRET).dumps(USER)
        client.cookies.set("session", cookie)
        assert client.get(ACCOUNTS).status_code == 401


@pytest.mark.db
class TestEveryRouteRequiresAnAllowedEmail:
    """A validly signed session is not enough: the email must be allowed."""

    @pytest.fixture
    def cash(self, db_connection):
        # The stranger is a real user and even an owner of the workspace, so
        # the allowlist is the only thing that can refuse them.
        add_user(db_connection, STRANGER, "owner")
        cash = create_account(db_connection, WS, "Cash", RecordType.ASSET)
        db_connection.commit()
        assert cash.id == 1  # the sweep substitutes 1 for {account_id}
        return cash

    @pytest.mark.parametrize(
        ("env", "allowlist", "user"),
        [
            # Another identity user, with the allowlist set as in prod.
            ("prod", USER["email"], STRANGER),
            ("staging", USER["email"], STRANGER),
            # The real user, but the allowlist was lost from config.
            ("prod", None, USER),
            ("prod", "", USER),
            ("staging", None, USER),
            # Dev is only open when the allowlist is blank.
            ("dev", USER["email"], STRANGER),
            # Validly signed, but not a session for any current user.
            ("prod", USER["email"], {k: v for k, v in USER.items() if k != "id"}),
            ("prod", USER["email"], {**USER, "id": 99}),
            ("prod", USER["email"], {**USER, "id": "1"}),
            ("prod", USER["email"], {**USER, "sub": "someone-else"}),
            ("prod", USER["email"], {**STRANGER, "id": USER["id"]}),
        ],
    )
    def test_every_route_refuses_and_writes_nothing(
        self, client, db_connection, monkeypatch, cash, env, allowlist, user
    ):
        monkeypatch.setenv("ENV", env)
        if allowlist is not None:
            monkeypatch.setenv("ALLOWED_EMAILS", allowlist)
        session_for(client, user)

        statuses = sweep(client)

        assert {k: v for k, v in statuses.items() if v != 401} == {}
        assert_nothing_written(db_connection, cash.id)

    def test_the_allowed_user_gets_through_every_route(self, client, monkeypatch, cash):
        """Control: the refusals above are the allowlist, not a broken sweep."""
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.setenv(
            "ALLOWED_EMAILS", f"other@example.com,{USER['email'].upper()}"
        )
        session_for(client, USER)

        statuses = sweep(client)

        assert {k: v for k, v in statuses.items() if v == 401} == {}

    def test_removing_an_email_locks_out_its_live_session(
        self, client, monkeypatch, cash
    ):
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.setenv("ALLOWED_EMAILS", USER["email"])
        session_for(client, USER)
        assert client.get(ACCOUNTS).status_code == 200

        monkeypatch.setenv("ALLOWED_EMAILS", "someone-else@example.com")

        assert set(sweep(client).values()) == {401}

    def test_a_refused_page_request_redirects_to_login(self, client, monkeypatch):
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.setenv("ALLOWED_EMAILS", USER["email"])
        session_for(client, STRANGER)
        response = client.get(f"{PAGES}/accounts", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/login"


@pytest.mark.db
class TestCallback:
    def _use(self, monkeypatch, idp):
        from types import SimpleNamespace

        import asset_manager.web.app as app_module

        monkeypatch.setattr(
            app_module, "get_oauth_client", lambda: SimpleNamespace(idp=idp)
        )

    def _session_cookie(self, response) -> str | None:
        for header in response.headers.get_list("set-cookie"):
            if header.startswith("session="):
                return header
        return None

    def test_login_sets_a_session_that_authenticates(
        self, client, db_connection, monkeypatch
    ):
        self._use(monkeypatch, FakeIdp(token={"userinfo": claims(USER)}))

        response = client.get("/auth/callback", follow_redirects=False)

        assert response.status_code == 302
        assert response.headers["location"] == "/"
        header = self._session_cookie(response)
        assert header is not None
        assert "HttpOnly" in header and "samesite=lax" in header.lower()
        assert "Secure" not in header  # ENV=dev
        assert client.get(ACCOUNTS).status_code == 200

    def test_session_cookie_is_secure_outside_dev(self, client, monkeypatch):
        self._use(monkeypatch, FakeIdp(token={"userinfo": claims(USER)}))
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.setenv("ALLOWED_EMAILS", USER["email"])
        response = client.get("/auth/callback", follow_redirects=False)
        header = self._session_cookie(response)
        assert header is not None and "Secure" in header

    def test_falls_back_to_the_userinfo_endpoint(self, client, monkeypatch):
        self._use(monkeypatch, FakeIdp(token={}, userinfo=claims(USER)))
        response = client.get("/auth/callback", follow_redirects=False)
        assert response.status_code == 302
        assert self._session_cookie(response) is not None

    @pytest.mark.parametrize("email", ["stranger@example.com", None])
    def test_allowlist_refuses_with_403_and_no_session(
        self, client, monkeypatch, email
    ):
        self._use(monkeypatch, FakeIdp(token={"userinfo": claims(USER, email=email)}))
        monkeypatch.setenv("ALLOWED_EMAILS", "me@example.com")

        response = client.get("/auth/callback", follow_redirects=False)

        assert response.status_code == 403
        assert self._session_cookie(response) is None
        assert client.get(ACCOUNTS).status_code == 401

    def test_login_is_refused_outside_dev_without_an_allowlist(
        self, client, monkeypatch
    ):
        self._use(monkeypatch, FakeIdp(token={"userinfo": claims(USER)}))
        monkeypatch.setenv("ENV", "prod")

        response = client.get("/auth/callback", follow_redirects=False)

        assert response.status_code == 403
        assert self._session_cookie(response) is None

    def test_refusal_also_applies_to_the_userinfo_fallback(self, client, monkeypatch):
        self._use(monkeypatch, FakeIdp(token={}, userinfo=claims(STRANGER)))
        monkeypatch.setenv("ALLOWED_EMAILS", USER["email"])

        response = client.get("/auth/callback", follow_redirects=False)

        assert response.status_code == 403
        assert self._session_cookie(response) is None

    def test_allowed_email_logs_in_regardless_of_case(self, client, monkeypatch):
        self._use(monkeypatch, FakeIdp(token={"userinfo": claims(USER)}))
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.setenv("ALLOWED_EMAILS", USER["email"].upper())

        response = client.get("/auth/callback", follow_redirects=False)

        assert response.status_code == 302
        assert self._session_cookie(response) is not None

    def test_oauth_error_is_400_with_no_session(self, client, monkeypatch):
        from authlib.integrations.starlette_client import OAuthError

        self._use(monkeypatch, FakeIdp(error=OAuthError(error="access_denied")))

        response = client.get("/auth/callback", follow_redirects=False)

        assert response.status_code == 400
        assert self._session_cookie(response) is None

    def test_logout_clears_the_session(self, client, monkeypatch):
        # Log in through the callback so the client holds the cookie exactly
        # as the server set it; one set by hand is never matched for deletion.
        self._use(monkeypatch, FakeIdp(token={"userinfo": claims(USER)}))
        client.get("/auth/callback", follow_redirects=False)
        assert client.get(ACCOUNTS).status_code == 200

        response = client.get("/logout", follow_redirects=False)
        assert response.status_code == 302
        header = self._session_cookie(response)
        assert header is not None and "Max-Age=0" in header
        assert client.get(ACCOUNTS).status_code == 401


@pytest.mark.db
class TestAccountForm:
    def test_new_page_presets_type_and_lists_inputs(self, client, db_connection):
        create_account(db_connection, WS, "Schwab", RecordType.ASSET)
        login(client)
        response = client.get(f"{PAGES}/accounts/new?type=liability")
        assert response.status_code == 200
        assert "New liability" in response.text
        assert 'name="input_ids"' in response.text
        assert "Schwab" in response.text

    def test_create_plain_account_redirects_with_flash(self, client, db_connection):
        from asset_manager.repository import get_accounts

        login(client)
        response = client.post(
            f"{PAGES}/accounts",
            data={"name": "Cash", "type": "asset"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == f"{PAGES}/accounts"
        assert [a.name for a in get_accounts(db_connection, WS)] == ["Cash"]
        page = client.get(f"{PAGES}/accounts")
        assert "Added Cash" in page.text

    def test_create_computed_account(self, client, db_connection):
        from asset_manager.repository import get_accounts

        schwab = create_account(db_connection, WS, "Schwab", RecordType.ASSET)
        login(client)
        response = client.post(
            f"{PAGES}/accounts",
            data={
                "name": "Cap Gains Tax",
                "type": "liability",
                "computed": "on",
                "rate_percent": "15",
                "cost_basis": "$70,634.00",
                "input_ids": [str(schwab.id)],
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        tax = [a for a in get_accounts(db_connection, WS) if a.name == "Cap Gains Tax"][
            0
        ]
        assert tax.formula is not None
        assert tax.formula.rate == Decimal("0.15")
        assert tax.formula.cost_basis == Decimal("70634.00")
        assert tax.input_ids == [schwab.id]

    def test_create_duplicate_rerenders_with_error(self, client, db_connection):
        create_account(db_connection, WS, "Cash", RecordType.ASSET)
        login(client)
        response = client.post(
            f"{PAGES}/accounts", data={"name": "Cash", "type": "asset"}
        )
        assert response.status_code == 400
        assert "already exists" in response.text
        assert 'value="Cash"' in response.text

    def test_create_bad_rate_rerenders_with_error(self, client):
        login(client)
        response = client.post(
            f"{PAGES}/accounts",
            data={
                "name": "Tax",
                "type": "liability",
                "computed": "on",
                "rate_percent": "abc",
            },
        )
        assert response.status_code == 400
        assert "Rate must be a number" in response.text

    def test_edit_page_prefills_formula(self, client, db_connection):
        from asset_manager.models import ProportionalFormula

        schwab = create_account(db_connection, WS, "Schwab", RecordType.ASSET)
        tax = create_account(
            db_connection,
            WS,
            "Tax",
            RecordType.LIABILITY,
            ProportionalFormula(rate=Decimal("0.325"), cost_basis=Decimal("100")),
            [schwab.id],
        )
        login(client)
        response = client.get(f"{PAGES}/accounts/{tax.id}/edit")
        assert response.status_code == 200
        assert "Edit liability" in response.text
        assert 'value="32.5"' in response.text
        assert 'value="100.00"' in response.text
        assert re.search(
            rf'value="{schwab.id}" data-amount=""\s+checked', response.text
        )
        # The type is fixed once created: the drawer names it and offers no choice.
        assert 'name="type"' not in response.text

    def test_edit_page_shows_history_newest_first(self, client, db_connection):
        cash = create_account(db_connection, WS, "Cash", RecordType.ASSET)
        upsert_amounts(db_connection, WS, date(2026, 7, 1), {cash.id: Decimal("1000")})
        upsert_amounts(
            db_connection, WS, date(2026, 8, 1), {cash.id: Decimal("1250.50")}
        )
        upsert_amounts(db_connection, WS, date(2026, 9, 1), {cash.id: Decimal("900")})
        db_connection.commit()
        login(client)
        text = client.get(f"{PAGES}/accounts/{cash.id}/edit").text
        history = text[text.index('<details class="drawer-history">') :]
        history = history[: history.index("</details>")]
        assert "History (3 snapshots)" in history
        rows = re.findall(
            r'<div class="history-row"><span>([^<]+)</span><span>([^<]+)</span>',
            history,
        )
        assert rows == [
            ("Sep 1, 2026", "$900.00"),
            ("Aug 1, 2026", "$1,250.50"),
            ("Jul 1, 2026", "$1,000.00"),
        ]

    def test_edit_page_history_empty_state(self, client, db_connection):
        cash = create_account(db_connection, WS, "Cash", RecordType.ASSET)
        login(client)
        text = client.get(f"{PAGES}/accounts/{cash.id}/edit").text
        assert "No snapshots yet" in text

    def test_edit_page_404_for_unknown(self, client):
        login(client)
        assert client.get(f"{PAGES}/accounts/9999/edit").status_code == 404

    def test_update_account(self, client, db_connection):
        from asset_manager.repository import get_account

        cash = create_account(db_connection, WS, "Cash", RecordType.ASSET)
        login(client)
        response = client.post(
            f"{PAGES}/accounts/{cash.id}",
            data={"name": "Cash (SoFi)"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        loaded = get_account(db_connection, WS, cash.id)
        assert loaded is not None and loaded.name == "Cash (SoFi)"

    def test_create_and_change_category(self, client, db_connection):
        from asset_manager.models import AccountCategory
        from asset_manager.repository import get_account_by_name

        login(client)
        response = client.post(
            f"{PAGES}/accounts",
            data={"name": "Visa", "type": "liability", "category": "credit_cards"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        visa = get_account_by_name(db_connection, WS, RecordType.LIABILITY, "Visa")
        assert visa is not None and visa.category == AccountCategory.CREDIT_CARDS

        edit = client.get(f"{PAGES}/accounts/{visa.id}/edit").text
        assert '<option value="credit_cards" selected>Credit Cards</option>' in edit

        client.post(
            f"{PAGES}/accounts/{visa.id}",
            data={"name": "Visa", "category": ""},
            follow_redirects=False,
        )
        db_connection.rollback()
        reloaded = get_account_by_name(db_connection, WS, RecordType.LIABILITY, "Visa")
        assert reloaded is not None and reloaded.category is None

    def test_unknown_category_rerenders_with_error(self, client):
        login(client)
        response = client.post(
            f"{PAGES}/accounts",
            data={"name": "X", "type": "asset", "category": "boats"},
        )
        assert response.status_code == 400
        assert "&#39;boats&#39; is not a category" in response.text

    def test_retire_blocked_by_formula_shows_flash(self, client, db_connection):
        from asset_manager.models import ProportionalFormula

        schwab = create_account(db_connection, WS, "Schwab", RecordType.ASSET)
        create_account(
            db_connection,
            WS,
            "Tax",
            RecordType.LIABILITY,
            ProportionalFormula(rate=Decimal("0.15")),
            [schwab.id],
        )
        login(client)
        response = client.post(
            f"{PAGES}/accounts/{schwab.id}/retire", follow_redirects=False
        )
        assert response.status_code == 303
        page = client.get(f"{PAGES}/accounts")
        assert "Schwab is an input to Tax" in page.text
        edit = client.get(f"{PAGES}/accounts/{schwab.id}/edit")
        assert "Schwab is an input to Tax" in edit.text
        # Blocked: no Retire button at all, just the reason.
        assert f"{schwab.id}/retire" not in edit.text

    def test_retire_nonzero_warns_then_succeeds(self, client, db_connection):
        from asset_manager.repository import get_account

        cash = create_account(db_connection, WS, "Cash", RecordType.ASSET)
        upsert_amounts(db_connection, WS, date(2026, 9, 1), {cash.id: Decimal("5")})
        db_connection.commit()
        login(client)
        edit = client.get(f"{PAGES}/accounts/{cash.id}/edit")
        assert "Last saved at $5.00 on September 1, 2026" in edit.text
        assert "Retire anyway" in edit.text
        assert f'action="{PAGES}/accounts/{cash.id}/retire"' in edit.text
        response = client.post(
            f"{PAGES}/accounts/{cash.id}/retire", follow_redirects=False
        )
        assert response.status_code == 303
        loaded = get_account(db_connection, WS, cash.id)
        assert loaded is not None and loaded.retired_at is not None
        assert "Retired Cash" in client.get(f"{PAGES}/accounts").text

    def test_retire_and_unretire(self, client, db_connection):
        from asset_manager.repository import get_account

        cash = create_account(db_connection, WS, "Cash", RecordType.ASSET)
        login(client)
        client.post(f"{PAGES}/accounts/{cash.id}/retire", follow_redirects=False)
        loaded = get_account(db_connection, WS, cash.id)
        assert loaded is not None and loaded.retired_at == today(TZ)
        assert "Retired Cash" in client.get(f"{PAGES}/accounts").text

        client.post(f"{PAGES}/accounts/{cash.id}/unretire", follow_redirects=False)
        loaded = get_account(db_connection, WS, cash.id)
        assert loaded is not None and loaded.retired_at is None
