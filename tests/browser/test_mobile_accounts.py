"""The Accounts page and the account drawer on a phone
(docs/superpowers/specs/2026-10-26-mobile-design.md, "Accounts").

Every state is checked at 320px and 390px with assert_fits_phone.
"""

from datetime import date

import pytest
from playwright.sync_api import Page, expect

from sensibility.accounts import create_account, retire_account
from sensibility.models import RecordType
from tests.browser.mobile import PHONE_WIDTHS, assert_fits_phone
from tests.support import WS
from tests.web_support import PAGES

pytestmark = [pytest.mark.browser, pytest.mark.db]

ACCOUNTS = f"{PAGES}/accounts"


@pytest.fixture
def with_retired(db_connection, seeded):
    """seeded, plus a retired account, so "Show retired" appears."""
    old = create_account(db_connection, WS, "Old savings", RecordType.ASSET)
    retire_account(db_connection, WS, old.id, date(2026, 9, 1))
    db_connection.commit()
    return {**seeded, "old": old}


def amount(page: Page, account):
    return page.locator(f'input[data-field="amount"][data-account-id="{account.id}"]')


def tabbar_h(page: Page) -> float:
    """--tabbar-h as the page computes it: 0 before the shell's tab bar lands,
    its height after (and 0 while a field has focus)."""
    return page.evaluate(
        """() => {
        const probe = document.createElement('div');
        probe.style.cssText = 'position:absolute;height:var(--tabbar-h)';
        document.body.append(probe);
        const h = probe.getBoundingClientRect().height;
        probe.remove();
        return h;
    }"""
    )


def box(page: Page, selector: str) -> dict:
    return page.evaluate(
        "(s) => { const r = document.querySelector(s).getBoundingClientRect();"
        " return {top: r.top, bottom: r.bottom, left: r.left, right: r.right,"
        " width: r.width, height: r.height}; }",
        selector,
    )


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_the_page_fits(open_page, with_retired, width):
    page = open_page(ACCOUNTS, phone=width)
    assert_fits_phone(page)
    page.locator("#show-retired").check()
    expect(page.locator(".retired-row").first).to_be_visible()
    assert_fits_phone(page)


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_the_page_fits_with_staged_edits(open_page, seeded, width):
    page = open_page(ACCOUNTS, phone=width)
    amount(page, seeded["checking"]).fill("123456.78")
    page.locator(
        f'input[data-field="basis"][data-account-id="{seeded["tax"].id}"]'
    ).fill("90000")
    page.locator("main h1").click()  # blur, so the field formats itself
    expect(page.locator("#dirty-status")).to_have_text("2 unsaved changes")
    expect(page.locator("#net-change")).to_be_visible()
    assert_fits_phone(page)

    # Two lines: the count and the net worth share the first, the buttons
    # share the second, equally.
    status, net = box(page, "#dirty-status"), box(page, "#net-worth")
    assert abs(status["top"] - net["top"]) < 4
    discard, save = box(page, "#discard-button"), box(page, "#save-button")
    assert abs(discard["top"] - save["top"]) < 1
    assert abs(discard["width"] - save["width"]) < 1
    assert discard["bottom"] > net["bottom"]


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_the_page_fits_for_a_viewer(open_page, seeded, db_connection, width):
    db_connection.execute(
        "UPDATE workspace_members SET role = 'viewer' WHERE workspace_id = %s", (WS,)
    )
    db_connection.commit()
    page = open_page(ACCOUNTS, phone=width)
    expect(page.locator(".account-row").first).to_be_visible()
    assert_fits_phone(page)


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_the_empty_page_fits(open_page, db_connection, width):
    page = open_page(ACCOUNTS, phone=width)
    expect(page.locator(".empty-card")).to_be_visible()
    assert_fits_phone(page)


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_card_heads_stay_on_one_line(open_page, seeded, width):
    page = open_page(ACCOUNTS, phone=width)
    for kind in ("asset", "liability"):
        head = f".section-{kind} .card-head"
        title, add, total = (
            box(page, f"{head} h2"),
            box(page, f"{head} .btn"),
            box(page, f"{head} .total"),
        )
        # One line: everything shares a band, left to right.
        assert title["bottom"] > add["top"] and add["bottom"] > title["top"]
        assert total["bottom"] > add["top"] and add["bottom"] > total["top"]
        assert title["right"] <= add["left"] <= add["right"] <= total["left"]
        # The title is not cut short.
        assert page.evaluate(
            "(s) => { const h = document.querySelector(s); return h.scrollWidth <= h.clientWidth; }",
            f"{head} h2",
        )
        expect(page.locator(f"{head} .btn")).to_have_accessible_name("+ Add")


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_the_save_bar_sits_above_the_tab_bar_and_clears_the_last_row(
    open_page, seeded, width
):
    page = open_page(ACCOUNTS, phone=width)
    inner = page.evaluate("window.innerHeight")
    # At the top of the page the bar is pinned to the bottom of the screen,
    # just above the tab bar.
    assert box(page, ".save-bar-wrap")["bottom"] == pytest.approx(
        inner - tabbar_h(page), abs=1
    )
    assert box(page, ".save-bar")["bottom"] <= inner - tabbar_h(page)

    # Scrolled to the end, the last row is clear of it.
    page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    page.wait_for_function(
        "window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 1"
    )
    last_row = page.locator(".account-row:not(.retired-row)").last
    row = last_row.bounding_box()
    assert row is not None
    bar = box(page, ".save-bar")
    assert row["y"] + row["height"] <= bar["top"]
    assert bar["bottom"] <= inner - tabbar_h(page) + 1


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_rows_are_thumb_sized(open_page, seeded, width):
    page = open_page(ACCOUNTS, phone=width)
    for selector in (".account-name", "input[data-field]"):
        for el in page.locator(selector).all():
            b = el.bounding_box()
            assert b is not None and b["height"] >= 43.5 and b["width"] >= 43.5, (
                selector
            )
    for el in page.locator("input[data-field]").all():
        assert el.get_attribute("inputmode") == "decimal"
        assert el.evaluate("e => parseFloat(getComputedStyle(e).fontSize)") >= 16
    # A computed row: the basis field sits under the name and value, on the
    # value's side, inside the card.
    tax = f'.account-row[data-account-id="{seeded["tax"].id}"]'
    basis, value, card = (
        box(page, f"{tax} .basis-input"),
        box(page, f"{tax} .computed-value"),
        box(page, ".section-liability"),
    )
    assert basis["top"] >= value["bottom"]
    assert basis["right"] <= card["right"]


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_staging_and_saving_work_on_a_phone(open_page, seeded, width):
    page = open_page(ACCOUNTS, phone=width)
    checking = amount(page, seeded["checking"])
    checking.tap()
    checking.fill("2000")
    expect(page.locator("#dirty-status")).to_have_text("1 unsaved change")
    page.locator("#discard-button").tap()
    expect(page.locator("#dirty-status")).to_have_text("No unsaved changes")
    expect(checking).to_have_value("1,000.00")

    checking.fill("2500")
    with page.expect_navigation():
        page.locator("#save-button").tap()
    expect(page.locator("#snapshot-saved")).to_have_attribute("data-today", "1")
    expect(page.locator("#dirty-status")).to_have_text("No unsaved changes")
    expect(amount(page, seeded["checking"])).to_have_value("2,500.00")


