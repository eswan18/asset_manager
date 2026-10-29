"""The Accounts page and account drawer (frontend/src/routes/accounts.tsx,
account-drawer.tsx), in a real browser against the built app: staged edits,
"was $X", the save bar's count and live net worth, computed accounts
recomputing, Discard, sessionStorage across reloads, a save dated in the
browser's zone, the drawer in every state, and every state fitting a phone."""

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from playwright.sync_api import Page, expect

from sensibility.accounts import create_account, retire_account
from sensibility.models import RecordType
from tests.browser.conftest import SAVED_ON
from tests.browser.mobile import PHONE_WIDTHS, TARGET, assert_fits_phone
from tests.support import WS
from tests.web_support import TZ

pytestmark = [pytest.mark.browser, pytest.mark.db]

ACCOUNTS = f"/workspaces/{WS}/accounts"
STORAGE_KEY = "sensibility:staged-edits"


@pytest.fixture
def with_retired(db_connection, seeded):
    """seeded, plus a retired account, so "Show retired" appears."""
    old = create_account(db_connection, WS, "Old savings", RecordType.ASSET)
    assert old.id is not None
    retire_account(db_connection, WS, old.id, date(2026, 9, 1))
    db_connection.commit()
    return {**seeded, "old": old}


def amount(page: Page, account):
    # By attribute, not role: under a drawer the page is hidden from the
    # accessibility tree.
    return page.locator(f'input[aria-label="Amount for {account.name}"]')


def basis(page: Page, account):
    return page.locator(f'input[aria-label="Cost basis for {account.name}"]')


def computed_amount(page: Page, account):
    return page.locator(f'[data-account-id="{account.id}"] [data-computed-amount]')


def was(page: Page, account):
    return page.locator(f'[data-account-id="{account.id}"] [data-was]')


def status(page: Page):
    return page.locator("[data-status]")


def net_worth(page: Page):
    return page.locator("[data-net-worth]")


def net_change(page: Page):
    return page.locator("[data-net-change]")


def card_total(page: Page, kind: str):
    return page.locator(f"[data-section={kind}] [data-slot=card-total]")


def staged(page: Page) -> dict:
    return page.evaluate(
        f"JSON.parse(sessionStorage.getItem('{STORAGE_KEY}') || '{{}}')"
    )


def settled(page: Page) -> None:
    page.wait_for_function(
        "document.getAnimations().every(a => a.playState === 'finished')"
    )


def box(page: Page, selector: str) -> dict:
    return page.evaluate(
        "(s) => { const r = document.querySelector(s).getBoundingClientRect();"
        " return {top: r.top, bottom: r.bottom, left: r.left, right: r.right,"
        " width: r.width, height: r.height}; }",
        selector,
    )


def tabbar_h(page: Page) -> float:
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


# --- the page ------------------------------------------------------------------


def test_edit_is_staged_counted_and_survives_a_reload(open_page, seeded):
    page = open_page(ACCOUNTS)
    checking = amount(page, seeded["checking"])
    expect(status(page)).to_have_text("No unsaved changes")
    expect(net_worth(page)).to_have_text("$165,233.26")
    expect(was(page, seeded["checking"])).to_have_count(0)

    checking.fill("1500")
    expect(checking).to_have_attribute("data-edited", "true")
    expect(status(page)).to_have_text("1 unsaved change")
    expect(net_worth(page)).to_have_text("$165,733.26")
    expect(net_change(page)).to_have_text(" (+$500.00)")
    expect(was(page, seeded["checking"])).to_have_text("was $1,000.00")
    expect(card_total(page, "asset")).to_have_text("$180,765.00")
    assert staged(page) == {f"amount:{seeded['checking'].id}": "1500"}

    # Leaving the field formats it; it is still the same edit.
    checking.blur()
    expect(checking).to_have_value("1,500.00")
    expect(status(page)).to_have_text("1 unsaved change")

    # A second edit counts separately; undoing it by hand uncounts it.
    card = amount(page, seeded["card"])
    card.fill("750")
    expect(status(page)).to_have_text("2 unsaved changes")
    expect(net_worth(page)).to_have_text("$165,483.26")
    card.fill("500.00")
    expect(status(page)).to_have_text("1 unsaved change")

    # Storage holds what each dirty field shows now: the formatted value.
    assert staged(page) == {f"amount:{seeded['checking'].id}": "1,500.00"}
    page.reload()
    checking = amount(page, seeded["checking"])
    expect(checking).to_have_value("1,500.00")
    expect(checking).to_have_attribute("data-edited", "true")
    expect(status(page)).to_have_text("1 unsaved change")
    expect(net_worth(page)).to_have_text("$165,733.26")


