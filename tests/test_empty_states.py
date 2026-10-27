"""Empty states (board Y): a new workspace's dashboard, the in-between state
(accounts but no snapshot), and empty Accounts and Cash flows pages."""

import html as html_lib
import re
from datetime import date
from decimal import Decimal

import pytest

from sensibility.accounts import create_account, retire_account
from sensibility.cashflows import create_category as create_flow_category
from sensibility.models import RecordType
from sensibility.repository import upsert_amounts
from sensibility.web.dashboard import getting_started
from tests.support import WS
from tests.web_support import PAGES, STRANGER, add_user, login, session_for

NEW_ACCOUNT = f"{PAGES}/accounts/new?type=asset"
NEW_LIABILITY = f"{PAGES}/accounts/new?type=liability"


def _text(html: str) -> str:
    body = re.sub(r"<style.*?</style>|<script.*?</script>", "", html, flags=re.S)
    return html_lib.unescape(" ".join(re.sub(r"<[^>]+>", " ", body).split()))


def _main(html: str) -> str:
    """The page's content, without the shell (whose nav links to Accounts)."""
    return html.split('<main class="container"', 1)[1]


def _links(html: str) -> list[tuple[str, str]]:
    """(href, text) for each link in the page's content, in order."""
    return [
        (html_lib.unescape(href), " ".join(re.sub(r"<[^>]+>", " ", text).split()))
        for href, text in re.findall(
            r'<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>', _main(html), flags=re.S
        )
    ]


def _as_viewer(client, db_connection):
    add_user(db_connection, STRANGER, role="viewer")
    session_for(client, STRANGER)


# --- the steps, as data ------------------------------------------------------


def test_steps_for_a_workspace_with_no_accounts():
    steps = getting_started(0, "/workspaces/7")
    assert [s["title"] for s in steps] == [
        "Add your accounts",
        "Enter today's balances",
        "Come back now and then",
    ]
    assert [s["done"] for s in steps] == [False, False, False]
    assert [s["action"] for s in steps] == [
        ("+ Add an account", "/workspaces/7/accounts/new?type=asset"),
        None,
        None,
    ]


@pytest.mark.parametrize(("count", "text"), [(1, "1 account"), (3, "3 accounts")])
def test_steps_once_accounts_exist(count, text):
    steps = getting_started(count, "/workspaces/7")
    assert [s["done"] for s in steps] == [True, False, False]
    assert steps[0]["text"].startswith(f"Done: {text} added.")
    assert [s["action"] for s in steps] == [
        None,
        ("Enter balances", "/workspaces/7/accounts"),
        None,
    ]


# --- the dashboard -----------------------------------------------------------


@pytest.mark.db
class TestNewWorkspaceDashboard:
    def test_editor_sees_the_steps_and_add_buttons(self, client):
        login(client)
        response = client.get(PAGES)
        assert response.status_code == 200
        text = _text(response.text)
        assert "Test is new" in text
        assert "Let's get your first net worth on the board." in text
        for title in (
            "1 Add your accounts",
            "2 Enter today's balances",
            "3 Come back now and then",
        ):
            assert title in text
        # Step 1, then each card's button; the asset card's goes to the same
        # form as step 1.
        assert _links(response.text) == [
            (NEW_ACCOUNT, "+ Add an account"),
            (NEW_ACCOUNT, "+ Add an asset"),
            (NEW_LIABILITY, "+ Add a liability"),
        ]
        assert "No assets yet." in text
        assert "No liabilities yet. That's fine; plenty of people have none." in text
        assert f'{PAGES}/accounts"' not in _main(response.text)
        assert "editor" not in text
        assert "const figure" not in response.text

    def test_placeholder_chart_is_hidden_from_screen_readers(self, client):
        login(client)
        html = client.get(PAGES).text
        chart = re.search(
            r'<div class="placeholder-chart" aria-hidden="true">(.*?)</div>',
            html,
            flags=re.S,
        )
        assert chart is not None
        assert "stroke-dasharray" in chart.group(1)
        assert "placeholder-dot" in chart.group(1)
        assert "Your first snapshot starts the line." in chart.group(1)

    def test_viewer_gets_no_buttons(self, client, db_connection):
        _as_viewer(client, db_connection)
        response = client.get(PAGES)
        assert response.status_code == 200
        text = _text(response.text)
        assert "Let's get your first net worth on the board." in text
        assert "An editor hasn't added any accounts yet." in text
        assert "/accounts/new" not in response.text
        assert "+ Add" not in text

    def test_retired_accounts_do_not_count(self, client, db_connection):
        cash = create_account(db_connection, WS, "Cash", RecordType.ASSET)
        retire_account(db_connection, WS, cash.id, date(2026, 1, 1))
        login(client)
        links = _links(client.get(PAGES).text)
        assert links[0] == (NEW_ACCOUNT, "+ Add an account")


