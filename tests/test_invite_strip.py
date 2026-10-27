"""Board Z: the invite strip, the restyled flashes, and the header gear.

The strip tells someone already in a workspace about an invite they could
accept, on every page with the shell. Decline returns to the page it was
on (a safe `next`); Join goes into the workspace, as it does on /welcome.
"""

import re
from decimal import Decimal
from html import unescape

import pytest

from asset_manager import repository as repo
from asset_manager.accounts import create_account
from asset_manager.clock import local_date
from asset_manager.invites import create_invite
from asset_manager.models import ProportionalFormula, RecordType, Role
from asset_manager.web.invite_strip import safe_next
from asset_manager.workspaces import create_workspace
from tests.support import USER_ID, WS
from tests.web_support import PAGES, STRANGER, TZ, USER, add_user, login, session_for

JORDAN = {
    "id": 2,
    "sub": "user-2",
    "email": "jordan@example.com",
    "name": "Jordan Swan",
}
SAM = {"id": 3, "sub": "user-3", "email": "sam@example.com", "name": None}


def visible(html: str) -> str:
    body = re.sub(r"<style.*?</style>|<script.*?</script>", "", html, flags=re.S)
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", body)).split())


def strips(html: str) -> list[str]:
    return re.findall(r'<section class="invite-strip".*?</section>', html, flags=re.S)


def short(instant) -> str:
    day = local_date(instant, TZ)
    return f"{day:%b} {day.day}"


@pytest.fixture(autouse=True)
def _no_redirects(client):
    client.follow_redirects = False


@pytest.fixture
def lake_house(db_connection):
    """Jordan owns workspace 2, Lake house, and invites Me as a viewer."""
    add_user(db_connection, JORDAN)
    create_workspace(db_connection, JORDAN["id"], "Lake house")
    return create_invite(db_connection, 2, JORDAN["id"], USER["email"], Role.VIEWER)


@pytest.fixture
def two_invites(db_connection, lake_house):
    """And later, Sam (no name) invites Me to Cabin (workspace 3) as an editor."""
    add_user(db_connection, SAM)
    create_workspace(db_connection, SAM["id"], "Cabin")
    later = create_invite(db_connection, 3, SAM["id"], USER["email"], Role.EDITOR)
    return lake_house, later


@pytest.mark.db
class TestStrip:
    def test_none_without_invites(self, client):
        login(client)
        assert strips(client.get(PAGES).text) == []
        assert "invite-strip" not in client.get(PAGES).text.split("</style>")[1]

    def test_one_invite(self, client, lake_house):
        login(client)
        html = client.get(PAGES).text
        [strip] = strips(html)
        text = visible(strip)
        assert "Jordan Swan invited you to Lake house as a viewer." in text
        assert f"Expires {short(lake_house.expires_at)}" in text
        assert f'action="/invites/{lake_house.id}/accept"' in strip
        assert f'action="/invites/{lake_house.id}/decline"' in strip
        assert re.search(
            r'<button[^>]*class="btn btn-outline"[^>]*>Decline</button>', strip
        )
        assert re.search(
            r'<button[^>]*class="btn btn-primary"[^>]*>Join Lake house</button>', strip
        )
        assert '<input type="hidden" name="next" value="/workspaces/1">' in strip
        assert 'aria-label="Invite to Lake house"' in strip
        # The mail icon is decoration.
        assert re.search(r'<svg[^>]*aria-hidden="true"', strip)
        # Inside main, above the page content.
        at = html.index('<section class="invite-strip"')
        assert html.index("<main") < at < html.index("Test is new")

    def test_one_per_invite_newest_first(self, client, two_invites):
        login(client)
        found = [visible(s) for s in strips(client.get(PAGES).text)]
        assert len(found) == 2
        # Sam has no name: the email stands in.
        assert found[0].startswith("sam@example.com invited you to Cabin as an editor.")
        assert found[1].startswith("Jordan Swan invited you to Lake house")

    def test_lapsed_invite_is_left_out(self, client, db_connection, two_invites):
        # Jordan stops being an owner of Lake house: that invite lapses.
        add_user(
            db_connection,
            {"id": 4, "sub": "user-4", "email": "o@example.com", "name": "O"},
            "owner",
            workspace_id=2,
        )
        repo.set_member_role(db_connection, 2, JORDAN["id"], Role.EDITOR)
        db_connection.commit()
        login(client)
        found = [visible(s) for s in strips(client.get(PAGES).text)]
        assert len(found) == 1
        assert "Cabin" in found[0]

    def test_someone_elses_invite_is_not_shown(self, client, db_connection):
        add_user(db_connection, STRANGER)
        create_invite(db_connection, WS, USER_ID, STRANGER["email"], Role.EDITOR)
        login(client)
        assert strips(client.get(PAGES).text) == []

    def test_resolved_invites_are_not_shown(self, client, db_connection, lake_house):
        repo.set_invite_revoked(db_connection, lake_house.id)
        db_connection.commit()
        login(client)
        assert strips(client.get(PAGES).text) == []

    @pytest.mark.parametrize(
        "path", ["", "/accounts", "/cash-flows", "/cash-flows?per=year", "/settings"]
    )
    def test_on_every_shell_page(self, client, lake_house, path):
        login(client)
        response = client.get(PAGES + path)
        assert response.status_code == 200
        [strip] = strips(response.text)
        # Decline comes back to this very page, query included.
        assert f'name="next" value="{PAGES + path}"' in strip

    def test_next_is_escaped(self, client, lake_house):
        login(client)
        html = client.get(f"{PAGES}/cash-flows?per=year&x=%22%3E").text
        [strip] = strips(html)
        assert 'value="/workspaces/1/cash-flows?per=year&amp;x=%22%3E"' in strip

    def test_a_refused_post_returns_to_the_page_not_the_post(self, client, lake_house):
        login(client)
        response = client.post(
            f"{PAGES}/invites", data={"email": "not-an-email", "role": "viewer"}
        )
        assert response.status_code == 400
        [strip] = strips(response.text)
        assert f'name="next" value="{PAGES}/settings"' in strip

    def test_not_on_welcome(self, client, lake_house):
        login(client)
        html = client.get("/welcome").text
        assert strips(html) == []
        assert "Lake house" in visible(html)  # welcome lists it itself

    def test_not_on_login(self, client, lake_house):
        login(client)
        assert strips(client.get("/login").text) == []

    @pytest.mark.parametrize(
        "path", ["/accounts/new", "/cash-flows/new", "/cash-flow-categories"]
    )
    def test_not_under_a_drawer(self, client, lake_house, path):
        login(client)
        response = client.get(PAGES + path)
        assert response.status_code == 200
        assert strips(response.text) == []