def test_discard_restores_the_page_and_forgets_the_edits(open_page, seeded):
    page = open_page(ACCOUNTS)
    checking = amount(page, seeded["checking"])
    checking.fill("1500")
    basis(page, seeded["tax"]).fill("0")
    expect(status(page)).to_have_text("2 unsaved changes")

    page.get_by_role("button", name="Discard").click()
    expect(checking).to_have_value("1,000.00")
    expect(checking).not_to_have_attribute("data-edited", "true")
    expect(status(page)).to_have_text("No unsaved changes")
    expect(net_worth(page)).to_have_text("$165,233.26")
    expect(net_change(page)).to_have_count(0)
    expect(computed_amount(page, seeded["tax"])).to_have_text("$14,531.74")
    assert staged(page) == {}

    page.reload()
    expect(amount(page, seeded["checking"])).to_have_value("1,000.00")
    expect(status(page)).to_have_text("No unsaved changes")


def test_computed_account_follows_its_input_and_basis(open_page, seeded):
    page = open_page(ACCOUNTS)
    tax = computed_amount(page, seeded["tax"])
    expect(tax).to_have_text("$14,531.74")
    expect(was(page, seeded["tax"])).to_have_count(0)

    amount(page, seeded["schwab"]).fill("200000")
    # 0.15 × (200,000 − 82,386.74) = 17,641.989
    expect(tax).to_have_text("$17,641.99")
    expect(tax).to_have_attribute("data-edited", "true")
    expect(was(page, seeded["tax"])).to_have_text("was $14,531.74")
    expect(card_total(page, "liability")).to_have_text("$18,141.99")

    field = basis(page, seeded["tax"])
    field.fill("100,000")
    expect(tax).to_have_text("$15,000.00")
    field.fill("(1,000)")  # parentheses are negative
    expect(tax).to_have_text("$30,150.00")
    field.fill("abc")
    expect(tax).to_have_text("—")
    expect(field).to_have_attribute("aria-invalid", "true")
    field.fill("")  # blank basis is zero
    expect(tax).to_have_text("$30,000.00")
    # Net worth: 1,000 + 200,000 − 500 − 30,000
    expect(net_worth(page)).to_have_text("$170,500.00")


def test_show_retired(open_page, with_retired):
    page = open_page(ACCOUNTS)
    old = page.get_by_role("link", name="Old savings")
    expect(old).to_have_count(0)
    page.get_by_label("Show retired (1)").check()
    expect(old).to_be_visible()
    assert "line-through" in old.evaluate("e => getComputedStyle(e).textDecoration")
    expect(
        page.locator(f'[data-account-id="{with_retired["old"].id}"]')
    ).to_contain_text("Retired Sep 1, 2026")


