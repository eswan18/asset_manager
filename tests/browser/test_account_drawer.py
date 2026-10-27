"""The account drawer's script: the live computed-value line, the computed
toggle, the type switch, and the shared drawer behaviour (focus, an inert
page behind, scroll lock, Escape)."""

import pytest
from playwright.sync_api import expect

from tests.web_support import PAGES

pytestmark = [pytest.mark.browser, pytest.mark.db]

ACCOUNTS = f"{PAGES}/accounts"
STORAGE_KEY = "sensibility:staged-edits"


def test_drawer_takes_focus_and_the_page_behind_is_inert(open_page, seeded):
    tax = seeded["tax"]
    page = open_page(f"{ACCOUNTS}/{tax.id}/edit")
    expect(page.locator("#account-form [name=name]")).to_be_focused()
    assert page.evaluate("getComputedStyle(document.body).overflow") == "hidden"

    # The page behind cannot take focus, by script or by Tab.
    behind = page.get_by_label("Amount for Checking")
    behind.evaluate("el => el.focus()")
    expect(behind).not_to_be_focused()
    for _ in range(30):
        page.keyboard.press("Tab")
        assert page.evaluate(
            "!!document.activeElement.closest('.drawer') || document.activeElement === document.body"
        )

    # The scrim lies over the save bar.
    box = page.locator(".save-bar-wrap").bounding_box()
    assert box is not None
    top = page.evaluate(
        "([x, y]) => document.elementFromPoint(x, y).className",
        [box["x"] + 20, box["y"] + box["height"] / 2],
    )
    assert "scrim" in top


def test_escape_closes_to_the_accounts_page(open_page, seeded):
    page = open_page(f"{ACCOUNTS}/{seeded['checking'].id}/edit")
    with page.expect_navigation():
        page.keyboard.press("Escape")
    assert page.url.endswith(ACCOUNTS)
    expect(page.locator(".drawer")).to_have_count(0)


def test_staged_edits_stay_under_the_drawer(open_page, seeded):
    page = open_page(ACCOUNTS)
    page.get_by_label("Amount for Checking").fill("999")
    page.get_by_role("link", name="Cap gains tax").click()
    page.wait_for_url(f"**{ACCOUNTS}/{seeded['tax'].id}/edit")
    expect(page.get_by_label("Amount for Checking")).to_have_value("999")
    expect(page.locator("#dirty-status")).to_have_text("1 unsaved change")
    assert page.evaluate(f"sessionStorage.getItem('{STORAGE_KEY}')") == (
        f'{{"amount:{seeded["checking"].id}":"999"}}'
    )


def test_computed_line_recomputes_as_you_type(open_page, seeded):
    page = open_page(f"{ACCOUNTS}/{seeded['tax'].id}/edit")
    form = page.locator("#account-form")
    text, value = page.locator("#formula-text"), page.locator("#formula-value")

    def line(t: str, v: str) -> None:
        expect(text).to_have_text(t)
        expect(value).to_have_text(v)

    line("15% × ($179,265 − $82,387)", "$14,531.74")  # from the server
    form.locator("[name=rate_percent]").fill("20")
    line("20% × ($179,265 − $82,387)", "$19,375.65")
    form.locator("[name=cost_basis]").fill("$1,000.005")  # basis rounds to cents first
    expect(value).to_have_text("$35,653.00")
    form.locator("[name=cost_basis]").fill("")
    line("20% × ($179,265 − $0)", "$35,853.00")
    form.get_by_label("Checking").check()  # a second input sums
    line("20% × ($180,265 − $0)", "$36,053.00")
    form.locator("[name=cost_basis]").fill("(100)")
    expect(text).to_have_text("20% × ($180,265 − -$100)")
    form.locator("[name=rate_percent]").fill("abc")
    line("rate × (sum of inputs − cost basis)", "—")
    form.locator("[name=rate_percent]").fill("15")
    form.get_by_label("Checking").uncheck()
    form.get_by_label("Schwab").uncheck()
    expect(value).to_have_text("—")


def test_computed_toggle_and_type_switch(open_page, seeded):
    page = open_page(f"{ACCOUNTS}/new?type=asset")
    fields = page.locator("#formula-fields")
    expect(fields).to_be_hidden()
    page.locator("#computed").check()
    expect(fields).to_be_visible()
    page.locator("#computed").uncheck()
    expect(fields).to_be_hidden()

    drawer = page.locator(".drawer")
    head = page.locator(".drawer-head")
    before = head.evaluate("el => getComputedStyle(el).borderBottomColor")
    expect(drawer).to_contain_class("section-asset")
    page.locator('#type-choice input[value="liability"]').check()
    expect(page.locator("#drawer-title")).to_have_text("New liability")
    expect(drawer).to_contain_class("section-liability")
    expect(drawer).not_to_contain_class("section-asset")
    after = head.evaluate("el => getComputedStyle(el).borderBottomColor")
    assert before != after


def test_new_account_from_the_drawer(open_page, db_connection):
    """No accounts yet: the drawer still opens, saves, and closes."""
    page = open_page(f"{PAGES}/accounts/new?type=asset")
    page.locator("#account-form [name=name]").fill("Brokerage")
    with page.expect_navigation():
        page.get_by_role("button", name="Save").click()
    expect(page.get_by_role("link", name="Brokerage")).to_be_visible()
