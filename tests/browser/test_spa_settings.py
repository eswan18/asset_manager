"""The React settings and welcome pages under /app (frontend/src/routes/
settings.tsx and welcome.tsx), in a real browser against the built app: the
Jinja pages' behaviors (test_settings_page.py, test_welcome_page.py) and
phone layouts (test_mobile_settings.py), at /app paths.

Every write goes through the JSON API; the confirms are in the page, through
`?confirm=`, as the Jinja page's are."""

import re
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from sensibility import repository as repo
from sensibility.invites import create_invite
from sensibility.models import Role
from sensibility.workspaces import create_workspace
from tests.browser.mobile import PHONE_WIDTHS, assert_fits_phone
from tests.support import USER_ID, WS
from tests.web_support import USER, add_user

pytestmark = [pytest.mark.browser, pytest.mark.db]

APP = f"/app/workspaces/{WS}"
SETTINGS = f"{APP}/settings"
WELCOME = "/app/welcome"

LONG_NAME: dict[str, Any] = {
    "id": 2,
    "sub": "user-2",
    "email": "alexandra.rivera-montgomery.the.third@example.com",
    "name": "Alexandra Rivera-Montgomery-Featherstonehaugh",
}
OTHER: dict[str, Any] = {
    "id": 3,
    "sub": "user-3",
    "email": "casey@example.com",
    "name": "Casey Park",
}
LONG_INVITE = "someone.with.a.very.long.address.indeed@example.com"
TRUST = "The Rivera-Montgomery family trust"
ME_EMAIL = str(USER["email"])


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


def roles(conn) -> dict[int, Role]:
    return {m.user_id: m.role for m in repo.get_members(conn, WS)}


def box(locator) -> dict:
    found = locator.bounding_box()
    assert found is not None
    return found


def open_settings(open_page, path: str = SETTINGS, **kwargs) -> Page:
    page = open_page(path, **kwargs)
    expect(page.get_by_role("heading", level=1, name="Test settings")).to_be_visible()
    return page


def confirms(page: Page):
    return page.locator("[data-slot=confirm]")


def flashed(page: Page, text: str) -> None:
    expect(page.get_by_role("status").filter(has_text=text)).to_be_visible()


# --- layout ------------------------------------------------------------------


def test_desktop_has_two_columns(open_page, team):
    page = open_settings(open_page)
    outline = box(page.get_by_role("region", name="Leave or delete"))
    people = box(page.get_by_role("heading", name="People"))
    assert people["x"] > outline["x"] + outline["width"]
    assert people["y"] < outline["y"] + outline["height"]
    # One row per person: role select and × beside the name.
    row = page.get_by_role("listitem").filter(has_text=LONG_NAME["name"])
    name = box(row.get_by_text(LONG_NAME["name"]))
    select = box(row.get_by_role("combobox"))
    assert select["x"] > name["x"] + name["width"] - 1
    assert page.title() == "Settings · Test · Sensibility"


def test_one_column_from_860px(open_page, team):
    page = open_settings(open_page)
    page.set_viewport_size({"width": 860, "height": 900})
    outline = box(page.get_by_role("region", name="Leave or delete"))
    people = box(page.get_by_role("heading", name="People"))
    assert people["y"] > outline["y"] + outline["height"]


