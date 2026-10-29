"""The React app's shell (frontend/src/components/shell), in a real browser
against the built app: the top bar on a desktop, a tablet and a phone, the
bottom tab bar, the account menu, the invite strip, flashes, the drawer
frame, and every page fitting a phone. Each page has its own tests
(test_spa_*.py)."""

import pytest
from playwright.sync_api import Page, expect

from sensibility.invites import create_invite
from sensibility.models import Role
from sensibility.workspaces import create_workspace
from tests.browser.mobile import (
    PHONE_WIDTHS,
    TARGET,
    assert_fits_phone,
    layout_problems,
)
from tests.support import WS
from tests.web_support import USER, add_user

pytestmark = [pytest.mark.browser, pytest.mark.db]

APP = f"/workspaces/{WS}"
JORDAN = {
    "id": 2,
    "sub": "user-2",
    "email": "jordan@example.com",
    "name": "Jordan Swan",
}
LAKE = "The Swan family lake house fund"

# Pages the shell tests open in an empty workspace, and a heading each shows
# (the dashboard's: its first card, with no snapshot yet). Every page and
# drawer state is fitted to a phone in its own test_spa_<area>.py.
PAGES = {
    APP: "Assets",
    f"{APP}/settings": "People",
    "/welcome": "Start your own workspace",
}


@pytest.fixture
def invited(db_connection):
    """Jordan owns workspace 2, with a long name, and invites Me to it."""
    add_user(db_connection, JORDAN)
    create_workspace(db_connection, JORDAN["id"], LAKE)
    create_invite(db_connection, 2, JORDAN["id"], USER["email"], Role.EDITOR)


def settled(page: Page) -> None:
    page.wait_for_function(
        "document.getAnimations().every(a => a.playState === 'finished')"
    )


def box(locator) -> dict:
    found = locator.bounding_box()
    assert found is not None
    return found


def tabbar_h(page: Page) -> str:
    return page.evaluate(
        "getComputedStyle(document.documentElement).getPropertyValue('--tabbar-h').trim()"
    )


def style(locator, prop: str) -> str:
    return locator.evaluate(f"el => getComputedStyle(el).{prop}")


def test_app_goes_to_your_oldest_workspace(open_page):
    page = open_page("/")
    expect(page).to_have_url(f"http://{page.url.split('/')[2]}{APP}")
    expect(
        page.get_by_role("heading", name="Let's get your first net worth")
    ).to_be_visible()


def test_a_lost_session_goes_to_login(open_page):
    page = open_page(APP, user={**USER, "id": 99})
    page.wait_for_url("**/login")


def test_desktop_top_bar(open_page):
    page = open_page(f"{APP}/accounts")
    nav = page.get_by_role("navigation", name="Main")
    expect(nav.get_by_role("link")).to_have_text(
        ["Dashboard", "Accounts", "Cash flows"]
    )
    current = nav.locator('[aria-current="page"]')
    expect(current).to_have_text("Accounts")
    assert style(nav, "position") == "static"
    assert float(style(nav, "borderRadius").removesuffix("px")) >= 999  # a pill
    assert not nav.locator("svg").first.is_visible()
    assert tabbar_h(page) == "0px"
    expect(page.get_by_role("link", name="Sensibility")).to_be_visible()
    picker = page.get_by_role("combobox", name="Workspace")
    expect(picker).to_have_value(str(WS))
    expect(page.get_by_text("Workspace", exact=True)).to_be_visible()
    expect(page.get_by_role("link", name="Workspace settings")).to_have_attribute(
        "href", f"{APP}/settings"
    )
    expect(page.get_by_role("button", name="Account menu for Me")).to_have_text("M")
    assert page.title() == "Test · Sensibility"


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_phone_top_bar_and_tab_bar(open_page, width):
    page = open_page(f"{APP}/accounts", phone=width)
    nav = page.get_by_role("navigation", name="Main")
    expect(nav).to_be_visible()
    assert style(nav, "position") == "fixed"
    bar = box(nav)
    assert bar["x"] == 0 and bar["width"] == width
    assert bar["y"] + bar["height"] == 844 and bar["height"] == 56
    tabs = nav.get_by_role("link")
    assert tabs.count() == 3
    for i in range(3):
        tab = box(tabs.nth(i))
        assert tab["height"] >= TARGET and abs(tab["width"] - width / 3) < 1
        assert tabs.nth(i).locator("svg").is_visible()
    current = nav.locator('[aria-current="page"]')
    expect(current).to_have_text("Accounts")
    assert style(current, "fontWeight") == "600"
    assert style(current, "backgroundColor") == "rgba(0, 0, 0, 0)"
    assert tabbar_h(page).startswith("calc(56px")
    # The workspace is the title; the gear and the avatar sit right, 44px.
    assert not page.get_by_role("link", name="Sensibility").is_visible()
    picker = page.get_by_role("combobox", name="Workspace")
    assert style(picker, "fontSize") == "17px"
    gear = box(page.get_by_role("link", name="Workspace settings"))
    avatar = box(page.get_by_role("button", name="Account menu for Me"))
    assert box(picker)["x"] < gear["x"] < avatar["x"]
    assert gear["width"] == avatar["width"] == TARGET
    assert avatar["x"] + avatar["width"] <= width - 16 + 0.5
    # The page clears the bar.
    pad = page.evaluate(
        "parseFloat(getComputedStyle(document.querySelector('main')).paddingBottom)"
    )
    assert pad >= 56
    assert_fits_phone(page)


