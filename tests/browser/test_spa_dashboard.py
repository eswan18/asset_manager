"""The dashboard (frontend/src/routes/dashboard.tsx), in a real browser against the built app: the headline, the range toggle (the URL
changes, the page does not reload, the old numbers stay while the new range
loads), the Recharts chart (lines and columns on a desktop; lines only with
the stacked bars under them on a phone; re-laid across the breakpoint;
re-themed with the color scheme; a tap shows the values), and the
getting-started state for editors and viewers."""

from datetime import date
from decimal import Decimal

import pytest
from playwright.sync_api import Page, expect

from sensibility import repository as repo
from sensibility.accounts import create_account
from sensibility.models import AccountCategory, RecordType
from tests.browser.mobile import PHONE_WIDTHS, TARGET, assert_fits_phone
from tests.support import WS

pytestmark = [pytest.mark.browser, pytest.mark.db]

APP = f"/workspaces/{WS}"
CHART = '[role=img][aria-label^="Assets, net worth and liabilities"]'
WELCOME = "Let's get your first net worth on the board."


@pytest.fixture
def history(db_connection):
    """Four snapshots, the first more than a year before the latest, so
    "All" shows one more than "1Y"."""
    conn = db_connection
    checking = create_account(
        conn, WS, "Checking", RecordType.ASSET, category=AccountCategory.BANK_ACCOUNTS
    )
    schwab = create_account(
        conn,
        WS,
        "Schwab",
        RecordType.ASSET,
        category=AccountCategory.INVESTMENT_ACCOUNTS,
    )
    card = create_account(
        conn,
        WS,
        "Card",
        RecordType.LIABILITY,
        category=AccountCategory.CREDIT_CARDS,
    )
    ids = [checking.id, schwab.id, card.id]
    for day, amounts in {
        date(2025, 9, 1): ["1000", "5000", "200"],
        date(2026, 8, 20): ["2000", "8000", "300"],
        date(2026, 9, 24): ["2500", "9000", "400"],
        date(2026, 10, 24): ["3000.50", "10000", "250.25"],
    }.items():
        repo.upsert_amounts(
            conn, WS, day, {i: Decimal(a) for i, a in zip(ids, amounts)}
        )
    conn.commit()
    return conn


def as_viewer(db_connection) -> None:
    db_connection.execute("UPDATE workspace_members SET role = 'viewer'")
    db_connection.commit()


def wait_for_chart(page: Page) -> None:
    # (A lone snapshot draws no curve, only dots: wait for the line's group.)
    page.locator(f"{CHART} .recharts-line").first.wait_for(state="attached")


def chart(page: Page) -> dict:
    """What is drawn: column blocks, the divider, the lines' plot width
    against the chart's, the chart's height, which layout."""
    return page.evaluate(
        """(sel) => {
        const el = document.querySelector(sel);
        const lines = el.querySelector('.recharts-cartesian-grid');
        return {
            layout: el.dataset.chart,
            columns: el.querySelectorAll('.recharts-bar-rectangle path').length,
            divider: el.querySelector('[data-divider]') !== null,
            height: Math.round(el.getBoundingClientRect().height),
            chartWidth: el.getBoundingClientRect().width,
            plotWidth: lines ? lines.getBoundingClientRect().width : 0,
        };
    }""",
        CHART,
    )


def x_ticks(page: Page):
    """The date labels under the lines."""
    return page.locator(f"{CHART} [data-x-tick]")


def bars_shown(page: Page) -> bool:
    return page.locator("[data-category-bar]").first.is_visible()


# --- desktop -----------------------------------------------------------------


def test_the_headline_and_cards(open_page, history):
    page = open_page(APP)
    overview = page.get_by_role("region", name="Net worth")
    # 3000.50 + 10000 − 250.25, and against Sep 24 (exactly 30 days before):
    # 12750.25 − 11100.
    expect(overview).to_contain_text("$12,750")
    expect(overview).to_contain_text("+$1,650 (+14.9%) since Sep 24")
    expect(overview).to_contain_text("Last snapshot Oct 24, 2026")
    expect(overview.get_by_role("link", name="Update balances")).to_have_attribute(
        "href", f"{APP}/accounts"
    )
    expect(overview).to_contain_text("Bank Accounts $3,001")
    expect(overview).to_contain_text("Credit Cards $250")
    assets = page.locator(
        "section", has=page.get_by_role("heading", name="Assets", exact=True)
    )
    expect(assets).to_contain_text("Bank Accounts$3,001Checking$3,001")
    expect(assets.locator("[data-slot=card-total]")).to_have_text("$13,001")
    assert page.title() == "Test · Sensibility"


