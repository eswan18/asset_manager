"""The Accounts page's script: staged edits, the save bar, computed accounts,
Discard, sessionStorage across reloads, and the date a save gets."""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from playwright.sync_api import Page, expect

from tests.browser.conftest import SAVED_ON
from tests.web_support import PAGES, TZ

pytestmark = [pytest.mark.browser, pytest.mark.db]

ACCOUNTS = f"{PAGES}/accounts"
STORAGE_KEY = "asset-manager:staged-edits"


def amount(page: Page, account) -> object:
    return page.locator(f'input[data-field="amount"][data-account-id="{account.id}"]')


def staged(page: Page) -> dict:
    return page.evaluate(
        f"JSON.parse(sessionStorage.getItem('{STORAGE_KEY}') || '{{}}')"
    )


def test_edit_is_staged_counted_and_survives_a_reload(open_page, seeded):
    page = open_page(ACCOUNTS)
    checking = amount(page, seeded["checking"])
    was = page.locator(f'.was[data-account-id="{seeded["checking"].id}"]')
    expect(page.locator("#dirty-status")).to_have_text("No unsaved changes")
    expect(page.locator("#net-worth")).to_have_text("$165,233.26")
    expect(was).to_be_hidden()

    checking.fill("1500")
    expect(checking).to_contain_class("edited")
    expect(page.locator("#dirty-status")).to_have_text("1 unsaved change")
    expect(page.locator("#net-worth")).to_have_text("$165,733.26")
    expect(page.locator("#net-change")).to_have_text(" (+$500.00)")
    expect(was).to_be_visible()
    expect(was).to_have_text("was $1,000.00")
    expect(page.locator(".section-asset .card-head .total")).to_have_text("$180,765.00")
    assert staged(page) == {f"amount:{seeded['checking'].id}": "1500"}

    # Leaving the field formats it; it is still the same edit.
    checking.blur()
    expect(checking).to_have_value("1,500.00")
    expect(page.locator("#dirty-status")).to_have_text("1 unsaved change")

    # A second edit counts separately; undoing it by hand uncounts it.
    card = amount(page, seeded["card"])
    card.fill("750")
    expect(page.locator("#dirty-status")).to_have_text("2 unsaved changes")
    expect(page.locator("#net-worth")).to_have_text("$165,483.26")
    card.fill("500.00")
    expect(page.locator("#dirty-status")).to_have_text("1 unsaved change")

    # Storage holds what each dirty field shows now: the formatted value.
    assert staged(page) == {f"amount:{seeded['checking'].id}": "1,500.00"}
    page.reload()
    checking = amount(page, seeded["checking"])
    expect(checking).to_have_value("1,500.00")
    expect(checking).to_contain_class("edited")
    expect(page.locator("#dirty-status")).to_have_text("1 unsaved change")
    expect(page.locator("#net-worth")).to_have_text("$165,733.26")


def test_discard_restores_the_page_and_forgets_the_edits(open_page, seeded):
    page = open_page(ACCOUNTS)
    checking = amount(page, seeded["checking"])
    checking.fill("1500")
    page.locator(
        f'input[data-field="basis"][data-account-id="{seeded["tax"].id}"]'
    ).fill("0")
    expect(page.locator("#dirty-status")).to_have_text("2 unsaved changes")

    page.get_by_role("button", name="Discard").click()
    expect(checking).to_have_value("1,000.00")
    expect(checking).not_to_contain_class("edited")
    expect(page.locator("#dirty-status")).to_have_text("No unsaved changes")
    expect(page.locator("#net-worth")).to_have_text("$165,233.26")
    expect(page.locator("#net-change")).to_be_hidden()
    expect(
        page.locator(f'.computed-amount[data-account-id="{seeded["tax"].id}"]')
    ).to_have_text("$14,531.74")
    assert staged(page) == {}

    page.reload()
    expect(amount(page, seeded["checking"])).to_have_value("1,000.00")
    expect(page.locator("#dirty-status")).to_have_text("No unsaved changes")