def test_save_dates_the_snapshot_in_the_browser_zone(open_page, seeded, db_connection):
    # A zone whose today differs from the server default's right now. The
    # app sends it as X-Timezone with the save.
    now = datetime.now(ZoneInfo("UTC"))
    default_day = now.astimezone(ZoneInfo(TZ)).date()
    zone = next(
        z
        for z in ("Pacific/Kiritimati", "Pacific/Pago_Pago")
        if now.astimezone(ZoneInfo(z)).date() != default_day
    )
    page = open_page(ACCOUNTS, timezone_id=zone)
    today = now.astimezone(ZoneInfo(zone)).date()
    expect(page.get_by_text("Saving writes today's snapshot")).to_contain_text(
        f"{today:%b} {today.day}, {today.year}"
    )

    amount(page, seeded["checking"]).fill("1234.5")
    page.get_by_role("button", name="Save snapshot").click()
    expect(page.get_by_role("status")).to_contain_text(
        "Saved today's snapshot: 4 accounts, net worth $165,468."
    )
    expect(status(page)).to_have_text("No unsaved changes")
    expect(amount(page, seeded["checking"])).to_have_value("1,234.50")
    expect(
        page.get_by_text("Last saved today; saving again replaces it.")
    ).to_be_visible()
    assert staged(page) == {}

    with db_connection.cursor() as cur:
        cur.execute(
            "SELECT date, amount FROM snapshots WHERE account_id = %s ORDER BY date",
            (seeded["checking"].id,),
        )
        rows = cur.fetchall()
    assert rows == [(SAVED_ON, Decimal("1000.00")), (today, Decimal("1234.50"))]


def test_second_save_on_the_same_day_asks_first(open_page, seeded):
    page = open_page(ACCOUNTS)
    amount(page, seeded["checking"]).fill("2000")
    page.get_by_role("button", name="Save snapshot").click()
    expect(status(page)).to_have_text("No unsaved changes")
    amount(page, seeded["checking"]).fill("3000")
    page.get_by_role("button", name="Save snapshot").click()
    expect(status(page)).to_have_text(
        "Today's snapshot already exists. Saving again replaces it."
    )
    page.get_by_role("button", name="Overwrite today's snapshot").click()
    expect(status(page)).to_have_text("No unsaved changes")
    expect(amount(page, seeded["checking"])).to_have_value("3,000.00")


def test_blank_amount_blocks_the_save(open_page, seeded):
    page = open_page(ACCOUNTS)
    checking = amount(page, seeded["checking"])
    checking.fill("")
    page.get_by_role("button", name="Save snapshot").click()
    expect(page.get_by_role("alert")).to_have_text(
        "Every account needs an amount before saving."
    )
    expect(checking).to_have_attribute("aria-invalid", "true")
    expect(checking).to_be_focused()


def test_a_viewer_gets_no_add(open_page, seeded, db_connection):
    db_connection.execute(
        "UPDATE workspace_members SET role = 'viewer' WHERE workspace_id = %s", (WS,)
    )
    db_connection.commit()
    page = open_page(ACCOUNTS)
    expect(amount(page, seeded["checking"])).not_to_be_editable()
    expect(page.get_by_role("link", name="+ Add")).to_have_count(0)
    expect(page.get_by_role("region", name="Save snapshot")).to_have_count(0)


def test_the_empty_page(open_page):
    page = open_page(ACCOUNTS)
    expect(page.get_by_role("heading", name="No accounts yet")).to_be_visible()
    page.get_by_role("link", name="+ Add an account").click()
    expect(page.get_by_role("dialog", name="New asset")).to_be_visible()


# --- the drawer ------------------------------------------------------------------


def test_drawer_takes_focus_and_the_page_behind_is_inert(open_page, seeded):
    page = open_page(f"{ACCOUNTS}/{seeded['tax'].id}/edit")
    dialog = page.get_by_role("dialog", name="Cap gains tax")
    expect(dialog.get_by_label("Name")).to_be_focused()
    assert page.evaluate("getComputedStyle(document.body).overflow") == "hidden"

    # The page behind cannot take focus, by script or by Tab.
    behind = amount(page, seeded["checking"])
    behind.evaluate("el => el.focus()")
    expect(behind).not_to_be_focused()
    for _ in range(30):
        page.keyboard.press("Tab")
        assert page.evaluate(
            "!!document.activeElement.closest('[role=dialog]')"
            " || document.activeElement === document.body"
        )

    # The scrim lies over the save bar.
    bar = page.locator("[data-save-bar-wrap]").bounding_box()
    assert bar is not None
    top = page.evaluate(
        "([x, y]) => document.elementFromPoint(x, y).dataset.slot",
        [bar["x"] + 20, bar["y"] + bar["height"] / 2],
    )
    assert top == "sheet-scrim"


