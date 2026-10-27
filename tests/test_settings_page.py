"""Workspace settings (board V): `/workspaces/{id}/settings`.

Owners get the whole page: the General form, Leave and Delete, and People
(invite form, members with role selects, pending invites). Editors and
viewers get the same page read-only, plus Leave. Every write posts and
redirects back (or to `/` after leaving or deleting); a refusal re-renders
the page with a 400 and the service's message. Removing, revoking, leaving
and deleting confirm in the page first (`?confirm=`), so no JS is needed.
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
from tests.web_support import PAGES, STRANGER, TZ, add_user, login, session_for

SETTINGS = f"{PAGES}/settings"
THIRD = {"id": 3, "sub": "user-3", "email": "third@example.com", "name": "Third Person"}
INVITEE = "sam.lee@example.com"


def visible(html: str) -> str:
    """Visible text, whitespace collapsed."""
    body = re.sub(r"<style.*?</style>|<script.*?</script>", "", html, flags=re.S)
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", body)).split())


def main(html: str) -> str:
    """The page body, without the shell's header."""
    return html[html.index("<main") :]


def short(instant) -> str:
    """How the page dates an instant: "Oct 20" in the viewer's zone."""
    day = local_date(instant, TZ)
    return f"{day:%b} {day.day}"


def roles(conn) -> dict[int, Role]:
    return {m.user_id: m.role for m in repo.get_members(conn, WS)}


@pytest.fixture(autouse=True)
def _no_redirects(client):
    """Posts answer with a redirect; tests look at it, or follow on purpose."""
    client.follow_redirects = False


@pytest.fixture
def team(db_connection):
    """The seeded owner (Me), Stranger as an editor, Third as a viewer, and
    a pending invite from Me."""
    add_user(db_connection, STRANGER, "editor")
    add_user(db_connection, THIRD, "viewer")
    return create_invite(db_connection, WS, USER_ID, INVITEE, Role.EDITOR)