@pytest.mark.parametrize("width", PHONE_WIDTHS)
class TestSettingsOnAPhone:
    def test_owner(self, open_page, team, width):
        page = open_settings(open_page, phone=width)
        assert_fits_phone(page)
        # One column: People comes under Leave / Delete.
        outline = box(page.get_by_role("region", name="Leave or delete"))
        people = box(page.get_by_role("heading", name="People"))
        assert people["y"] > outline["y"] + outline["height"]
        # The invite form stacks: email on its own row, then role and Invite.
        form = page.get_by_role("form", name="Invite")
        email = box(form.get_by_role("textbox", name="Invite by email"))
        role = box(form.get_by_role("combobox", name="Role"))
        invite = box(form.get_by_role("button", name="Invite"))
        assert role["y"] >= email["y"] + email["height"]
        assert abs(role["y"] - invite["y"]) < 2
        # A person's role and × sit together under their name and email.
        row = page.get_by_role("listitem").filter(has_text=LONG_NAME["name"])
        main = box(row.get_by_text(LONG_NAME["email"]))
        select = box(row.get_by_role("combobox"))
        remove = box(row.get_by_role("link", name=f"Remove {LONG_NAME['name']}"))
        assert select["y"] >= main["y"] + main["height"]
        assert abs(select["y"] - remove["y"]) < 2
        assert remove["x"] > select["x"]

    @pytest.mark.parametrize(
        "confirm", ["member-2", "member-1", "invite", "leave", "delete"]
    )
    def test_owner_confirms(self, open_page, team, width, confirm):
        if confirm == "invite":
            confirm = f"invite-{team.id}"
        page = open_settings(open_page, f"{SETTINGS}?confirm={confirm}", phone=width)
        expect(confirms(page)).to_have_count(1)
        assert_fits_phone(page)

    def test_confirm_buttons_share_a_row(self, open_page, team, width):
        page = open_settings(
            open_page, f"{SETTINGS}?confirm=invite-{team.id}", phone=width
        )
        keep = box(confirms(page).get_by_role("link", name="Keep"))
        revoke = box(confirms(page).get_by_role("button", name="Revoke invite"))
        assert abs(keep["y"] - revoke["y"]) < 2

    def test_a_refused_invite_shows_its_error_beside_the_form(
        self, open_page, team, width
    ):
        page = open_settings(open_page, phone=width)
        form = page.get_by_role("form", name="Invite")
        form.get_by_role("textbox", name="Invite by email").fill(LONG_NAME["email"])
        form.get_by_role("button", name="Invite").click()
        expect(form.get_by_role("alert")).to_contain_text(
            "is already a member of this workspace"
        )
        assert_fits_phone(page)

    @pytest.mark.parametrize("role", ["editor", "viewer"])
    def test_read_only(self, open_page, db_connection, team, width, role):
        _set_my_role(db_connection, role)
        page = open_settings(open_page, phone=width)
        expect(page.get_by_role("form", name="Invite")).to_have_count(0)
        assert_fits_phone(page)
        page.get_by_role("region", name="Leave or delete").get_by_role(
            "link", name="Leave"
        ).click()
        expect(confirms(page)).to_have_count(1)
        assert_fits_phone(page)


# --- settings, interactively ---------------------------------------------------


def test_renames(open_page, db_connection, team):
    page = open_settings(open_page)
    page.get_by_role("textbox", name="Name").fill(" Household ")
    page.get_by_role("button", name="Save").click()
    flashed(page, "Saved Household.")
    expect(
        page.get_by_role("heading", level=1, name="Household settings")
    ).to_be_visible()
    # The picker has it too, without a reload.
    expect(page.get_by_role("combobox", name="Workspace")).to_contain_text("Household")
    renamed = repo.get_workspace(db_connection, WS)
    assert renamed is not None and renamed.name == "Household"


def test_a_blank_name_is_refused_in_the_form(open_page, team):
    page = open_settings(open_page)
    field = page.get_by_role("textbox", name="Name")
    field.fill("   ")
    page.get_by_role("button", name="Save").click()
    general = page.locator("section", has=page.get_by_role("heading", name="General"))
    expect(general.get_by_role("alert")).to_have_text("Name is required")
    expect(field).to_have_value("   ")
    expect(field).to_be_focused()


def test_choosing_a_role_saves_it(open_page, db_connection, team):
    page = open_settings(open_page)
    page.get_by_role("combobox", name="Role for Casey Park").select_option("editor")
    flashed(page, "Casey Park is now an editor.")
    assert roles(db_connection)[3] == Role.EDITOR


def test_the_last_owner_cannot_be_demoted(open_page, db_connection):
    page = open_settings(open_page)
    select = page.get_by_role("combobox", name="Role for Me")
    select.select_option("viewer")
    expect(page.get_by_role("alert")).to_contain_text(
        "A workspace needs at least one owner."
    )
    expect(select).to_have_value("owner")
    assert roles(db_connection)[USER_ID] == Role.OWNER


def test_demoting_yourself_leaves_a_read_only_page(open_page, db_connection, team):
    page = open_settings(open_page)
    page.get_by_role("combobox", name="Role for Me").select_option("editor")
    flashed(page, "You're now an editor.")
    expect(page.get_by_text("You're an editor of this workspace.")).to_be_visible()
    expect(page.get_by_role("form", name="Invite")).to_have_count(0)
    expect(page.get_by_role("heading", name="General")).to_have_count(0)