def test_escape_closes_to_the_accounts_page(open_page, seeded):
    page = open_page(f"{ACCOUNTS}/{seeded['checking'].id}/edit")
    expect(page.get_by_role("dialog", name="Checking")).to_be_visible()
    page.keyboard.press("Escape")
    page.wait_for_url(f"**{ACCOUNTS}")
    expect(page.get_by_role("dialog")).to_have_count(0)


def test_staged_edits_stay_under_the_drawer(open_page, seeded):
    page = open_page(ACCOUNTS)
    amount(page, seeded["checking"]).fill("999")
    page.get_by_role("link", name="Cap gains tax").click()
    page.wait_for_url(f"**{ACCOUNTS}/{seeded['tax'].id}/edit")
    expect(page.get_by_role("dialog", name="Cap gains tax")).to_be_visible()
    # The page stays mounted, so the field left for the link tidied itself.
    expect(amount(page, seeded["checking"])).to_have_value("999.00")
    expect(status(page)).to_have_text("1 unsaved change")
    assert page.evaluate(f"sessionStorage.getItem('{STORAGE_KEY}')") == (
        f'{{"amount:{seeded["checking"].id}":"999.00"}}'
    )
    # And still there after the drawer saves.
    page.get_by_role("dialog").get_by_role("button", name="Save").click()
    page.wait_for_url(f"**{ACCOUNTS}")
    expect(page.get_by_role("status")).to_contain_text("Saved Cap gains tax")
    expect(amount(page, seeded["checking"])).to_have_value("999.00")
    expect(status(page)).to_have_text("1 unsaved change")


def test_computed_line_recomputes_as_you_type(open_page, seeded):
    page = open_page(f"{ACCOUNTS}/{seeded['tax'].id}/edit")
    form = page.get_by_role("dialog")
    line = form.locator("[data-formula-preview]")
    text, value = line.locator("span"), line.locator("strong")

    def show(t: str, v: str) -> None:
        expect(text).to_have_text(t)
        expect(value).to_have_text(v)

    show("15% × ($179,265 − $82,387)", "$14,531.74")
    form.get_by_label("Rate (%)").fill("20")
    show("20% × ($179,265 − $82,387)", "$19,375.65")
    form.get_by_label("Cost basis ($)").fill("$1,000.005")  # rounds to cents first
    expect(value).to_have_text("$35,653.00")
    form.get_by_label("Cost basis ($)").fill("")
    show("20% × ($179,265 − $0)", "$35,853.00")
    form.get_by_label("Checking").check()  # a second input sums
    show("20% × ($180,265 − $0)", "$36,053.00")
    form.get_by_label("Cost basis ($)").fill("(100)")
    expect(text).to_have_text("20% × ($180,265 − -$100)")
    form.get_by_label("Rate (%)").fill("abc")
    show("rate × (sum of inputs − cost basis)", "—")
    form.get_by_label("Rate (%)").fill("15")
    form.get_by_label("Checking").uncheck()
    form.get_by_label("Schwab").uncheck()
    expect(value).to_have_text("—")


def test_computed_toggle_and_type_switch(open_page, seeded):
    page = open_page(f"{ACCOUNTS}/new?type=asset")
    dialog = page.get_by_role("dialog", name="New asset")
    computed = dialog.get_by_label("Computed from other accounts")
    expect(dialog.get_by_label("Rate (%)")).to_have_count(0)
    computed.check()
    expect(dialog.get_by_label("Rate (%)")).to_be_visible()
    computed.uncheck()
    expect(dialog.get_by_label("Rate (%)")).to_have_count(0)

    head = page.locator("[data-slot=sheet-head]")
    before = head.evaluate("el => getComputedStyle(el).borderBottomColor")
    dialog.get_by_role("radio", name="Liability").check()
    expect(page.get_by_role("dialog", name="New liability")).to_be_visible()
    after = head.evaluate("el => getComputedStyle(el).borderBottomColor")
    assert before != after