def test_a_desktop_chart_has_lines_columns_and_no_bars(open_page, seeded):
    page = open_page(APP)
    wait_for_chart(page)
    drawn = chart(page)
    assert drawn["layout"] == "desktop" and drawn["height"] == 320
    assert drawn["columns"] == 2  # one category (Uncategorized) per column
    assert drawn["divider"]
    assert page.locator(f"{CHART} .recharts-line").count() == 3
    assert not bars_shown(page)
    # A lone snapshot is drawn as dots, at the right of the month before it.
    assert page.locator(f"{CHART} .recharts-line-dots circle").count() == 3


def test_the_range_toggle_changes_the_url_without_reloading(open_page, history):
    page = open_page(APP)
    wait_for_chart(page)
    toggle = page.get_by_role("radiogroup", name="Range")
    expect(toggle.get_by_role("radio", name="1Y")).to_be_checked()
    year = " ".join(x_ticks(page).all_text_contents())
    assert "2025" not in year

    # Hold the new range's answer, to see what shows while it loads.
    held = []
    page.route(lambda url: "/dashboard?range=all" in url, lambda r: held.append(r))
    page.evaluate("window.notReloaded = true")
    toggle.get_by_role("radio", name="All").click()
    page.wait_for_url(f"**{APP}?range=all")
    expect(toggle.get_by_role("radio", name="All")).to_be_checked()
    for _ in range(50):
        if held:
            break
        page.wait_for_timeout(20)
    assert held, "the new range was not requested"
    # The previous range's numbers stay on screen meanwhile.
    expect(page.get_by_role("region", name="Net worth")).to_contain_text("$12,750")
    assert "2025" not in " ".join(x_ticks(page).all_text_contents())
    held[0].continue_()

    expect(x_ticks(page).first).to_contain_text("2025")
    assert page.evaluate("window.notReloaded") is True

    page.go_back()
    page.wait_for_url(f"**{APP}")
    expect(toggle.get_by_role("radio", name="1Y")).to_be_checked()
    expect(x_ticks(page).first).not_to_contain_text("2025")
    assert page.evaluate("window.notReloaded") is True


def test_an_unknown_range_is_a_year(open_page, history):
    page = open_page(f"{APP}?range=decade")
    toggle = page.get_by_role("radiogroup", name="Range")
    expect(toggle.get_by_role("radio", name="1Y")).to_be_checked()


def strokes(page: Page) -> list[str]:
    """Every line's and column block's color, as drawn."""
    return page.evaluate(
        """(sel) => [...document.querySelectorAll(
            `${sel} .recharts-line-curve, ${sel} .recharts-bar-rectangle path`
        )].map(e => {
            const st = getComputedStyle(e);
            return e.closest('.recharts-bar-rectangle') ? st.fill : st.stroke;
        })""",
        CHART,
    )


def token(page: Page, name: str) -> str:
    return page.evaluate(
        """(name) => {
        const probe = document.createElement('span');
        probe.style.color = `var(${name})`;
        document.body.appendChild(probe);
        const color = getComputedStyle(probe).color;
        probe.remove();
        return color;
    }""",
        name,
    )


def test_the_chart_rethemes_with_the_color_scheme(open_page, history):
    page = open_page("about:blank")
    page.emulate_media(color_scheme="light")
    page.goto(f"{APP}?range=all")
    wait_for_chart(page)
    light = strokes(page)
    assert len(light) == 3 + 3  # three lines, three categories
    assert light[0] == token(page, "--asset")
    assert light[2] == token(page, "--liability")

    page.emulate_media(color_scheme="dark")
    page.wait_for_function(
        "([sel, before]) => getComputedStyle(document.querySelector("
        "`${sel} .recharts-line-curve`)).stroke !== before",
        arg=[CHART, light[0]],
    )
    dark = strokes(page)
    assert len(dark) == len(light) and dark != light
    assert dark[0] == token(page, "--asset")
    assert dark[1] == token(page, "--ink")

    page.emulate_media(color_scheme="light")
    page.wait_for_function(
        "([sel, before]) => getComputedStyle(document.querySelector("
        "`${sel} .recharts-line-curve`)).stroke === before",
        arg=[CHART, light[0]],
    )
    assert strokes(page) == light