def test_asks_in_the_row_then_removes(open_page, db_connection, team):
    page = open_settings(open_page)
    page.get_by_role("link", name="Remove Casey Park").click()
    expect(page).to_have_url(re.compile(r"\?confirm=member-3$"))
    confirm = confirms(page)
    expect(confirm).to_contain_text(
        "Remove Casey Park? They lose access to Test right away."
    )
    expect(confirm.get_by_role("link", name="Keep")).to_be_focused()
    confirm.get_by_role("button", name="Remove").click()
    flashed(page, "Removed Casey Park.")
    expect(confirms(page)).to_have_count(0)
    # In the page: the flash is a list item too.
    main = page.get_by_role("main")
    expect(main.get_by_role("listitem").filter(has_text="Casey Park")).to_have_count(0)
    assert 3 not in roles(db_connection)


def test_keep_changes_nothing(open_page, db_connection, team):
    page = open_settings(open_page, f"{SETTINGS}?confirm=member-3")
    confirms(page).get_by_role("link", name="Keep").click()
    expect(page).to_have_url(re.compile(r"/settings$"))
    expect(confirms(page)).to_have_count(0)
    assert 3 in roles(db_connection)


def test_asks_in_the_row_then_revokes(open_page, db_connection, team):
    page = open_settings(open_page)
    expect(page.get_by_text("3 members · 1 invited")).to_be_visible()
    page.get_by_role("link", name=f"Revoke the invite to {LONG_INVITE}").click()
    confirm = confirms(page)
    expect(confirm).to_contain_text(f"Revoke the invite to {LONG_INVITE}?")
    confirm.get_by_role("button", name="Revoke invite").click()
    flashed(page, f"Revoked the invite to {LONG_INVITE}.")
    expect(page.get_by_text("3 members", exact=True)).to_be_visible()
    assert repo.get_pending_workspace_invites(db_connection, WS) == []


def test_invites_with_the_role(open_page, db_connection, team):
    page = open_settings(open_page)
    form = page.get_by_role("form", name="Invite")
    form.get_by_role("textbox", name="Invite by email").fill("New@example.com")
    form.get_by_role("combobox", name="Role").select_option("owner")
    form.get_by_role("button", name="Invite").click()
    flashed(page, "Invited new@example.com as an owner.")
    expect(page.get_by_text("3 members · 2 invited")).to_be_visible()
    expect(form.get_by_role("textbox", name="Invite by email")).to_have_value("")
    invites = repo.get_pending_workspace_invites(db_connection, WS)
    assert (invites[-1].email, invites[-1].role) == ("new@example.com", Role.OWNER)


def test_a_lapsed_invite_says_so(open_page, db_connection, team):
    """An invite speaks for its sender: once they are not an owner it cannot
    be accepted, and the list says why."""
    create_invite(db_connection, WS, LONG_NAME["id"], "late@example.com", Role.VIEWER)
    repo.set_member_role(db_connection, WS, LONG_NAME["id"], Role.EDITOR)
    db_connection.commit()
    page = open_settings(open_page)
    row = page.get_by_role("listitem").filter(has_text="late@example.com")
    expect(row).to_contain_text(f"Sent by {LONG_NAME['name']} ")
    expect(row).to_contain_text(f"lapsed: {LONG_NAME['name']} is no longer an owner")


def test_leaving_goes_home(open_page, db_connection, team):
    page = open_settings(open_page)
    page.get_by_role("region", name="Leave or delete").get_by_role(
        "link", name="Leave"
    ).click()
    page.get_by_role("button", name="Leave workspace").click()
    # No workspace left: home is the welcome page, with the flash.
    page.wait_for_url(f"**{WELCOME}")
    flashed(page, "You left Test.")
    expect(page.get_by_role("heading", level=1, name="Welcome, Me")).to_be_visible()
    assert USER_ID not in roles(db_connection)


def test_leaving_from_your_own_row(open_page, db_connection, team):
    page = open_settings(open_page)
    page.get_by_role("link", name="Leave Test").click()
    expect(page).to_have_url(re.compile(rf"\?confirm=member-{USER_ID}$"))
    confirms(page).get_by_role("button", name="Leave workspace").click()
    page.wait_for_url(f"**{WELCOME}")
    assert USER_ID not in roles(db_connection)


def test_the_only_owner_cannot_leave(open_page):
    page = open_settings(open_page, f"{SETTINGS}?confirm=leave")
    expect(confirms(page)).to_have_count(0)
    expect(
        page.get_by_text("You're its only owner, so you can't leave.")
    ).to_be_visible()