@pytest.mark.db
class TestAccountsButNoSnapshot:
    def test_editor_is_sent_to_enter_balances(self, client, db_connection):
        create_account(db_connection, WS, "Cash", RecordType.ASSET)
        create_account(db_connection, WS, "Brokerage", RecordType.ASSET)
        login(client)
        response = client.get(PAGES)
        text = _text(response.text)
        assert "Let's get your first net worth on the board." in text
        assert "✓ Add your accounts Done: 2 accounts added." in text
        # The accounts show, with no amounts yet; liabilities can still be added.
        assert _links(response.text) == [
            (f"{PAGES}/accounts", "Enter balances"),
            (NEW_LIABILITY, "+ Add a liability"),
        ]
        assert "Assets — Uncategorized Brokerage — Cash —" in text
        assert "No liabilities yet." in text

    def test_viewer_is_told_balances_are_coming(self, client, db_connection):
        create_account(db_connection, WS, "Cash", RecordType.ASSET)
        _as_viewer(client, db_connection)
        response = client.get(PAGES)
        text = _text(response.text)
        assert "An editor hasn't entered any balances yet." in text
        assert "Enter balances" not in text
        assert "/accounts/new" not in response.text

    def test_one_snapshot_ends_the_onboarding(self, client, db_connection):
        cash = create_account(db_connection, WS, "Cash", RecordType.ASSET)
        upsert_amounts(db_connection, WS, date(2026, 9, 1), {cash.id: Decimal("5")})
        db_connection.commit()
        login(client)
        text = _text(client.get(PAGES).text)
        assert "Let's get your first" not in text
        assert "Net worth $5" in text

    def test_database_error_shows_only_the_message(self, client, monkeypatch):
        import sensibility.web.app as app_module

        login(client)

        def broken(conn, workspace_id):
            raise RuntimeError("database down")

        monkeypatch.setattr(app_module, "get_all_records", broken)
        text = _text(client.get(PAGES).text)
        assert "An error occurred while loading your data" in text
        assert "Let's get your first" not in text


# --- Accounts and Cash flows -------------------------------------------------


@pytest.mark.db
class TestEmptyAccountsPage:
    def test_editor_gets_one_add_button(self, client):
        login(client)
        response = client.get(f"{PAGES}/accounts")
        assert response.status_code == 200
        text = _text(response.text)
        assert "No accounts yet" in text
        assert "anything with a balance" in text
        assert _links(response.text) == [(NEW_ACCOUNT, "+ Add an account")]
        assert "save-bar" not in _main(response.text)

    def test_viewer_gets_no_button(self, client, db_connection):
        _as_viewer(client, db_connection)
        response = client.get(f"{PAGES}/accounts")
        text = _text(response.text)
        assert "No accounts yet" in text
        assert "An editor hasn't added any accounts yet." in text
        assert _links(response.text) == []


@pytest.mark.db
class TestEmptyCashFlowsPage:
    def test_editor_gets_one_add_button(self, client, db_connection):
        create_flow_category(db_connection, WS, "Housing")
        login(client)
        response = client.get(f"{PAGES}/cash-flows?per=year")
        assert response.status_code == 200
        text = _text(response.text)
        assert "No cash flows yet" in text
        assert "Pay, rent, groceries, subscriptions" in text
        assert _links(response.text) == [
            (f"{PAGES}/cash-flows/new?direction=income&per=year", "+ Add income")
        ]
        assert "Where income goes" not in text

    def test_viewer_gets_no_button(self, client, db_connection):
        _as_viewer(client, db_connection)
        response = client.get(f"{PAGES}/cash-flows")
        text = _text(response.text)
        assert "No cash flows yet" in text
        assert "An editor hasn't added any cash flows yet." in text
        assert _links(response.text) == []