@pytest.mark.db
class TestOwnerView:
    def test_title_and_your_role(self, client, team):
        login(client)
        text = visible(client.get(SETTINGS).text)
        assert "Test settings" in text
        assert "You're an owner of this workspace." in text

    def test_general_form_holds_the_name(self, client, team):
        login(client)
        html = main(client.get(SETTINGS).text)
        assert f'action="{SETTINGS}"' in html
        assert re.search(r'<input[^>]*name="name"[^>]*value="Test"', html)

    def test_people_lists_members_then_the_pending_invite(self, client, team):
        login(client)
        html = main(client.get(SETTINGS).text)
        text = visible(html)
        assert "3 members · 1 invited" in text
        # Members in order, you marked, then the invite.
        assert (
            text.index("Me (you)") < text.index("Stranger") < text.index("Third Person")
        )
        assert text.index("Third Person") < text.index(INVITEE)
        assert "stranger@example.com" in text
        expected = (
            f"Invited Sent by you {short(team.created_at)} · "
            f"expires {short(team.expires_at)} Editor"
        )
        assert expected in text

    def test_each_member_has_a_role_select_with_their_role(self, client, team):
        login(client)
        html = main(client.get(SETTINGS).text)
        for user_id, role in ((USER_ID, "owner"), (2, "editor"), (3, "viewer")):
            form = html[html.index(f'action="{PAGES}/members/{user_id}"') :]
            form = form[: form.index("</form>")]
            assert re.search(rf'<option value="{role}" selected>', form), user_id
            assert form.count(" selected") == 1
        # Selecting submits; the Save button is the no-JS fallback.
        assert html.count('class="btn btn-outline role-save">Save</button>') == 3
        assert "requestSubmit" in html
        assert "save.hidden = true" in html  # the fallback hides when JS runs

    def test_remove_buttons_ask_first(self, client, team):
        login(client)
        html = main(client.get(SETTINGS).text)
        assert (
            f'href="{SETTINGS}?confirm=member-2" aria-label="Remove Stranger"' in html
        )
        assert f'href="{SETTINGS}?confirm=invite-{team.id}"' in html
        assert 'aria-label="Revoke the invite to sam.lee@example.com"' in html
        # Nothing is removed by a link alone.
        assert f'action="{PAGES}/members/2/remove"' not in html

    def test_invite_form_and_footnote(self, client, team):
        login(client)
        html = main(client.get(SETTINGS).text)
        assert f'action="{PAGES}/invites"' in html
        assert re.search(r'<option value="editor" selected>Editor</option>', html)
        text = visible(html)
        assert "No email is sent" in text
        assert "they'll see the invite when they log in with that address" in text
        assert "Invites expire after 14 days." in text
        assert "owners also manage the workspace and its people" in text

    def test_the_only_owner_cannot_leave_but_can_delete(self, client, team):
        login(client)
        html = main(client.get(SETTINGS).text)
        text = visible(html)
        assert "Leave Test" in text
        assert "You're its only owner, so you can't leave." in text
        assert f'href="{SETTINGS}?confirm=leave"' not in html
        assert 'aria-label="Leave Test"' not in html  # no × on your own row
        assert "Delete Test" in text
        assert (
            "Removes it for all 3 members. Its data is kept and can be restored by an admin."
            in text
        )
        assert f'href="{SETTINGS}?confirm=delete"' in html
        # Asking for the confirm by URL offers nothing either.
        for confirm in ("leave", f"member-{USER_ID}"):
            asked = main(client.get(f"{SETTINGS}?confirm={confirm}").text)
            assert f'action="{PAGES}/members/{USER_ID}/remove"' not in asked

    def test_an_owner_with_another_owner_can_leave(self, client, db_connection, team):
        repo.set_member_role(db_connection, WS, 2, Role.OWNER)
        db_connection.commit()
        login(client)
        html = main(client.get(SETTINGS).text)
        assert "Another owner stays, so you can leave." in visible(html)
        assert f'href="{SETTINGS}?confirm=leave"' in html
        assert (
            f'href="{SETTINGS}?confirm=member-{USER_ID}" aria-label="Leave Test"'
            in html
        )

    def test_a_lapsed_invite_says_so(self, client, db_connection, team):
        """An invite speaks for its sender: once they are not an owner it
        cannot be accepted, and the list says why."""
        repo.set_member_role(db_connection, WS, 2, Role.OWNER)
        db_connection.commit()
        session_for(client, STRANGER)
        assert "lapsed" not in visible(client.get(SETTINGS).text)
        repo.set_member_role(db_connection, WS, USER_ID, Role.EDITOR)
        db_connection.commit()
        text = visible(client.get(SETTINGS).text)
        assert "Sent by Me" in text
        assert "lapsed: Me is no longer an owner" in text

    def test_dates_are_in_the_viewers_zone(self, client, db_connection, team):
        """02:00 UTC on Oct 21 is still Oct 20 in Chicago (the tz cookie)."""
        db_connection.execute(
            "UPDATE workspace_invites SET created_at = '2026-10-21T02:00:00Z',"
            " expires_at = '2026-11-04T02:00:00Z'"
        )
        db_connection.commit()
        login(client)
        client.cookies.set("tz", "America/Chicago")
        assert "Sent by you Oct 20 · expires Nov 3" in visible(
            client.get(SETTINGS).text
        )
        client.cookies.set("tz", "UTC")
        assert "Sent by you Oct 21 · expires Nov 4" in visible(
            client.get(SETTINGS).text
        )

    def test_one_member_is_its_only_member(self, client):
        login(client)
        text = visible(client.get(SETTINGS).text)
        assert "1 member" in text and "1 members" not in text
        assert "Removes it for you, its only member." in text