def test_computed_account_follows_its_input_and_basis(open_page, seeded):
    page = open_page(ACCOUNTS)
    tax_id = seeded["tax"].id
    tax = page.locator(f'.computed-amount[data-account-id="{tax_id}"]')
    tax_was = page.locator(f'.was[data-account-id="{tax_id}"]')
    expect(tax).to_have_text("$14,531.74")
    expect(tax_was).to_be_hidden()

    amount(page, seeded["schwab"]).fill("200000")
    # 0.15 × (200,000 − 82,386.74) = 17,641.989
    expect(tax).to_have_text("$17,641.99")
    expect(tax).to_contain_class("edited")
    expect(tax_was).to_be_visible()
    expect(page.locator(".section-liability .card-head .total")).to_have_text(
        "$18,141.99"
    )

    basis = page.locator(f'input[data-field="basis"][data-account-id="{tax_id}"]')
    basis.fill("100,000")
    expect(tax).to_have_text("$15,000.00")
    basis.fill("(1,000)")  # parentheses are negative
    expect(tax).to_have_text("$30,150.00")
    basis.fill("abc")
    expect(tax).to_have_text("—")
    expect(basis).to_contain_class("invalid")
    basis.fill("")  # blank basis is zero
    expect(tax).to_have_text("$30,000.00")
    # Net worth: 1,000 + 200,000 − 500 − 30,000
    expect(page.locator("#net-worth")).to_have_text("$170,500.00")


def test_save_dates_the_snapshot_in_the_browser_zone(open_page, seeded, db_connection):
    # A zone whose today differs from the server default's right now.
    now = datetime.now(ZoneInfo("UTC"))
    default_day = now.astimezone(ZoneInfo(TZ)).date()
    zone = next(
        z
        for z in ("Pacific/Kiritimati", "Pacific/Pago_Pago")
        if now.astimezone(ZoneInfo(z)).date() != default_day
    )
    page = open_page(ACCOUNTS, timezone_id=zone)
    cookie = next(c for c in page.context.cookies() if c["name"] == "tz")
    assert cookie["value"] == zone.replace("/", "%2F")

    amount(page, seeded["checking"]).fill("1234.5")
    with page.expect_navigation():
        page.get_by_role("button", name="Save snapshot").click()
    expect(page.locator("#dirty-status")).to_have_text("No unsaved changes")
    expect(amount(page, seeded["checking"])).to_have_value("1,234.50")
    assert staged(page) == {}

    with db_connection.cursor() as cur:
        cur.execute(
            "SELECT date, amount FROM snapshots WHERE account_id = %s ORDER BY date",
            (seeded["checking"].id,),
        )
        rows = cur.fetchall()
    assert rows == [
        (SAVED_ON, Decimal("1000.00")),
        (now.astimezone(ZoneInfo(zone)).date(), Decimal("1234.50")),
    ]


def test_second_save_on_the_same_day_asks_first(open_page, seeded):
    page = open_page(ACCOUNTS)
    amount(page, seeded["checking"]).fill("2000")
    with page.expect_navigation():
        page.get_by_role("button", name="Save snapshot").click()
    amount(page, seeded["checking"]).fill("3000")
    page.get_by_role("button", name="Save snapshot").click()
    expect(page.locator("#dirty-status")).to_have_text(
        "Today's snapshot already exists. Saving again replaces it."
    )
    with page.expect_navigation():
        page.get_by_role("button", name="Overwrite today's snapshot").click()
    expect(amount(page, seeded["checking"])).to_have_value("3,000.00")


def test_blank_amount_blocks_the_save(open_page, seeded):
    page = open_page(ACCOUNTS)
    checking = amount(page, seeded["checking"])
    checking.fill("")
    page.get_by_role("button", name="Save snapshot").click()
    expect(page.locator("#save-error")).to_have_text(
        "Every account needs an amount before saving."
    )
    expect(checking).to_contain_class("invalid")
    expect(checking).to_be_focused()
