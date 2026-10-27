"""The welcome page (board W): `/welcome`.

Where a logged-in user with no live workspace lands (bare `/` and
`/accounts` redirect here), and where anyone starts a new workspace. It
lists the invites addressed to your email (Join / Decline) and has a form
to create a workspace.
"""

import re
from html import unescape

import pytest

from sensibility import repository as repo
from sensibility.clock import local_date
from sensibility.invites import create_invite
from sensibility.models import Role
from sensibility.workspaces import create_workspace
from tests.support import USER_ID, WS
from tests.web_support import STRANGER, TZ, add_user, login, session_for

WELCOME = "/welcome"
THIRD = {"id": 3, "sub": "user-3", "email": "third@example.com", "name": "Jordan Swan"}


def visible(html: str) -> str:
    body = re.sub(r"<style.*?</style>|<script.*?</script>", "", html, flags=re.S)
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", body)).split())


def main(html: str) -> str:
    return html[html.index("<main") :]


def short(instant) -> str:
    day = local_date(instant, TZ)
    return f"{day:%b} {day.day}"


@pytest.fixture(autouse=True)
def _no_redirects(client):
    """Posts answer with a redirect; tests look at it, or follow on purpose."""
    client.follow_redirects = False


@pytest.fixture
def newcomer(db_connection):
    """Stranger, logged in, in no workspace."""
    add_user(db_connection, STRANGER)
    return STRANGER


@pytest.fixture
def invited(db_connection, newcomer):
    """Two invites for Stranger: to Test as an editor (from Me) and to Lake
    house as a viewer (from Jordan Swan)."""
    add_user(db_connection, THIRD)
    create_workspace(db_connection, THIRD["id"], "Lake house")
    first = create_invite(db_connection, WS, USER_ID, STRANGER["email"], Role.EDITOR)
    second = create_invite(
        db_connection, 2, THIRD["id"], STRANGER["email"], Role.VIEWER
    )
    return first, second


@pytest.mark.db
class TestBarePaths:
    def test_no_workspace_redirects_to_welcome(self, client, newcomer):
        session_for(client, newcomer)
        for path in ("/", "/accounts"):
            response = client.get(path, follow_redirects=False)
            assert (response.status_code, response.headers["location"]) == (
                302,
                WELCOME,
            ), path

    def test_with_a_workspace_they_still_go_to_it(self, client):
        login(client)
        assert (
            client.get("/", follow_redirects=False).headers["location"]
            == "/workspaces/1"
        )


@pytest.mark.db
class TestWithoutInvites:
    def test_greets_and_offers_to_create(self, client, newcomer):
        session_for(client, newcomer)
        response = client.get(WELCOME)
        assert response.status_code == 200
        html = main(response.text)
        text = visible(html)
        assert "Welcome, Stranger" in text
        assert "A workspace holds a set of accounts and cash flows" in text
        assert "Start your own workspace" in text
        assert 'action="/workspaces"' in html
        assert "Invites for you" not in text
        assert 'class="or"' not in html

    def test_header_has_no_nav_or_picker(self, client, newcomer):
        session_for(client, newcomer)
        html = client.get(WELCOME).text
        header = html[: html.index("<main")]
        assert 'class="main-nav"' not in header
        assert "<select" not in header
        assert "Workspace settings" not in header
        assert 'href="/logout"' in header

    def test_first_name_falls_back_to_the_email(self, client, db_connection):
        add_user(
            db_connection,
            {"id": 2, "sub": "user-2", "email": "sam.lee@example.com", "name": None},
        )
        session_for(
            client,
            {"id": 2, "sub": "user-2", "email": "sam.lee@example.com", "name": None},
        )
        text = visible(client.get(WELCOME).text)
        assert "Welcome, sam.lee A workspace" in text

    def test_only_the_first_name(self, client, db_connection):
        sam = {"id": 2, "sub": "user-2", "email": "s@example.com", "name": "Sam Lee"}
        add_user(db_connection, sam)
        session_for(client, sam)
        assert "Welcome, Sam A workspace" in visible(client.get(WELCOME).text)

    def test_reachable_with_workspaces(self, client):
        login(client)
        text = visible(main(client.get(WELCOME).text))
        assert "New workspace" in text and "Welcome," not in text
        assert "Start your own workspace" in text