@pytest.mark.db
class TestHeader:
    def test_gear_links_to_settings_and_marks_it_current(self, client, team):
        login(client)
        gear = f'href="{SETTINGS}" aria-label="Workspace settings"'
        assert f'{gear} aria-current="page"' in client.get(SETTINGS).text
        dashboard = client.get(PAGES).text
        assert gear in dashboard
        assert f'{gear} aria-current="page"' not in dashboard

    def test_the_picker_keeps_you_on_settings(self, client, db_connection, team):
        create_workspace(db_connection, USER_ID, "Second")
        login(client)
        text = client.get(SETTINGS).text
        assert '<option value="/workspaces/2/settings">Second</option>' in text

    def test_a_refused_write_keeps_the_picker_on_settings(
        self, client, db_connection, team
    ):
        """The page re-renders at the POST's path; the picker must not link
        to that path in another workspace."""
        create_workspace(db_connection, USER_ID, "Second")
        login(client)
        for path, data in (
            (f"{PAGES}/members/{USER_ID}", {"role": "viewer"}),
            (f"{PAGES}/members/{USER_ID}/remove", {}),
            (f"{PAGES}/invites", {"email": "bad", "role": "viewer"}),
        ):
            response = client.post(path, data=data)
            assert response.status_code == 400, path
            assert (
                '<option value="/workspaces/2/settings">Second</option>'
                in response.text
            ), path

    def test_user_menu_offers_a_new_workspace(self, client, team):
        login(client)
        assert 'href="/welcome"' in client.get(SETTINGS).text


@pytest.mark.db
class TestReadOnlyView:
    """Editors and viewers see who is in the workspace and can leave. They
    get no General form, no delete, no invites (the API lists invites to
    owners only) and no role selects."""

    @pytest.mark.parametrize(
        "user,phrase", [(STRANGER, "an editor"), (THIRD, "a viewer")]
    )
    def test_read_only_page(self, client, team, user, phrase):
        session_for(client, user)
        response = client.get(SETTINGS)
        assert response.status_code == 200
        html = main(response.text)
        text = visible(html)
        assert f"You're {phrase} of this workspace." in text
        assert f'action="{SETTINGS}"' not in html
        assert f'action="{PAGES}/invites"' not in html
        assert "<select" not in html
        assert "Delete Test" not in text
        assert INVITEE not in text and "invited" not in text
        assert "3 members" in text
        assert "Only owners can invite people or change roles." in text
        # Roles as text.
        assert re.search(r"Me\s*</span>.*?Owner", html, re.S)
        # Leave, from the card and from your own row; no × on others.
        assert f'href="{SETTINGS}?confirm=leave"' in html
        assert f'href="{SETTINGS}?confirm=member-{user["id"]}"' in html
        assert html.count("?confirm=member-") == 1
        assert "until an owner invites you again" in text

    def test_confirms_for_owner_actions_are_ignored(self, client, team):
        session_for(client, THIRD)
        for confirm in ("delete", f"invite-{team.id}", "member-2"):
            html = main(client.get(f"{SETTINGS}?confirm={confirm}").text)
            assert "/remove" not in html and "/revoke" not in html, confirm
            assert f'action="{PAGES}/delete"' not in html


@pytest.mark.db
class TestRename:
    def test_saves_and_comes_back(self, client, db_connection, team):
        login(client)
        response = client.post(SETTINGS, data={"name": "  Household "})
        assert (response.status_code, response.headers["location"]) == (303, SETTINGS)
        workspace = repo.get_workspace(db_connection, WS)
        assert workspace is not None and workspace.name == "Household"
        text = visible(client.get(SETTINGS).text)
        assert "Saved Household" in text
        assert "Household settings" in text

    def test_a_blank_name_is_refused_in_the_form(self, client, db_connection, team):
        login(client)
        response = client.post(SETTINGS, data={"name": "   "})
        assert response.status_code == 400
        html = main(response.text)
        general = html[: html.index("People")]
        assert "Name is required" in general
        assert re.search(r'name="name"[^>]*value="   "', general)
        assert "Test settings" in visible(html)  # the title keeps the saved name
        workspace = repo.get_workspace(db_connection, WS)
        assert workspace is not None and workspace.name == "Test"


