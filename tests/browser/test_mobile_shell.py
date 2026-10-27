"""The shell on phones (docs/superpowers/specs/2026-10-26-mobile-design.md, "Shell"):
the top bar, the bottom tab bar, the account menu, the invite strip and
flash, and the drawer frame. Desktop keeps the pill nav.

Page content belongs to the other mobile test files, so the layout checks
here are scoped to the shell's own elements.
"""

import pytest
from playwright.sync_api import Page

from sensibility.invites import create_invite
from sensibility.models import Role
from sensibility.workspaces import create_workspace
from tests.browser.mobile import PHONE_WIDTHS, TARGET, layout_problems
from tests.web_support import PAGES, USER, add_user

pytestmark = [pytest.mark.browser, pytest.mark.db]

SHELL = "header, .main-nav, .invite-strip, .flash"
JORDAN = {
    "id": 2,
    "sub": "user-2",
    "email": "jordan@example.com",
    "name": "Jordan Swan",
}


@pytest.fixture
def invited(db_connection):
    """Jordan owns workspace 2, with a long name, and invites Me to it."""
    add_user(db_connection, JORDAN)
    create_workspace(db_connection, JORDAN["id"], "The Swan family lake house fund")
    create_invite(db_connection, 2, JORDAN["id"], USER["email"], Role.EDITOR)


def shell_problems(page: Page) -> dict:
    """layout_problems, keeping only what is in the shell."""
    page.evaluate(
        """(sel) => {
        for (const el of document.querySelectorAll('main a[href], main button, main input, main select, main textarea, main summary')) {
            if (!el.closest(sel)) el.dataset.notShell = '';
        }
    }""",
        SHELL,
    )
    return layout_problems(page, ("[data-not-shell]",))


def assert_shell_fits(page: Page) -> None:
    p = shell_problems(page)
    assert p["overflow"] <= 0, p["wide"]
    assert not p["small"], p["small"]
    # Fields: only the shell's own (the workspace picker); pages check theirs.
    sizes = page.evaluate(
        """() => [...document.querySelectorAll('header :is(input, select, textarea)')]
            .map((el) => parseFloat(getComputedStyle(el).fontSize))"""
    )
    assert all(size >= 16 for size in sizes), sizes


def box(page: Page, selector: str) -> dict:
    found = page.locator(selector).first.bounding_box()
    assert found is not None, selector
    return found


def tabbar_h(page: Page) -> str:
    return page.evaluate(
        "getComputedStyle(document.documentElement).getPropertyValue('--tabbar-h').trim()"
    )


@pytest.mark.parametrize("width", PHONE_WIDTHS)
@pytest.mark.parametrize(
    "path", [PAGES, f"{PAGES}/accounts", f"{PAGES}/cash-flows", f"{PAGES}/settings"]
)
def test_top_bar_and_tab_bar_fit(open_page, seeded, path, width):
    page = open_page(path, phone=width)
    assert_shell_fits(page)
    # One row: the workspace title, then the gear and the avatar, 44px each.
    picker = box(page, ".workspace-picker select")
    gear = box(page, ".round-button")
    avatar = box(page, ".user-menu summary")
    assert picker["x"] < gear["x"] < avatar["x"]
    assert (
        abs(picker["y"] + picker["height"] / 2 - (gear["y"] + gear["height"] / 2)) < 2
    )
    assert gear["width"] == avatar["width"] == TARGET
    assert avatar["x"] + avatar["width"] <= width - 16 + 0.5
    assert not page.locator(".wordmark").is_visible()
    # The picker is still labelled "Workspace", though the label is hidden.
    assert page.locator("header").get_by_role("combobox", name="Workspace").count() == 1
    assert (
        page.evaluate(
            "getComputedStyle(document.querySelector('.workspace-picker select')).fontSize"
        )
        == "17px"
    )


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_welcome_keeps_the_wordmark_and_has_no_tab_bar(
    open_page, seeded, invited, width
):
    page = open_page("/welcome", phone=width)
    assert_shell_fits(page)
    assert page.locator(".wordmark").is_visible()
    assert page.locator(".user-menu summary").is_visible()
    assert page.locator(".main-nav").count() == 0
    assert tabbar_h(page) == "0px"


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_tab_bar_is_fixed_at_the_bottom_and_marks_the_page(open_page, seeded, width):
    page = open_page(f"{PAGES}/accounts", phone=width)
    nav = page.locator("nav.main-nav")
    assert page.get_by_role("navigation").count() == 1
    assert nav.evaluate("el => getComputedStyle(el).position") == "fixed"
    bar = box(page, "nav.main-nav")
    assert bar["x"] == 0 and bar["width"] == width
    assert bar["y"] + bar["height"] == 844
    assert bar["height"] == 56
    tabs = nav.locator("a")
    assert tabs.count() == 3
    for i in range(3):
        tab = tabs.nth(i).bounding_box()
        assert tab is not None
        assert tab["height"] >= TARGET and abs(tab["width"] - width / 3) < 1
        assert tabs.nth(i).locator("svg").is_visible()
    current = nav.locator('a[aria-current="page"]')
    assert current.inner_text() == "Accounts"
    assert current.evaluate("el => getComputedStyle(el).fontWeight") == "600"
    # The page clears it: main pads its bottom by the bar's height.
    pad = page.evaluate(
        "parseFloat(getComputedStyle(document.querySelector('main')).paddingBottom)"
    )
    assert pad >= 56
    # Still the pill nav, unchanged, on a desktop.
    desk = open_page(f"{PAGES}/accounts")
    nav = desk.locator("nav.main-nav")
    assert nav.evaluate("el => getComputedStyle(el).position") == "static"
    assert nav.evaluate("el => getComputedStyle(el).borderRadius") == "999px"
    assert not nav.locator("svg").first.is_visible()
    assert tabbar_h(desk) == "0px"
    assert desk.locator(".wordmark").is_visible()
    assert desk.locator(".picker-label").is_visible()


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_account_menu_opens_on_screen(open_page, seeded, width):
    page = open_page(PAGES, phone=width)
    page.locator(".user-menu summary").click()
    panel = box(page, ".user-menu-panel")
    assert panel["x"] >= 16 - 0.5 and panel["x"] + panel["width"] <= width - 16 + 0.5
    header = box(page, "header")
    assert panel["y"] < header["y"] + header["height"] + 8
    for name in ("New workspace", "Log out"):
        button = page.locator(".user-menu-panel").get_by_role("link", name=name)
        b = button.bounding_box()
        assert b is not None and b["height"] >= TARGET
        assert b["x"] >= 0 and b["x"] + b["width"] <= width
    assert_shell_fits(page)
    # A tap elsewhere closes it.
    page.mouse.click(width / 2, 600)
    assert not page.locator(".user-menu-panel").is_visible()