@pytest.mark.db
class TestInvites:
    def test_lists_them_with_join_and_decline(self, client, invited):
        first, second = invited
        session_for(client, STRANGER)
        html = main(client.get(WELCOME).text)
        text = visible(html)
        assert "Invites for you" in text
        assert 'class="or"' in html
        assert (
            f"Test Me invited you as an editor · expires {short(first.expires_at)}"
            in text
        )
        assert (
            f"Lake house Jordan Swan invited you as a viewer · expires "
            f"{short(second.expires_at)}" in text
        )
        for invite in invited:
            assert f'action="/invites/{invite.id}/accept"' in html
            assert f'action="/invites/{invite.id}/decline"' in html
        # Create is secondary when there are invites.
        assert "btn-primary-outline" in html

    def test_a_lapsed_invite_is_not_offered(self, client, db_connection, invited):
        """Its sender is no longer an owner, so Join would fail."""
        add_user(
            db_connection,
            {"id": 4, "sub": "user-4", "email": "o@example.com", "name": "O"},
            "owner",
        )
        repo.set_member_role(db_connection, WS, USER_ID, Role.EDITOR)
        db_connection.commit()
        session_for(client, STRANGER)
        text = visible(client.get(WELCOME).text)
        assert "Lake house" in text
        assert "Me invited you" not in text

    def test_join_goes_into_the_workspace(self, client, db_connection, invited):
        first, _ = invited
        session_for(client, STRANGER)
        response = client.post(f"/invites/{first.id}/accept")
        assert (response.status_code, response.headers["location"]) == (
            303,
            "/workspaces/1",
        )
        assert repo.get_access(db_connection, WS, STRANGER["id"]) is not None
        assert repo.get_access(db_connection, WS, STRANGER["id"])[1] == Role.EDITOR
        assert "Joined Test as an editor." in visible(client.get("/workspaces/1").text)
        # The other invite is still there.
        text = visible(client.get(WELCOME).text)
        assert "Lake house" in text and "Me invited you" not in text

    def test_decline_stays_here(self, client, db_connection, invited):
        _, second = invited
        session_for(client, STRANGER)
        response = client.post(f"/invites/{second.id}/decline")
        assert (response.status_code, response.headers["location"]) == (303, WELCOME)
        invite = repo.get_invite(db_connection, second.id)
        assert invite is not None and invite.declined_at is not None
        text = visible(client.get(WELCOME).text)
        assert "Declined the invite to Lake house." in text
        assert "Jordan Swan invited you" not in text

    def test_someone_elses_invite_is_not_found(self, client, db_connection, invited):
        first, _ = invited
        login(client)  # Me, not the invitee
        assert client.post(f"/invites/{first.id}/accept").status_code == 404
        assert client.post(f"/invites/{first.id}/decline").status_code == 404
        invite = repo.get_invite(db_connection, first.id)
        assert invite is not None and invite.is_open
        assert client.post("/invites/999/accept").status_code == 404


@pytest.mark.db
class TestCreate:
    def test_creates_and_goes_into_it(self, client, db_connection, newcomer):
        session_for(client, newcomer)
        response = client.post("/workspaces", data={"name": " Personal "})
        assert (response.status_code, response.headers["location"]) == (
            303,
            "/workspaces/2",
        )
        found = repo.get_access(db_connection, 2, STRANGER["id"])
        assert found is not None
        assert (found[0].name, found[1]) == ("Personal", Role.OWNER)
        assert "Created Personal." in visible(client.get("/workspaces/2").text)

    def test_a_blank_name_is_refused(self, client, db_connection, newcomer):
        session_for(client, newcomer)
        response = client.post("/workspaces", data={"name": "  "})
        assert response.status_code == 400
        html = main(response.text)
        assert "Name is required" in visible(html)
        assert re.search(r'name="name"[^>]*value="  "', html)
        assert repo.get_workspace(db_connection, 2) is None
        # Without invites the create button is the primary one.
        assert "btn-primary-outline" not in html