@pytest.mark.db
class TestInvite:
    def _post(self, client, email, role="viewer"):
        login(client)
        return client.post(f"{PAGES}/invites", data={"email": email, "role": role})

    def test_invites_with_the_role(self, client, db_connection, team):
        response = self._post(client, "New@Example.com", "owner")
        assert (response.status_code, response.headers["location"]) == (303, SETTINGS)
        invites = repo.get_pending_workspace_invites(db_connection, WS)
        assert [(i.email, i.role) for i in invites][-1] == (
            "new@example.com",
            Role.OWNER,
        )
        text = visible(client.get(SETTINGS).text)
        assert "Invited new@example.com as an owner." in text
        assert "4 invited" not in text and "2 invited" in text

    def test_a_bad_email_keeps_the_input(self, client, db_connection, team):
        response = self._post(client, "not-an-email", "owner")
        assert response.status_code == 400
        html = main(response.text)
        assert "&#39;not-an-email&#39; is not an email address" in html
        assert re.search(r'name="email"[^>]*value="not-an-email"', html)
        assert re.search(r'<option value="owner" selected>Owner</option>', html)
        assert len(repo.get_pending_workspace_invites(db_connection, WS)) == 1

    def test_a_second_open_invite_is_refused(self, client, team):
        response = self._post(client, INVITEE)
        assert response.status_code == 400
        assert "already has a pending invite" in visible(response.text)

    def test_a_member_cannot_be_invited(self, client, team):
        response = self._post(client, STRANGER["email"])
        assert response.status_code == 400
        assert "already a member of this workspace" in visible(response.text)

    def test_an_unknown_role_is_refused(self, client, db_connection, team):
        response = self._post(client, "x@example.com", "admin")
        assert response.status_code == 400
        assert "Choose a role" in visible(response.text)
        assert len(repo.get_pending_workspace_invites(db_connection, WS)) == 1


@pytest.mark.db
class TestRevoke:
    def test_asks_in_the_row_then_revokes(self, client, db_connection, team):
        login(client)
        html = main(client.get(f"{SETTINGS}?confirm=invite-{team.id}").text)
        text = visible(html)
        assert f"Revoke the invite to {INVITEE}?" in text
        assert f'action="{PAGES}/invites/{team.id}/revoke"' in html
        assert f'href="{SETTINGS}"' in html  # Keep

        response = client.post(f"{PAGES}/invites/{team.id}/revoke")
        assert (response.status_code, response.headers["location"]) == (303, SETTINGS)
        assert repo.get_pending_workspace_invites(db_connection, WS) == []
        assert f"Revoked the invite to {INVITEE}" in visible(client.get(SETTINGS).text)

    def test_another_workspaces_invite_is_not_found(self, client, db_connection, team):
        add_user(
            db_connection,
            {"id": 4, "sub": "user-4", "email": "o@example.com", "name": "O"},
        )
        create_workspace(db_connection, 4, "Theirs")
        theirs = create_invite(db_connection, 2, 4, "x@example.com", Role.VIEWER)
        login(client)
        assert client.post(f"{PAGES}/invites/{theirs.id}/revoke").status_code == 404
        assert repo.get_pending_workspace_invites(db_connection, 2) != []

    def test_a_resolved_invite_says_so(self, client, db_connection, team):
        repo.set_invite_revoked(db_connection, team.id)
        db_connection.commit()
        login(client)
        response = client.post(f"{PAGES}/invites/{team.id}/revoke")
        assert response.status_code == 400
        assert "already been resolved" in visible(response.text)


@pytest.mark.db
class TestChangeRole:
    def test_changes_it(self, client, db_connection, team):
        login(client)
        response = client.post(f"{PAGES}/members/3", data={"role": "editor"})
        assert (response.status_code, response.headers["location"]) == (303, SETTINGS)
        assert roles(db_connection)[3] == Role.EDITOR
        assert "Third Person is now an editor." in visible(client.get(SETTINGS).text)

    def test_the_last_owner_cannot_be_demoted(self, client, db_connection, team):
        login(client)
        response = client.post(f"{PAGES}/members/{USER_ID}", data={"role": "viewer"})
        assert response.status_code == 400
        html = main(response.text)
        assert "A workspace needs at least one owner." in visible(html)
        # The select still shows the saved role.
        form = html[html.index(f'action="{PAGES}/members/{USER_ID}"') :]
        assert re.search(
            r'<option value="owner" selected>', form[: form.index("</form>")]
        )
        assert roles(db_connection)[USER_ID] == Role.OWNER

    def test_demoting_yourself_leaves_a_read_only_page(
        self, client, db_connection, team
    ):
        repo.set_member_role(db_connection, WS, 2, Role.OWNER)
        db_connection.commit()
        login(client)
        client.post(f"{PAGES}/members/{USER_ID}", data={"role": "editor"})
        assert roles(db_connection)[USER_ID] == Role.EDITOR
        text = visible(client.get(SETTINGS).text)
        assert "You're now an editor." in text
        assert "You're an editor of this workspace." in text

    def test_an_unknown_member_or_role(self, client, db_connection, team):
        login(client)
        assert (
            client.post(f"{PAGES}/members/99", data={"role": "editor"}).status_code
            == 404
        )
        bad = client.post(f"{PAGES}/members/3", data={"role": "admin"})
        assert bad.status_code == 400
        assert roles(db_connection)[3] == Role.VIEWER