def test_a_focused_field_leaves_the_tab_bar_in_place(open_page, seeded):
    # Moving the bar on focus moves the save bar above it, so the tap that
    # blurs the field would land where a button used to be.
    page = open_page(f"{PAGES}/accounts", phone=390)
    nav = page.locator("nav.main-nav")
    before = nav.bounding_box()
    page.locator("main input.money-input").first.focus()
    assert tabbar_h(page).startswith("calc(56px")
    assert nav.is_visible() and nav.bounding_box() == before


def test_all_fields_are_16px_on_phones(open_page, seeded):
    page = open_page(f"{PAGES}/accounts", phone=320)
    sizes = page.evaluate(
        "[...document.querySelectorAll('main input.money-input')].map(el => getComputedStyle(el).fontSize)"
    )
    assert sizes and set(sizes) == {"16px"}


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_drawer_is_a_full_screen_sheet(open_page, seeded, width):
    page = open_page(f"{PAGES}/accounts/new", phone=width)
    # The sheet slides up; measure once it has arrived.
    page.wait_for_function(
        "document.getAnimations().every(a => a.playState === 'finished')"
    )
    drawer = box(page, ".drawer")
    assert drawer == {"x": 0, "y": 0, "width": width, "height": 844}
    foot = box(page, ".drawer-foot")
    assert foot["y"] + foot["height"] == 844
    close = box(page, ".drawer-close")
    assert close["width"] >= TARGET and close["height"] >= TARGET
    assert close["x"] + close["width"] <= width
    # Cancel and Save share the footer's row equally.
    buttons = page.locator(".drawer-foot .btn")
    a, b = buttons.nth(0).bounding_box(), buttons.nth(1).bounding_box()
    assert a is not None and b is not None
    assert a["y"] == b["y"] and abs(a["width"] - b["width"]) < 1
    assert a["height"] >= TARGET
    assert layout_problems(page)["overflow"] <= 0
    # The tab bar is under the sheet.
    assert page.evaluate(
        "document.elementFromPoint(innerWidth / 2, innerHeight - 20).closest('.drawer') !== null"
    )


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_invite_strip_and_flash_fit(open_page, seeded, invited, width):
    page = open_page(PAGES, phone=width)
    assert_shell_fits(page)
    strip = page.locator(".invite-strip")
    text = box(page, ".invite-strip .invite-text")
    decline = box(page, ".invite-strip .invite-actions form:first-child .btn")
    join = box(page, ".invite-strip .invite-actions form:last-child .btn")
    assert decline["y"] >= text["y"] + text["height"]
    assert decline["y"] == join["y"] and abs(decline["width"] - join["width"]) < 1
    strip.get_by_role("button", name="Decline").click()
    flash = page.locator(".flash")
    flash.wait_for()
    assert_shell_fits(page)
    dismiss = box(page, ".flash-dismiss")
    assert dismiss["width"] >= TARGET and dismiss["height"] >= TARGET
    page.locator(".flash-dismiss").click()
    assert flash.count() == 0


def test_desktop_and_tablet_do_not_scroll_sideways(open_page, seeded, invited):
    page = open_page(PAGES)
    p = layout_problems(page)
    assert p["overflow"] <= 0, p["wide"]
    # A tablet: the desktop layout, opened at 768px (reloaded, so the chart
    # lays itself out for that width).
    page.set_viewport_size({"width": 768, "height": 1024})
    page.reload()
    p = layout_problems(page)
    assert p["overflow"] <= 0, p["wide"]
    assert (
        page.locator("nav.main-nav").evaluate("el => getComputedStyle(el).position")
        == "static"
    )
