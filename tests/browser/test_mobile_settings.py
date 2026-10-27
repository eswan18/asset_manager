"""Settings, welcome and login on a phone (docs/superpowers/specs/2026-10-26-mobile-design.md).

Each screen, in each state that changes its layout, fits a 320px and a 390px
phone: nothing scrolls sideways, tap targets are 44px, fields are 16px. The
shell's header (nav, workspace picker, user menu) is the shell's to size and
is checked by its own tests, so `fits` leaves it out.
"""

from types import SimpleNamespace

import pytest

from asset_manager.invites import create_invite
from asset_manager.models import Role
from asset_manager.workspaces import create_workspace
from playwright.sync_api import Page

from tests.browser.mobile import PHONE_WIDTHS, assert_fits_phone
from tests.support import USER_ID, WS
from tests.web_support import PAGES, USER, FakeIdp, add_user, claims

pytestmark = [pytest.mark.browser, pytest.mark.db]

SETTINGS = f"{PAGES}/settings"


def fits(page: Page) -> None:
    """assert_fits_phone on the page's content. `allow_small` cannot exempt
    the header's picker from the 16px field rule, so the header is made
    inert (which the checks skip) for the targets and fields; its width
    still counts toward sideways scrolling."""
    page.evaluate("() => document.querySelector('header')?.setAttribute('inert', '')")
    assert_fits_phone(page)


LONG_NAME = {
    "id": 2,
    "sub": "user-2",
    "email": "alexandra.rivera-montgomery.the.third@example.com",
    "name": "Alexandra Rivera-Montgomery-Featherstonehaugh",
}
OTHER = {"id": 3, "sub": "user-3", "email": "casey@example.com", "name": "Casey Park"}
LONG_INVITE = "someone.with.a.very.long.address.indeed@example.com"


@pytest.fixture
def team(db_connection):
    """Me (owner), a second owner with a long name and email, a viewer, and a
    pending invite to a long address."""
    add_user(db_connection, LONG_NAME, "owner")
    add_user(db_connection, OTHER, "viewer")
    return create_invite(db_connection, WS, USER_ID, LONG_INVITE, Role.EDITOR)


def _set_my_role(conn, role: str) -> None:
    conn.execute(
        "UPDATE workspace_members SET role = %s WHERE workspace_id = %s AND user_id = %s",
        (role, WS, USER_ID),
    )
    conn.commit()


def _box(page, selector: str) -> dict:
    box = page.locator(selector).first.bounding_box()
    assert box is not None, selector
    return box


@pytest.mark.parametrize("width", PHONE_WIDTHS)
class TestSettings:
    def test_owner(self, open_page, team, width):
        page = open_page(SETTINGS, phone=width)
        fits(page)
        # One column: People comes under Leave / Delete.
        outline = _box(page, ".outline-card")
        people = _box(page, ".people-head")
        assert people["y"] > outline["y"] + outline["height"]
        # The invite form stacks: email on its own row, then role and Invite.
        email = _box(page, ".invite-form input[name=email]")
        role = _box(page, ".invite-form select")
        invite = _box(page, ".invite-form button")
        assert role["y"] >= email["y"] + email["height"]
        assert abs(role["y"] - invite["y"]) < 2
        # A person's role and × sit together under their name and email.
        row = page.locator(".person", has_text=LONG_NAME["name"])
        main = row.locator(".person-main").bounding_box()
        select = row.locator("select").bounding_box()
        remove = row.locator(".person-remove").bounding_box()
        assert main and select and remove
        assert select["y"] >= main["y"] + main["height"]
        assert abs(select["y"] - remove["y"]) < 2
        assert remove["x"] > select["x"]

    @pytest.mark.parametrize(
        "confirm", ["member-2", "member-1", "invite", "leave", "delete"]
    )
    def test_owner_confirms(self, open_page, team, width, confirm):
        if confirm == "invite":
            confirm = f"invite-{team.id}"
        page = open_page(f"{SETTINGS}?confirm={confirm}", phone=width)
        assert page.locator(".confirm").count() == 1
        fits(page)

    def test_confirm_buttons_share_a_row(self, open_page, team, width):
        page = open_page(f"{SETTINGS}?confirm=invite-{team.id}", phone=width)
        keep = _box(page, ".confirm-actions a")
        revoke = _box(page, ".confirm-actions button")
        assert abs(keep["y"] - revoke["y"]) < 2

    def test_a_refused_invite_shows_its_error_beside_the_form(
        self, open_page, team, width
    ):
        page = open_page(SETTINGS, phone=width)
        page.fill(".invite-form input[name=email]", LONG_NAME["email"])
        page.click(".invite-form button")
        page.wait_for_selector(".invite-form .form-error")
        fits(page)

    @pytest.mark.parametrize("role", ["editor", "viewer"])
    def test_read_only(self, open_page, db_connection, team, width, role):
        _set_my_role(db_connection, role)
        page = open_page(SETTINGS, phone=width)
        assert page.locator(".invite-form").count() == 0
        fits(page)
        page = open_page(f"{SETTINGS}?confirm=leave", phone=width)
        assert page.locator(".confirm").count() == 1
        fits(page)