@pytest.mark.parametrize("width", [None, *PHONE_WIDTHS])
def test_the_account_menu_opens_and_closes(open_page, width):
    page = open_page(APP, phone=width)
    page.get_by_role("button", name="Account menu for Me").click()
    menu = page.get_by_role("menu")
    expect(menu).to_be_visible()
    expect(menu).to_contain_text(USER["email"])
    new = menu.get_by_role("menuitem", name="New workspace")
    expect(new).to_have_attribute("href", "/welcome")
    expect(menu.get_by_role("menuitem", name="Log out")).to_have_attribute(
        "href", "/logout"
    )
    if width:
        panel = box(menu)
        header = box(page.locator("header"))
        assert panel["y"] < header["y"] + header["height"] + 8
        assert panel["x"] >= 16 - 0.5
        assert panel["x"] + panel["width"] <= width - 16 + 0.5
        for item in menu.get_by_role("menuitem").all():
            assert box(item)["height"] >= TARGET
        assert_fits_phone(page)
        # A tap elsewhere closes it.
        page.mouse.click(width / 2, 600)
    else:
        page.keyboard.press("Escape")
    expect(menu).to_be_hidden()
    # New workspace is a client-side move to the welcome page.
    page.get_by_role("button", name="Account menu for Me").click()
    page.get_by_role("menuitem", name="New workspace").click()
    page.wait_for_url("**/welcome")
    expect(page.get_by_role("heading", name="New workspace")).to_be_visible()


def test_the_picker_switches_workspace_keeping_the_section(open_page, invited):
    page = open_page(f"{APP}/accounts")
    # Join first, so there are two workspaces to pick from.
    page.get_by_role("button", name=f"Join {LAKE}").click()
    page.wait_for_url("**/workspaces/2")
    page.goto(f"{APP}/accounts")
    page.get_by_role("combobox", name="Workspace").select_option(label=LAKE)
    page.wait_for_url("**/workspaces/2/accounts")


@pytest.mark.parametrize("width", [None, *PHONE_WIDTHS])
def test_the_invite_strip_shows_and_joins(open_page, invited, width):
    page = open_page(APP, phone=width)
    strip = page.get_by_role("region", name=f"Invite to {LAKE}")
    expect(strip).to_contain_text(f"to {LAKE} as an editor.")
    expect(strip).to_contain_text("Expires")
    if width:
        text = box(strip.get_by_text("Expires"))
        decline = box(strip.get_by_role("button", name="Decline"))
        join = box(strip.get_by_role("button", name=f"Join {LAKE}"))
        assert decline["y"] >= text["y"] + text["height"]
        assert decline["y"] == join["y"] and decline["height"] >= TARGET
        assert abs(decline["width"] - join["width"]) < 1
        assert_fits_phone(page)
    strip.get_by_role("button", name=f"Join {LAKE}").click()
    page.wait_for_url("**/workspaces/2")
    expect(page.get_by_role("status")).to_contain_text(f"Joined {LAKE} as an editor.")
    expect(page.get_by_role("region", name=f"Invite to {LAKE}")).to_have_count(0)
    expect(page.get_by_role("combobox", name="Workspace")).to_have_value("2")