def test_new_account_from_the_drawer(open_page, db_connection):
    """No accounts yet: the drawer still opens, saves, and closes."""
    page = open_page(f"{ACCOUNTS}/new?type=asset")
    page.get_by_role("dialog").get_by_label("Name").fill("Brokerage")
    page.get_by_role("dialog").get_by_role("button", name="Save").click()
    page.wait_for_url(f"**{ACCOUNTS}")
    expect(page.get_by_role("status")).to_contain_text("Added Brokerage to assets.")
    expect(page.get_by_role("link", name="Brokerage")).to_be_visible()
    expect(page.get_by_label("Amount for Brokerage")).to_have_value("")


def test_a_refusal_stays_in_the_drawer(open_page, seeded):
    page = open_page(f"{ACCOUNTS}/new?type=asset")
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Name").fill("Checking")
    dialog.get_by_role("button", name="Save").click()
    expect(dialog.get_by_role("alert")).to_contain_text("already exists")
    expect(dialog.get_by_label("Name")).to_have_value("Checking")
    assert page.url.endswith("/accounts/new?type=asset")


def test_retire_and_unretire(open_page, seeded):
    page = open_page(f"{ACCOUNTS}/{seeded['checking'].id}/edit")
    retire = page.get_by_role("dialog").get_by_role("region", name="Retire")
    expect(retire).to_contain_text("Last saved at $1,000.00 on September 27, 2026.")
    retire.get_by_role("button", name="Retire anyway").click()
    page.wait_for_url(f"**{ACCOUNTS}")
    expect(page.get_by_role("status")).to_contain_text("Retired Checking")
    expect(page.get_by_role("link", name="Checking")).to_have_count(0)
    page.get_by_label("Show retired (1)").check()
    page.get_by_role("link", name="Checking").click()
    retire = page.get_by_role("dialog").get_by_role("region", name="Retire")
    expect(retire).to_contain_text("Unretiring brings it back with a blank amount.")
    retire.get_by_role("button", name="Unretire").click()
    page.wait_for_url(f"**{ACCOUNTS}")
    expect(page.get_by_role("status").last).to_contain_text("Unretired Checking")
    expect(amount(page, seeded["checking"])).to_be_visible()