@pytest.mark.parametrize("width", PHONE_WIDTHS)
class TestWelcome:
    def test_with_a_workspace_and_no_invites(self, open_page, width):
        page = open_page("/welcome", phone=width)
        assert page.locator(".invite-row").count() == 0
        fits(page)

    def test_with_invites_and_no_workspace(self, open_page, db_connection, width):
        add_user(db_connection, LONG_NAME)
        other = create_workspace(
            db_connection, LONG_NAME["id"], "The Rivera-Montgomery family trust"
        )
        create_invite(
            db_connection, other.id, LONG_NAME["id"], USER["email"], Role.EDITOR
        )
        db_connection.execute(
            "UPDATE workspaces SET deleted_at = now() WHERE id = %s", (WS,)
        )
        db_connection.commit()
        page = open_page("/welcome", phone=width)
        assert page.locator("h1").inner_text().startswith("Welcome")
        fits(page)
        decline = _box(page, ".invite-row button >> nth=0")
        join = _box(page, ".invite-row button >> nth=1")
        assert abs(decline["y"] - join["y"]) < 2

    def test_a_refused_create(self, open_page, width):
        page = open_page("/welcome", phone=width)
        page.evaluate(
            "() => { document.querySelector('.create-form').noValidate = true; }"
        )
        page.fill(".create-form input[name=name]", "   ")
        page.click(".create-form button")
        page.wait_for_selector(".create-form .form-error")
        fits(page)


def _refused_login_html(client, monkeypatch, info: dict) -> str:
    """The real 403 page from the in-process app: the browser's server is a
    subprocess, so its identity provider cannot be faked there."""
    import asset_manager.web.app as app_module

    monkeypatch.setattr(
        app_module,
        "get_oauth_client",
        lambda: SimpleNamespace(idp=FakeIdp(token={"userinfo": info})),
    )
    monkeypatch.setenv("ALLOWED_EMAILS", USER["email"])
    response = client.get("/auth/callback", follow_redirects=False)
    assert response.status_code == 403
    return response.text


@pytest.mark.parametrize("width", PHONE_WIDTHS)
class TestLogin:
    def test_login(self, open_page, width):
        page = open_page("/login", phone=width)
        fits(page)

    @pytest.mark.parametrize(
        "info",
        [
            pytest.param(claims(LONG_NAME), id="not-allowed"),
            pytest.param(claims(USER, email_verified=False), id="unverified"),
        ],
    )
    def test_refused(self, open_page, client, monkeypatch, width, info):
        html = _refused_login_html(client, monkeypatch, info)
        page = open_page("/login", phone=width)
        page.route(
            "**/auth/callback",
            lambda route: route.fulfill(
                status=403, content_type="text/html", body=html
            ),
        )
        page.goto("/auth/callback")
        assert page.locator(".login-card.refused").count() == 1
        fits(page)