@pytest.mark.db
class TestDecline:
    def test_returns_to_next_with_a_flash(self, client, db_connection, lake_house):
        login(client)
        response = client.post(
            f"/invites/{lake_house.id}/decline",
            data={"next": f"{PAGES}/cash-flows?per=year"},
        )
        assert (response.status_code, response.headers["location"]) == (
            303,
            f"{PAGES}/cash-flows?per=year",
        )
        invite = repo.get_invite(db_connection, lake_house.id)
        assert invite is not None and invite.declined_at is not None
        html = client.get(f"{PAGES}/cash-flows?per=year").text
        assert "Declined the invite to Lake house." in visible(html)
        assert strips(html) == []

    @pytest.mark.parametrize(
        "unsafe",
        [
            "",
            "//evil.example.com/x",
            "https://evil.example.com/",
            "http:/evil.example.com",
            "/\\evil.example.com",
            "\\\\evil.example.com",
            "/\t/evil.example.com",
            "/\n/evil.example.com",
            "javascript:alert(1)",
            "evil.example.com",
            "workspaces/1",
        ],
    )
    def test_unsafe_next_goes_to_welcome(self, client, lake_house, unsafe):
        login(client)
        response = client.post(
            f"/invites/{lake_house.id}/decline", data={"next": unsafe}
        )
        assert (response.status_code, response.headers["location"]) == (
            303,
            "/welcome",
        )

    def test_without_next_goes_to_welcome(self, client, lake_house):
        login(client)
        response = client.post(f"/invites/{lake_house.id}/decline")
        assert response.headers["location"] == "/welcome"

    def test_someone_elses_invite_is_still_not_found(
        self, client, db_connection, lake_house
    ):
        other = {**STRANGER, "id": 3, "sub": "user-3"}
        add_user(db_connection, other)
        session_for(client, other)
        response = client.post(
            f"/invites/{lake_house.id}/decline", data={"next": PAGES}
        )
        assert response.status_code == 404


class TestSafeNext:
    @pytest.mark.parametrize(
        "value", ["/", "/workspaces/1", "/workspaces/1/cash-flows?per=year&x=1"]
    )
    def test_same_origin_paths_pass(self, value):
        assert safe_next(value) == value

    @pytest.mark.parametrize(
        "value",
        [
            None,
            "",
            "//evil.example.com",
            "///evil.example.com",
            "https://evil.example.com/",
            "/\\evil.example.com",
            "/x\\y",
            "/\x00",
            "/a\x7f",
            "/ok\r\nSet-Cookie: x=1",
            "relative/path",
        ],
    )
    def test_everything_else_is_refused(self, value):
        assert safe_next(value) is None


@pytest.mark.db
class TestJoin:
    def test_join_goes_into_the_workspace(self, client, db_connection, lake_house):
        login(client)
        response = client.post(f"/invites/{lake_house.id}/accept")
        assert (response.status_code, response.headers["location"]) == (
            303,
            "/workspaces/2",
        )
        found = repo.get_access(db_connection, 2, USER_ID)
        assert found is not None and found[1] == Role.VIEWER
        html = client.get("/workspaces/2").text
        assert "Joined Lake house as a viewer." in visible(html)
        assert strips(html) == []