def test_declining_removes_the_strip(open_page, invited):
    page = open_page(APP)
    page.get_by_role("button", name="Decline").click()
    expect(page.get_by_role("status")).to_contain_text(
        f"Declined the invite to {LAKE}."
    )
    expect(page.get_by_role("region", name=f"Invite to {LAKE}")).to_have_count(0)
    assert page.url.endswith(APP)


def test_an_api_write_without_the_header_is_refused(open_page):
    """The browser's session alone cannot write: the SPA's header is required."""
    page = open_page(APP)
    refused = page.request.post("/api/workspaces", data={"name": "Sneaky"})
    assert refused.status == 403
    assert refused.json() == {
        "error": "Missing the X-Requested-With: sensibility header"
    }
    allowed = page.request.post(
        "/api/workspaces",
        data={"name": "Ours"},
        headers={"X-Requested-With": "sensibility"},
    )
    assert allowed.status == 201


@pytest.mark.parametrize("width", [None, *PHONE_WIDTHS])
def test_a_drawer_is_a_side_panel_or_a_full_screen_sheet(open_page, width):
    page = open_page(f"{APP}/accounts/new", phone=width)
    dialog = page.get_by_role("dialog", name="New asset")
    expect(dialog).to_be_visible()
    settled(page)
    frame = box(dialog)
    if width:
        assert frame == {"x": 0, "y": 0, "width": width, "height": 844}
    else:
        assert frame["width"] == 500 and frame["x"] + 500 == 1280
        assert frame["height"] == 900
    foot = box(page.locator("[data-slot=sheet-foot]"))
    assert foot["y"] + foot["height"] == frame["y"] + frame["height"]
    close = box(dialog.get_by_role("button", name="Close"))
    assert close["width"] >= TARGET and close["height"] >= TARGET
    if width:
        assert close["x"] + close["width"] <= width
        # Cancel and Save share the footer's row equally.
        cancel = box(dialog.get_by_role("button", name="Cancel"))
        save = box(dialog.get_by_role("button", name="Save"))
        assert cancel["y"] == save["y"] and abs(cancel["width"] - save["width"]) < 1
        assert cancel["height"] >= TARGET
        assert layout_problems(page)["overflow"] <= 0
        # The tab bar is under the sheet.
        assert page.evaluate(
            "document.elementFromPoint(innerWidth / 2, innerHeight - 20)"
            ".closest('[role=dialog]') !== null"
        )
    # The page behind is inert.
    assert page.get_by_role("navigation", name="Main").count() == 0
    page.keyboard.press("Escape")
    page.wait_for_url(f"**{APP}/accounts")
    expect(dialog).to_be_hidden()
    expect(page.get_by_role("navigation", name="Main")).to_be_visible()


def test_a_cash_flow_drawer_closes_to_the_same_period(open_page):
    page = open_page(f"{APP}/cash-flows/new?per=year")
    page.get_by_role("dialog").get_by_role("button", name="Cancel").click()
    page.wait_for_url(f"**{APP}/cash-flows?per=year")


@pytest.mark.parametrize("width", PHONE_WIDTHS)
@pytest.mark.parametrize("path", sorted(PAGES))
def test_every_page_fits_a_phone(open_page, path, width):
    page = open_page(path, phone=width)
    expect(page.get_by_role("heading", level=2, name=PAGES[path])).to_be_visible()
    assert_fits_phone(page)