@pytest.mark.db
class TestRemove:
    def test_asks_in_the_row_then_removes(self, client, db_connection, team):
        login(client)
        html = main(client.get(f"{SETTINGS}?confirm=member-2").text)
        text = visible(html)
        assert "Remove Stranger? They lose access to Test right away." in text
        assert f'action="{PAGES}/members/2/remove"' in html

        response = client.post(f"{PAGES}/members/2/remove")
        assert (response.status_code, response.headers["location"]) == (303, SETTINGS)
        assert 2 not in roles(db_connection)
        assert "Removed Stranger" in visible(client.get(SETTINGS).text)

    def test_a_non_member_is_not_found(self, client, db_connection, team):
        login(client)
        assert client.post(f"{PAGES}/members/99/remove").status_code == 404

    def test_only_owners_remove_others(self, client, db_connection, team):
        session_for(client, STRANGER)
        assert client.post(f"{PAGES}/members/3/remove").status_code == 403
        assert 3 in roles(db_connection)


@pytest.mark.db
class TestLeave:
    def test_asks_first(self, client, team):
        session_for(client, THIRD)
        for confirm in ("leave", "member-3"):
            html = main(client.get(f"{SETTINGS}?confirm={confirm}").text)
            assert "Leave Test? You'll lose access right away." in visible(html)
            assert f'action="{PAGES}/members/3/remove"' in html

    def test_leaving_goes_home(self, client, db_connection, team):
        session_for(client, THIRD)
        response = client.post(f"{PAGES}/members/3/remove")
        assert (response.status_code, response.headers["location"]) == (303, "/")
        assert 3 not in roles(db_connection)
        # No workspace left: home is the welcome page, with the flash.
        landed = client.get("/", follow_redirects=True)
        assert landed.url.path == "/welcome"
        assert "You left Test." in visible(landed.text)

    def test_the_last_owner_is_refused(self, client, db_connection, team):
        login(client)
        response = client.post(f"{PAGES}/members/{USER_ID}/remove")
        assert response.status_code == 400
        html = main(response.text)
        leave = html[: html.index("People")]
        assert "A workspace needs at least one owner." in visible(leave)
        assert USER_ID in roles(db_connection)


@pytest.mark.db
class TestDelete:
    def test_asks_first(self, client, team):
        login(client)
        html = main(client.get(f"{SETTINGS}?confirm=delete").text)
        assert "Delete Test for all 3 members?" in visible(html)
        assert f'action="{PAGES}/delete"' in html

    def test_deletes_softly_and_goes_home(self, client, db_connection, team):
        create_workspace(db_connection, USER_ID, "Second")
        login(client)
        response = client.post(f"{PAGES}/delete")
        assert (response.status_code, response.headers["location"]) == (303, "/")
        workspace = repo.get_workspace(db_connection, WS)
        assert workspace is not None and workspace.deleted_at is not None
        landed = client.get("/", follow_redirects=True)
        assert landed.url.path == "/workspaces/2"
        assert "Deleted Test." in visible(landed.text)
        assert client.get(SETTINGS).status_code == 404

    def test_editors_cannot(self, client, db_connection, team):
        session_for(client, STRANGER)
        assert client.post(f"{PAGES}/delete").status_code == 403
        workspace = repo.get_workspace(db_connection, WS)
        assert workspace is not None and workspace.deleted_at is None