# --- phones ----------------------------------------------------------------------


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_the_page_fits(open_page, with_retired, width):
    page = open_page(ACCOUNTS, phone=width)
    expect(amount(page, with_retired["checking"])).to_be_visible()
    assert_fits_phone(page)
    page.get_by_label("Show retired (1)").check()
    expect(page.get_by_role("link", name="Old savings")).to_be_visible()
    assert_fits_phone(page)


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_the_page_fits_with_staged_edits(open_page, seeded, width):
    page = open_page(ACCOUNTS, phone=width)
    amount(page, seeded["checking"]).fill("123456.78")
    basis(page, seeded["tax"]).fill("90000")
    page.locator("main h1").click()  # blur, so the field formats itself
    expect(status(page)).to_have_text("2 unsaved changes")
    expect(net_change(page)).to_be_visible()
    assert_fits_phone(page)

    # Two lines: the count and the net worth share the first, the buttons
    # share the second, equally.
    first, net = box(page, "[data-status]"), box(page, "[data-net-worth]")
    assert abs(first["top"] - net["top"]) < 4
    bar = page.get_by_role("region", name="Save snapshot")
    discard = bar.get_by_role("button", name="Discard").bounding_box()
    save = bar.get_by_role("button", name="Save snapshot").bounding_box()
    assert discard is not None and save is not None
    assert abs(discard["y"] - save["y"]) < 1
    assert abs(discard["width"] - save["width"]) < 1
    assert discard["y"] + discard["height"] > net["bottom"]


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_the_page_fits_for_a_viewer(open_page, seeded, db_connection, width):
    db_connection.execute(
        "UPDATE workspace_members SET role = 'viewer' WHERE workspace_id = %s", (WS,)
    )
    db_connection.commit()
    page = open_page(ACCOUNTS, phone=width)
    expect(amount(page, seeded["checking"])).to_be_visible()
    assert_fits_phone(page)


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_the_empty_page_fits(open_page, db_connection, width):
    page = open_page(ACCOUNTS, phone=width)
    expect(page.get_by_role("heading", name="No accounts yet")).to_be_visible()
    assert_fits_phone(page)


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_card_heads_stay_on_one_line(open_page, seeded, width):
    page = open_page(ACCOUNTS, phone=width)
    expect(amount(page, seeded["checking"])).to_be_visible()
    for kind in ("asset", "liability"):
        head = f"[data-section={kind}] [data-slot=card-head]"
        title, add, total = (
            box(page, f"{head} [data-slot=card-title]"),
            box(page, f"{head} a"),
            box(page, f"{head} [data-slot=card-total]"),
        )
        # One line: everything shares a band, left to right.
        assert title["bottom"] > add["top"] and add["bottom"] > title["top"]
        assert total["bottom"] > add["top"] and add["bottom"] > total["top"]
        assert title["right"] <= add["left"] <= add["right"] <= total["left"]
        assert add["width"] >= TARGET - 0.5 and add["height"] >= TARGET - 0.5
        # The title is not cut short.
        assert page.evaluate(
            "(s) => { const h = document.querySelector(s); return h.scrollWidth <= h.clientWidth; }",
            f"{head} [data-slot=card-title]",
        )
        expect(page.locator(f"{head} a")).to_have_accessible_name("+ Add")


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_the_save_bar_sits_above_the_tab_bar_and_clears_the_last_row(
    open_page, seeded, width
):
    page = open_page(ACCOUNTS, phone=width)
    expect(amount(page, seeded["checking"])).to_be_visible()
    inner = page.evaluate("window.innerHeight")
    # At the top of the page the bar is pinned to the bottom of the screen,
    # just above the tab bar.
    assert box(page, "[data-save-bar-wrap]")["bottom"] == pytest.approx(
        inner - tabbar_h(page), abs=1
    )
    assert box(page, "[role=region][aria-label='Save snapshot']")[
        "bottom"
    ] <= inner - tabbar_h(page)

    # Scrolled to the end, the last row is clear of it.
    page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    page.wait_for_function(
        "window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 1"
    )
    row = page.locator("[data-account-id]").last.bounding_box()
    assert row is not None
    bar = box(page, "[role=region][aria-label='Save snapshot']")
    assert row["y"] + row["height"] <= bar["top"]
    assert bar["bottom"] <= inner - tabbar_h(page) + 1


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_rows_are_thumb_sized(open_page, seeded, width):
    page = open_page(ACCOUNTS, phone=width)
    expect(amount(page, seeded["checking"])).to_be_visible()
    for selector in ("[data-account-id] a", "[data-account-id] input"):
        for el in page.locator(selector).all():
            b = el.bounding_box()
            assert b is not None and b["height"] >= 43.5 and b["width"] >= 43.5, (
                selector
            )
    for el in page.locator("[data-account-id] input").all():
        assert el.get_attribute("inputmode") == "decimal"
        assert el.evaluate("e => parseFloat(getComputedStyle(e).fontSize)") >= 16
    # A computed row: the basis field sits under the name and value, on the
    # value's side, inside the card.
    tax = f'[data-account-id="{seeded["tax"].id}"]'
    field, value, card = (
        box(page, f"{tax} input"),
        box(page, f"{tax} [data-computed-amount]"),
        box(page, "[data-section=liability]"),
    )
    assert field["top"] >= value["bottom"]
    assert field["right"] <= card["right"]


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_staging_and_saving_work_on_a_phone(open_page, seeded, width):
    page = open_page(ACCOUNTS, phone=width)
    checking = amount(page, seeded["checking"])
    checking.tap()
    checking.fill("2000")
    expect(status(page)).to_have_text("1 unsaved change")
    page.get_by_role("button", name="Discard").tap()
    expect(status(page)).to_have_text("No unsaved changes")
    expect(checking).to_have_value("1,000.00")

    checking.fill("2500")
    page.get_by_role("button", name="Save snapshot").tap()
    expect(
        page.get_by_text("Last saved today; saving again replaces it.")
    ).to_be_visible()
    expect(status(page)).to_have_text("No unsaved changes")
    expect(amount(page, seeded["checking"])).to_have_value("2,500.00")