@pytest.mark.parametrize("width", PHONE_WIDTHS)
@pytest.mark.parametrize("path", ["", "/accounts", "/cash-flows", "/settings"])
def test_the_top_bar_is_one_row_on_every_page(open_page, seeded, path, width):
    page = open_page(APP + path, phone=width)
    # An empty page's heading is its empty card's h1.
    expect(page.locator("main :is(h1, h2)").first).to_be_visible()
    picker = page.get_by_role("combobox", name="Workspace")
    gear = box(page.get_by_role("link", name="Workspace settings"))
    avatar = box(page.get_by_role("button", name="Account menu for Me"))
    at = box(picker)
    assert at["x"] < gear["x"] < avatar["x"]
    middle = at["y"] + at["height"] / 2
    assert abs(middle - (gear["y"] + gear["height"] / 2)) < 2
    assert abs(middle - (avatar["y"] + avatar["height"] / 2)) < 2
    assert gear["width"] == avatar["width"] == TARGET
    assert avatar["x"] + avatar["width"] <= width - 16 + 0.5
    assert not page.get_by_role("link", name="Sensibility").is_visible()
    assert style(picker, "fontSize") == "17px"
    assert_fits_phone(page)


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_welcome_keeps_the_wordmark_and_has_no_tab_bar(open_page, invited, width):
    page = open_page("/welcome", phone=width)
    expect(page.get_by_role("heading", level=1)).to_be_visible()
    expect(page.get_by_role("link", name="Sensibility")).to_be_visible()
    expect(page.get_by_role("button", name="Account menu for Me")).to_be_visible()
    expect(page.get_by_role("navigation", name="Main")).to_have_count(0)
    assert tabbar_h(page) == "0px"
    assert_fits_phone(page)


def test_a_focused_field_leaves_the_tab_bar_in_place(open_page, seeded):
    """Moving the bar on focus would move the save bar above it, so the tap
    that blurs the field would land where a button used to be."""
    page = open_page(f"{APP}/accounts", phone=390)
    nav = page.get_by_role("navigation", name="Main")
    expect(nav).to_be_visible()
    field = page.get_by_label("Amount for Checking")
    expect(field).to_be_visible()
    before = box(nav)
    bar = page.locator("[data-save-bar-wrap]")
    bar_before = bar.bounding_box()
    field.focus()
    assert tabbar_h(page).startswith("calc(56px")
    expect(nav).to_be_visible()
    assert box(nav) == before
    assert bar.bounding_box() == bar_before


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_a_flash_fits_a_phone_and_dismisses(open_page, invited, width):
    page = open_page(APP, phone=width)
    page.get_by_role("button", name="Decline").click()
    flash = page.locator("[data-slot=flash]")
    expect(flash).to_contain_text(f"Declined the invite to {LAKE}.")
    # At once: a success flash fades after a few seconds.
    assert_fits_phone(page)
    dismiss = flash.get_by_role("button", name="Dismiss")
    found = box(dismiss)
    assert found["width"] >= TARGET and found["height"] >= TARGET
    dismiss.click()
    expect(flash).to_have_count(0)


def test_desktop_and_tablet_do_not_scroll_sideways(open_page, seeded, invited):
    page = open_page(APP)
    expect(page.locator("main h2").first).to_be_visible()
    found = layout_problems(page)
    assert found["overflow"] <= 0, found["wide"]
    # A tablet: the desktop layout, opened at 768px (reloaded, so the chart
    # lays itself out for that width).
    page.set_viewport_size({"width": 768, "height": 1024})
    page.reload()
    expect(page.locator("main h2").first).to_be_visible()
    found = layout_problems(page)
    assert found["overflow"] <= 0, found["wide"]
    assert style(page.get_by_role("navigation", name="Main"), "position") == "static"


def test_every_page_chunk_is_preloaded(open_page):
    """Once the first page has rendered, the browser fetches every other
    page's and drawer's chunk while idle, so no click waits for one."""
    page = open_page(APP)
    expect(page.locator("main :is(h1, h2)").first).to_be_visible()
    chunks = ["welcome", "accounts", "account-drawer", "cash-flows"]
    chunks += ["cash-flow-drawer", "cash-flow-categories", "settings"]
    page.wait_for_function(
        """names => names.every(name => performance.getEntriesByType('resource')
            .some(e => new URL(e.name).pathname.startsWith(`/assets/${name}-`)))""",
        arg=chunks,
    )