def test_hovering_shows_the_values(open_page, history):
    page = open_page(APP)
    wait_for_chart(page)
    grid = page.locator(f"{CHART} .recharts-cartesian-grid").first
    box = grid.bounding_box()
    assert box
    page.mouse.move(box["x"] + box["width"] - 2, box["y"] + box["height"] / 2)
    tooltip = page.locator("[data-chart-tooltip]")
    expect(tooltip).to_contain_text("Oct 24, 2026")
    expect(tooltip).to_contain_text("Assets$13,001")
    expect(tooltip).to_contain_text("Net worth$12,750")
    expect(tooltip).to_contain_text("Liabilities$250")


# --- phones ------------------------------------------------------------------


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_the_dashboard_fits_a_phone(open_page, seeded, width):
    page = open_page(APP, phone=width)
    wait_for_chart(page)
    assert_fits_phone(page)
    # Update balances spans the card; the range toggle's segments are 44px.
    button = page.get_by_role("link", name="Update balances").bounding_box()
    region = page.get_by_role("region", name="Net worth").bounding_box()
    assert button and region
    assert abs(button["width"] - (region["width"] - 32)) < 1
    radios = page.get_by_role("radiogroup", name="Range").get_by_role("radio").all()
    assert len(radios) == 3
    for radio in radios:
        segment = radio.bounding_box()
        assert segment and segment["height"] >= TARGET


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_a_viewer_dashboard_fits_a_phone(open_page, seeded, db_connection, width):
    as_viewer(db_connection)
    page = open_page(APP, phone=width)
    wait_for_chart(page)
    assert_fits_phone(page)


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_a_dashboard_with_history_fits_a_phone(open_page, history, width):
    page = open_page(f"{APP}?range=all", phone=width)
    wait_for_chart(page)
    assert_fits_phone(page)


@pytest.mark.parametrize("width", PHONE_WIDTHS)
@pytest.mark.parametrize("with_accounts", [False, True])
def test_the_getting_started_dashboard_fits_a_phone(
    open_page, db_connection, width, with_accounts
):
    if with_accounts:
        create_account(db_connection, WS, "Checking", RecordType.ASSET)
    page = open_page(APP, phone=width)
    page.get_by_role("heading", name=WELCOME).wait_for()
    assert_fits_phone(page)
    welcome = page.get_by_role("region", name=WELCOME).bounding_box()
    placeholder = page.locator("[data-placeholder-chart]").bounding_box()
    assert welcome and placeholder
    assert placeholder["x"] + placeholder["width"] <= welcome["x"] + welcome["width"]


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_a_phone_chart_is_lines_only_at_full_width_with_bars_below(
    open_page, history, width
):
    page = open_page(APP, phone=width)
    wait_for_chart(page)
    drawn = chart(page)
    assert drawn["layout"] == "phone" and drawn["height"] == 240
    # Not merely hidden: no columns, no divider before them.
    assert drawn["columns"] == 0 and not drawn["divider"]
    # The lines' plot takes the chart's width, less the dollar labels.
    assert drawn["plotWidth"] > drawn["chartWidth"] - 70
    assert bars_shown(page)
    # One bar per type, each above its own key, in the key's colors.
    bars = page.locator("[data-category-bar]")
    assert bars.all_inner_texts() == ["Assets", "Liabilities"]
    asset_bar = page.locator("[data-category-bar=asset]").bounding_box()
    asset_key = page.locator("[data-key-group=asset]").bounding_box()
    liability_bar = page.locator("[data-category-bar=liability]").bounding_box()
    assert asset_bar and asset_key and liability_bar
    assert asset_bar["y"] < asset_key["y"] < liability_bar["y"]
    colors = page.locator("[data-bar-segment]").evaluate_all(
        "els => els.map(e => getComputedStyle(e).backgroundColor)"
    )
    swatches = page.locator("[data-key-group] [data-swatch]").evaluate_all(
        "els => els.map(e => getComputedStyle(e).backgroundColor)"
    )
    assert colors == swatches and len(colors) == 3
    # The key's titles are for screen readers only; the bars' stand for them.
    title = page.locator("[data-key-group=asset]").get_by_text("Assets", exact=True)
    found = title.bounding_box()
    assert found and found["width"] <= 1 and found["height"] <= 1
    # Every date label stays inside the chart.
    chart_box = page.locator(CHART).bounding_box()
    assert chart_box
    assert x_ticks(page).count() >= 2
    for label in x_ticks(page).all():
        found = label.bounding_box()
        assert (
            found
            and found["x"] + found["width"] <= chart_box["x"] + chart_box["width"] + 0.5
        )