DRAWERS = {
    "new_asset": lambda s: f"{ACCOUNTS}/new?type=asset",
    "new_liability": lambda s: f"{ACCOUNTS}/new?type=liability",
    "edit_plain": lambda s: f"{ACCOUNTS}/{s['checking'].id}/edit",
    "edit_computed": lambda s: f"{ACCOUNTS}/{s['tax'].id}/edit",
    # Schwab feeds the tax account, so it cannot be retired.
    "retire_blocker": lambda s: f"{ACCOUNTS}/{s['schwab'].id}/edit",
    "retired": lambda s: f"{ACCOUNTS}/{s['old'].id}/edit",
}


@pytest.mark.parametrize("width", PHONE_WIDTHS)
@pytest.mark.parametrize("state", DRAWERS)
def test_every_drawer_state_fits(open_page, with_retired, width, state):
    page = open_page(DRAWERS[state](with_retired), phone=width)
    expect(page.locator(".drawer")).to_be_visible()
    if state == "edit_plain":
        # Checking has a non-zero amount: the retire warning.
        expect(page.locator(".drawer-retire")).to_contain_text("Retire anyway")
    if state == "retire_blocker":
        expect(page.locator(".drawer-retire button")).to_have_count(0)
    # Everything in the drawer body, scrolled through, fits.
    page.locator(".drawer-body").evaluate("e => e.scrollTo(0, e.scrollHeight)")
    assert_fits_phone(page)


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_the_computed_drawer_wraps_rather_than_clipping(open_page, seeded, width):
    page = open_page(f"{ACCOUNTS}/{seeded['tax'].id}/edit", phone=width)
    # The rate and cost basis stay side by side.
    rate, basis = (
        box(page, "input[name=rate_percent]"),
        box(page, "input[name=cost_basis]"),
    )
    assert abs(rate["top"] - basis["top"]) < 1 and rate["right"] < basis["left"]
    # Input chips wrap onto several lines, each a 44px label.
    pills = page.locator("#formula-fields .pill").all()
    tops = {round(p.bounding_box()["y"]) for p in pills}  # type: ignore[index]
    assert len(tops) > 1
    for pill in pills:
        b = pill.bounding_box()
        assert b is not None and b["height"] >= 43.5
    # A long computed-value line wraps inside its box.
    page.locator("input[name=rate_percent]").fill("12.3456")
    page.locator("input[name=cost_basis]").fill("1234567.89")
    page.locator(".formula-preview").scroll_into_view_if_needed()
    assert page.locator(".formula-preview").evaluate(
        """e => { const r = e.getBoundingClientRect();
        return e.scrollWidth <= e.clientWidth
            && [...e.children].every(c => c.getBoundingClientRect().right <= r.right + 0.5); }"""
    )
    assert_fits_phone(page)