DRAWERS = {
    "new_asset": (lambda s: f"{ACCOUNTS}/new?type=asset", "New asset"),
    "new_liability": (lambda s: f"{ACCOUNTS}/new?type=liability", "New liability"),
    "edit_plain": (lambda s: f"{ACCOUNTS}/{s['checking'].id}/edit", "Checking"),
    "edit_computed": (lambda s: f"{ACCOUNTS}/{s['tax'].id}/edit", "Cap gains tax"),
    # Schwab feeds the tax account, so it cannot be retired.
    "retire_blocker": (lambda s: f"{ACCOUNTS}/{s['schwab'].id}/edit", "Schwab"),
    "retired": (lambda s: f"{ACCOUNTS}/{s['old'].id}/edit", "Old savings"),
    "not_found": (lambda s: f"{ACCOUNTS}/9999/edit", "Account not found"),
}


@pytest.mark.parametrize("width", PHONE_WIDTHS)
@pytest.mark.parametrize("state", DRAWERS)
def test_every_drawer_state_fits(open_page, with_retired, width, state):
    path, title = DRAWERS[state]
    page = open_page(path(with_retired), phone=width)
    dialog = page.get_by_role("dialog", name=title)
    expect(dialog).to_be_visible()
    settled(page)
    if state == "edit_plain":
        # Checking has a non-zero amount: the retire warning.
        expect(dialog.get_by_role("region", name="Retire")).to_contain_text(
            "Retire anyway"
        )
    if state == "retire_blocker":
        expect(
            dialog.get_by_role("region", name="Retire").get_by_role("button")
        ).to_have_count(0)
    if state.startswith("new"):
        dialog.get_by_label("Computed from other accounts").check()
    if state.startswith("edit") or state in ("retire_blocker", "retired"):
        # The history, opened.
        dialog.locator("summary").click()
    # Everything in the drawer body, scrolled through, fits.
    page.locator("[data-slot=sheet-body]").evaluate(
        "e => e.scrollTo(0, e.scrollHeight)"
    )
    assert_fits_phone(page)


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_the_computed_drawer_wraps_rather_than_clipping(open_page, seeded, width):
    page = open_page(f"{ACCOUNTS}/{seeded['tax'].id}/edit", phone=width)
    dialog = page.get_by_role("dialog", name="Cap gains tax")
    expect(dialog).to_be_visible()
    settled(page)
    # The rate and cost basis stay side by side.
    rate = dialog.get_by_label("Rate (%)").bounding_box()
    cost = dialog.get_by_label("Cost basis ($)").bounding_box()
    assert rate is not None and cost is not None
    assert abs(rate["y"] - cost["y"]) < 1 and rate["x"] + rate["width"] < cost["x"]
    # Input chips wrap onto several lines, each a 44px label.
    pills = dialog.get_by_role("group", name="Inputs").locator("label").all()
    tops = {round(p.bounding_box()["y"]) for p in pills}  # type: ignore[index]
    assert len(tops) > 1
    for pill in pills:
        b = pill.bounding_box()
        assert b is not None and b["height"] >= 43.5
    # A long computed-value line wraps inside its box.
    dialog.get_by_label("Rate (%)").fill("12.3456")
    dialog.get_by_label("Cost basis ($)").fill("1234567.89")
    line = dialog.locator("[data-formula-preview]")
    line.scroll_into_view_if_needed()
    assert line.evaluate(
        """e => { const r = e.getBoundingClientRect();
        return e.scrollWidth <= e.clientWidth
            && [...e.children].every(c => c.getBoundingClientRect().right <= r.right + 0.5); }"""
    )
    assert_fits_phone(page)