def test_deleting_goes_to_your_next_workspace(open_page, db_connection, team):
    other = create_workspace(db_connection, USER_ID, "Second")
    page = open_settings(open_page)
    page.get_by_role("link", name="Delete workspace").click()
    confirm = confirms(page)
    expect(confirm).to_contain_text("Delete Test for all 3 members?")
    confirm.get_by_role("button", name="Delete workspace").click()
    page.wait_for_url(f"**/app/workspaces/{other.id}")
    flashed(page, "Deleted Test.")
    expect(page.get_by_role("combobox", name="Workspace")).to_have_value(str(other.id))
    gone = repo.get_workspace(db_connection, WS)
    assert gone is not None and gone.deleted_at is not None  # soft


# --- welcome ---------------------------------------------------------------------


@pytest.fixture
def invited_elsewhere(db_connection):
    """The long-named user owns the trust and invites Me to it as an editor."""
    add_user(db_connection, LONG_NAME)
    trust = create_workspace(db_connection, LONG_NAME["id"], TRUST)
    create_invite(db_connection, trust.id, LONG_NAME["id"], ME_EMAIL, Role.EDITOR)
    return trust


def _no_workspace(conn) -> None:
    conn.execute("UPDATE workspaces SET deleted_at = now() WHERE id = %s", (WS,))
    conn.commit()


@pytest.mark.parametrize("width", PHONE_WIDTHS)
class TestWelcomeOnAPhone:
    def test_with_a_workspace_and_no_invites(self, open_page, width):
        page = open_page(WELCOME, phone=width)
        expect(
            page.get_by_role("heading", level=1, name="New workspace")
        ).to_be_visible()
        expect(page.get_by_role("button", name=re.compile("^Join"))).to_have_count(0)
        assert_fits_phone(page)

    def test_with_invites_and_no_workspace(
        self, open_page, db_connection, invited_elsewhere, width
    ):
        _no_workspace(db_connection)
        page = open_page(WELCOME, phone=width)
        expect(page.get_by_role("heading", level=1)).to_have_text("Welcome, Me")
        decline = page.get_by_role("button", name=f"Decline the invite to {TRUST}")
        join = page.get_by_role("button", name=f"Join {TRUST}")
        expect(join).to_be_visible()
        assert_fits_phone(page)
        assert abs(box(decline)["y"] - box(join)["y"]) < 2

    def test_a_refused_create(self, open_page, width):
        page = open_page(WELCOME, phone=width)
        page.get_by_role("textbox", name="Name").fill("   ")
        page.get_by_role("button", name="Create workspace").click()
        expect(page.get_by_role("alert")).to_have_text("Name is required")
        assert_fits_phone(page)


def test_welcome_creates_and_goes_into_it(open_page, db_connection):
    page = open_page(WELCOME)
    page.get_by_role("textbox", name="Name").fill(" Personal ")
    page.get_by_role("button", name="Create workspace").click()
    page.wait_for_url("**/app/workspaces/2")
    flashed(page, "Created Personal.")
    expect(page.get_by_role("combobox", name="Workspace")).to_have_value("2")
    found = repo.get_access(db_connection, 2, USER_ID)
    assert found is not None and (found[0].name, found[1]) == ("Personal", Role.OWNER)


def test_welcome_joins(open_page, db_connection, invited_elsewhere):
    _no_workspace(db_connection)
    page = open_page(WELCOME)
    page.get_by_role("button", name=f"Join {TRUST}").click()
    page.wait_for_url(f"**/app/workspaces/{invited_elsewhere.id}")
    flashed(page, f"Joined {TRUST} as an editor.")
    expect(page.get_by_role("combobox", name="Workspace")).to_have_value(
        str(invited_elsewhere.id)
    )


def test_welcome_declines_and_stays(open_page, db_connection, invited_elsewhere):
    page = open_page(WELCOME)
    page.get_by_role("button", name=f"Decline the invite to {TRUST}").click()
    flashed(page, f"Declined the invite to {TRUST}.")
    expect(page.get_by_role("button", name=f"Join {TRUST}")).to_have_count(0)
    assert page.url.endswith(WELCOME)
    # With no invites left, Create is the primary button again: no divider.
    expect(page.get_by_text("or", exact=True)).to_have_count(0)


def test_the_account_menu_reaches_welcome(open_page):
    page = open_settings(open_page)
    page.get_by_role("button", name="Account menu for Me").click()
    page.get_by_role("menuitem", name="New workspace").click()
    page.wait_for_url(f"**{WELCOME}")
    expect(page.get_by_role("heading", level=1, name="New workspace")).to_be_visible()