def test_a_tap_shows_the_values(open_page, seeded):
    page = open_page(APP, phone=390)
    wait_for_chart(page)
    # seeded has one snapshot, drawn as dots at the right of the lines.
    dot = page.locator(f"{CHART} .recharts-line-dots circle").first
    box = dot.bounding_box()
    assert box
    page.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    tooltip = page.locator("[data-chart-tooltip]")
    expect(tooltip).to_contain_text("Net worth")
    expect(tooltip).to_contain_text("Assets")
    expect(tooltip).to_contain_text("Liabilities")
    expect(tooltip).to_contain_text("$")


def test_the_chart_relays_when_the_width_crosses_the_breakpoint(open_page, seeded):
    page = open_page(APP, phone=390)
    wait_for_chart(page)
    assert chart(page)["columns"] == 0

    page.set_viewport_size({"width": 1280, "height": 900})
    page.wait_for_function(
        f"document.querySelector('{CHART}').dataset.chart === 'desktop'"
    )
    drawn = chart(page)
    assert drawn["columns"] == 2 and drawn["divider"] and drawn["height"] == 320
    assert not bars_shown(page)

    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_function(
        f"document.querySelector('{CHART}').dataset.chart === 'phone'"
    )
    assert chart(page)["columns"] == 0
    assert bars_shown(page)


# --- getting started (board Y) -----------------------------------------------


def test_a_new_workspace_offers_to_add_an_account(open_page):
    page = open_page(APP)
    expect(page.get_by_role("heading", name=WELCOME)).to_be_visible()
    expect(page.get_by_text("Test is new")).to_be_visible()
    steps = page.get_by_role("region", name=WELCOME).get_by_role("listitem")
    expect(steps).to_have_count(3)
    expect(steps.nth(0)).to_contain_text("1Add your accounts")
    links = page.locator("main a[href*='/accounts']")
    expect(links).to_have_text(
        ["+ Add an account", "+ Add an asset", "+ Add a liability"]
    )
    expect(links.nth(0)).to_have_attribute("href", f"{APP}/accounts/new?type=asset")
    expect(links.nth(2)).to_have_attribute("href", f"{APP}/accounts/new?type=liability")
    expect(page.get_by_text("No assets yet.")).to_be_visible()
    expect(page.get_by_text("editor")).to_have_count(0)
    # A client-side move to the account drawer.
    page.evaluate("window.notReloaded = true")
    links.nth(0).click()
    page.wait_for_url(f"**{APP}/accounts/new?type=asset")
    assert page.evaluate("window.notReloaded") is True


def test_with_accounts_but_no_snapshot_it_goes_to_enter_balances(
    open_page, db_connection
):
    create_account(db_connection, WS, "Cash", RecordType.ASSET)
    create_account(db_connection, WS, "Brokerage", RecordType.ASSET)
    page = open_page(APP)
    steps = page.get_by_role("region", name=WELCOME).get_by_role("listitem")
    expect(steps.nth(0)).to_contain_text("✓Add your accounts")
    expect(steps.nth(0)).to_contain_text("Done: 2 accounts added.")
    link = page.get_by_role("link", name="Enter balances")
    expect(link).to_have_attribute("href", f"{APP}/accounts")
    assets = page.locator(
        "section", has=page.get_by_role("heading", name="Assets", exact=True)
    )
    expect(assets.locator("[data-slot=card-total]")).to_have_text("—")
    expect(assets).to_contain_text("Cash—")
    expect(page.get_by_role("link", name="+ Add a liability")).to_be_visible()


@pytest.mark.parametrize("with_accounts", [False, True])
def test_a_viewer_is_told_an_editor_has_not_started(
    open_page, db_connection, with_accounts
):
    if with_accounts:
        create_account(db_connection, WS, "Cash", RecordType.ASSET)
    as_viewer(db_connection)
    page = open_page(APP)
    expect(page.get_by_role("heading", name=WELCOME)).to_be_visible()
    note = (
        "An editor hasn't entered any balances yet."
        if with_accounts
        else "An editor hasn't added any accounts yet."
    )
    expect(page.get_by_text(note)).to_be_visible()
    expect(page.locator("main a[href*='/accounts']")).to_have_count(0)