def flash(html: str) -> str:
    [found] = re.findall(r'<div class="flash .*?</div>', html, flags=re.S)
    return found


@pytest.mark.db
class TestFlash:
    def test_success_is_a_status_with_a_check_and_dismiss(self, client):
        login(client)
        client.post(f"{PAGES}/settings", data={"name": "Home"})
        html = client.get(f"{PAGES}/settings").text
        found = flash(html)
        assert found.startswith('<div class="flash flash-success" role="status">')
        assert "Saved Home." in visible(found)
        assert 'class="flash-icon"' in found
        assert re.search(r'<svg class="flash-icon"[^>]*aria-hidden="true"', found)
        assert re.search(
            r'<button type="button" class="flash-dismiss" aria-label="Dismiss">', found
        )
        # One-shot.
        assert '<div class="flash' not in client.get(f"{PAGES}/settings").text

    def test_error_is_an_alert(self, client, db_connection):
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
        client.post(f"{PAGES}/accounts/{schwab.id}/retire")
        found = flash(client.get(f"{PAGES}/accounts").text)
        assert found.startswith('<div class="flash flash-error" role="alert">')
        assert "Schwab is an input to Tax" in visible(found)
        assert re.search(r'<svg class="flash-icon"[^>]*aria-hidden="true"', found)
        assert 'class="flash-dismiss"' in found

    def test_dismiss_script_and_new_tokens(self, client):
        login(client)
        client.post(f"{PAGES}/settings", data={"name": "Home"})
        html = client.get(f"{PAGES}/settings").text
        script = html.split("</style>")[1]
        assert "querySelectorAll('.flash-dismiss')" in script
        assert "button.closest('.flash').remove();" in script
        styles = html.split("Legacy aliases")[1].split("</style>")[0]
        rules = re.findall(r"\.(?:flash|error)[^{]*\{[^}]*\}", styles)
        assert rules
        for rule in rules:
            assert "--color-" not in rule, rule
        success = next(r for r in rules if ".flash-success" in r)
        assert "var(--asset-tint)" in success
        error = next(r for r in rules if ".flash-error" in r)
        assert "var(--danger-tint)" in error and "var(--danger)" in error

    def test_the_drawer_still_takes_the_flash(self, client, db_connection):
        """Under an open drawer the page's flash spot stays empty."""
        login(client)
        client.post(f"{PAGES}/cash-flow-categories", data={"name": "Food"})
        html = client.get(f"{PAGES}/cash-flow-categories").text
        assert '<div class="flash' not in html
        assert "Added Food" in visible(html)


@pytest.mark.db
class TestSnapshotFlash:
    def test_save_says_how_many_and_the_net_worth(self, client, db_connection):
        cash = create_account(db_connection, WS, "Cash", RecordType.ASSET)
        house = create_account(db_connection, WS, "House", RecordType.ASSET)
        card = create_account(db_connection, WS, "Card", RecordType.LIABILITY)
        login(client)
        response = client.post(
            f"{PAGES}/snapshots",
            json={
                "values": {
                    str(cash.id): "1000.40",
                    str(house.id): "357000",
                    str(card.id): "82.10",
                }
            },
        )
        assert response.status_code == 200
        text = visible(flash(client.get(f"{PAGES}/accounts").text))
        assert "Saved today's snapshot: 3 accounts, net worth $357,918." in text

    def test_one_account_is_singular(self, client, db_connection):
        cash = create_account(db_connection, WS, "Cash", RecordType.ASSET)
        login(client)
        client.post(f"{PAGES}/snapshots", json={"values": {str(cash.id): "-5"}})
        text = visible(flash(client.get(f"{PAGES}/accounts").text))
        assert "Saved today's snapshot: 1 account, net worth -$5." in text

    def test_a_refused_save_sets_no_flash(self, client, db_connection):
        create_account(db_connection, WS, "Cash", RecordType.ASSET)
        login(client)
        response = client.post(f"{PAGES}/snapshots", json={"values": {}})
        assert response.status_code == 400
        assert '<div class="flash' not in client.get(f"{PAGES}/accounts").text


@pytest.mark.db
class TestGear:
    def test_is_a_cog_outline(self, client):
        login(client)
        html = client.get(PAGES).text
        link = re.search(
            r'<a class="round-button" href="/workspaces/1/settings".*?</a>',
            html,
            flags=re.S,
        )
        assert link is not None
        svg = link.group(0)
        assert 'aria-label="Workspace settings"' in svg
        assert re.search(r'<svg width="18" height="18"[^>]*aria-hidden="true"', svg)
        assert 'stroke="currentColor"' in svg and 'fill="none"' in svg
        # A cog: one closed toothed outline and a hub, not the old sun's spokes.
        assert "M10 2.5v2" not in svg
        assert len(re.findall(r"<path", svg)) == 1
        assert re.search(r'<path d="M[^"]*z"', svg)
        assert "<circle" in svg
