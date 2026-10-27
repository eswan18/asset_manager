"""The cash flow drawers' scripts: the rates strip and header in the flow
form, and rename-on-blur in the categories drawer."""

import random
from decimal import Decimal

import pytest
from playwright.sync_api import Page, expect

from asset_manager.cashflows import create_cash_flow, create_category
from asset_manager.models import CashFlow, CashFlowDirection, FrequencyUnit
from asset_manager.web.cash_flows_routes import form_rates
from tests.support import WS
from tests.web_support import PAGES

pytestmark = [pytest.mark.browser, pytest.mark.db]

FLOWS = f"{PAGES}/cash-flows"
CATEGORIES = f"{PAGES}/cash-flow-categories?per=month"
DASHES = ["—", "—", "—"]


def flow(name, amount, every, unit, direction="expense", **extra) -> CashFlow:
    return CashFlow(
        name=name,
        direction=CashFlowDirection(direction),
        amount=Decimal(amount),
        every=every,
        unit=FrequencyUnit(unit),
        **extra,
    )


@pytest.fixture
def seed(db_connection):
    conn = db_connection
    cats = {
        n: create_category(conn, WS, n) for n in ("Work", "Housing", "Food", "Gifts")
    }
    flows = {
        f.name: create_cash_flow(conn, WS, f)
        for f in [
            flow("Salary", "5100", 2, "week", "income", category_id=cats["Work"].id),
            flow("Mortgage", "2450", 1, "month", category_id=cats["Housing"].id),
            flow("Groceries", "180", 1, "week", category_id=cats["Food"].id),
            flow("Car insurance", "1140", 6, "month"),
            flow("Domain", "12.99", 1, "year"),
            flow("Coffee", "4.75", 1, "day", category_id=cats["Food"].id),
            flow("Gym", "1234567.89", 3, "year"),
        ]
    }
    conn.commit()
    return cats, flows


def strip(page: Page) -> list[str]:
    return [page.locator(f"#rate-{p}").inner_text() for p in ("day", "month", "year")]


def server(amount: str, every: str, unit: str) -> list[str]:
    form = {
        "name": "",
        "direction": "expense",
        "category_id": "",
        "description": "",
        "is_estimate": False,
    }
    rates = form_rates({**form, "amount": amount, "every": every, "unit": unit})
    return (
        DASHES
        if rates is None
        else [rates[k] for k in ("per_day", "per_month", "per_year")]
    )


def enter(
    page: Page,
    amount: str | None = None,
    every: str | None = None,
    unit: str | None = None,
):
    form = page.locator("#flow-form")
    if amount is not None:
        form.locator("[name=amount]").fill(amount)
    if every is not None:
        form.locator("[name=every]").fill(every)
    if unit is not None:
        form.locator("[name=unit]").select_option(unit)


@pytest.mark.parametrize(
    "name",
    ["Salary", "Mortgage", "Groceries", "Car insurance", "Domain", "Coffee", "Gym"],
)
def test_rates_strip_matches_the_server_rendered_one(open_page, seed, name):
    """Retyping a flow's own values gives back the strip the server drew."""
    _, flows = seed
    f = flows[name]
    page = open_page(f"{FLOWS}/{f.id}/edit?per=month")
    rendered = strip(page)
    assert rendered == server(str(f.amount), str(f.every), f.unit.value)
    enter(page, amount="1", every="1", unit="day")
    assert strip(page) != rendered
    enter(page, amount=str(f.amount), every=str(f.every), unit=f.unit.value)
    assert strip(page) == rendered


def test_rates_strip_recomputes_in_cents(open_page, seed):
    _, flows = seed
    page = open_page(f"{FLOWS}/{flows['Groceries'].id}/edit")
    form = page.locator("#flow-form")
    expect(form.locator("[name=name]")).to_be_focused()

    cases = [
        (("100", "1", "week"), ["$14.29", "$434.52", "$5,214.29"]),
        (("5100", "2", "week"), ["$364.29", "$11,080.36", "$132,964.29"]),
        (("$1,200", "2", "year"), ["$1.64", "$50.00", "$600.00"]),
        (("1234567.89", "1", "year"), ["$3,382.38", "$102,880.66", "$1,234,567.89"]),
        (("0.005", "1", "day"), ["$0.01", "$0.30", "$3.65"]),  # half a cent rounds up
        (("0.004", "1", "day"), ["$0.00", "$0.00", "$0.00"]),
        (("0.06", "1", "year"), ["$0.00", "$0.01", "$0.06"]),
        ((".5", "1", "year"), ["$0.00", "$0.04", "$0.50"]),
        (("5.", "1", "year"), ["$0.01", "$0.42", "$5.00"]),
        (
            ("9999999999999.99", "1000", "day"),
            ["$10,000,000,000.00", "$304,166,666,666.67", "$3,650,000,000,000.00"],
        ),  # the largest
        (("", "1", "month"), DASHES),
        (("abc", "1", "month"), DASHES),
        (("-5", "1", "month"), DASHES),
        (("1e3", "1", "month"), DASHES),
        ((".", "1", "month"), DASHES),
        (("10000000000000", "1", "month"), DASHES),
        (("5", "0", "month"), DASHES),
        (("5", "1001", "month"), DASHES),
        (("5", "1.5", "month"), DASHES),
        (("5", "", "month"), DASHES),
    ]
    for (amount, every, unit), want in cases:
        enter(page, amount, every, unit)
        assert strip(page) == want == server(amount, every, unit), (amount, every, unit)

    # And random ones, against the server's arithmetic.
    rng = random.Random(20261026)
    for _ in range(40):
        amount = f"{rng.randrange(0, 10 ** rng.randrange(1, 10))}.{rng.randrange(0, 1000):03d}"
        every = str(rng.choice([1, 2, 3, 6, 7, 12, 13, 52, 365, 1000]))
        unit = rng.choice(["day", "week", "month", "year"])
        enter(page, amount, every, unit)
        assert strip(page) == server(amount, every, unit), (amount, every, unit)


def test_header_follows_direction_and_category(open_page, seed):
    _, flows = seed
    page = open_page(f"{FLOWS}/{flows['Groceries'].id}/edit")
    eyebrow = page.locator("#drawer-eyebrow")
    drawer = page.locator(".drawer")

    def section() -> str:
        return drawer.evaluate("el => el.style.getPropertyValue('--section').trim()")

    def rule() -> str:
        return page.locator(".drawer-head").evaluate(
            "el => getComputedStyle(el).borderBottomColor"
        )

    expect(eyebrow).to_have_text("Edit expense · Food")
    food = section()

    page.get_by_role("radio", name="Income").check()
    expect(eyebrow).to_have_text("Edit income · Food")
    assert section() == "var(--asset)"
    income_dot = page.locator(".dot-income").evaluate(
        "el => getComputedStyle(el).backgroundColor"
    )
    assert rule() == income_dot

    page.get_by_role("radio", name="Expense").check()
    expect(eyebrow).to_have_text("Edit expense · Food")
    assert section() == food

    select = page.locator("#category-select")
    select.select_option(label="Housing")
    expect(eyebrow).to_have_text("Edit expense · Housing")
    assert section() not in (food, "var(--asset)")

    select.select_option(label="Uncategorized")
    expect(eyebrow).to_have_text("Edit expense")
    assert section() == select.locator("option").first.get_attribute("data-color")


def test_flow_drawer_is_modal_and_escape_closes_it(open_page, seed):
    _, flows = seed
    page = open_page(f"{FLOWS}/{flows['Mortgage'].id}/edit?per=year")
    assert page.evaluate("getComputedStyle(document.body).overflow") == "hidden"
    behind = page.locator("a.flow-row").first
    behind.evaluate("el => el.focus()")
    expect(behind).not_to_be_focused()

    close = page.locator(".drawer-close").get_attribute("href")
    assert close is not None and close.endswith("per=year")
    with page.expect_navigation():
        page.keyboard.press("Escape")
    assert page.url.endswith(close)
    expect(page.locator(".drawer")).to_have_count(0)


def category_names(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM cash_flow_categories ORDER BY position, id")
        return [row[0] for row in cur.fetchall()]


@pytest.fixture
def posts(open_page, seed):
    """The categories drawer, and a list of the POSTs it sends."""
    page = open_page(CATEGORIES)
    sent: list[str] = []
    page.on("request", lambda r: sent.append(r.url) if r.method == "POST" else None)
    return page, sent


def test_rename_saves_on_blur(posts, db_connection):
    page, sent = posts
    food = page.get_by_label("Name of Food")
    food.fill("Food & drink")
    with page.expect_navigation():
        food.blur()
    assert len(sent) == 1
    assert category_names(db_connection) == ["Work", "Housing", "Food & drink", "Gifts"]
    expect(page.get_by_label("Name of Food & drink")).to_have_value("Food & drink")
    expect(page.locator(".drawer-status")).not_to_be_empty()


def test_unchanged_or_whitespace_rename_does_not_submit(posts, db_connection):
    page, sent = posts
    work = page.get_by_label("Name of Work")
    work.focus()
    work.blur()
    work.fill("  Work  ")
    work.blur()
    page.get_by_label("New category name").focus()
    page.wait_for_timeout(300)
    assert sent == []
    assert category_names(db_connection) == ["Work", "Housing", "Food", "Gifts"]


def test_enter_submits_a_rename_once(posts, db_connection):
    """Enter fires change (which submits) and then the implicit submit. Chromium
    sends one POST either way, as the second navigation replaces the first,
    so count the submissions the page lets through instead."""
    page, sent = posts
    allowed: list[bool] = []
    page.expose_function(
        "recordSubmit", lambda prevented: allowed.append(not prevented)
    )
    # Bubbling to document runs after the form's own guard.
    page.evaluate(
        "document.addEventListener('submit', e => window.recordSubmit(e.defaultPrevented))"
    )
    gifts = page.get_by_label("Name of Gifts")
    gifts.fill("Presents")
    with page.expect_navigation():
        gifts.press("Enter")
    page.wait_for_load_state()
    assert allowed == [True, False], allowed
    assert len(sent) == 1, sent
    assert category_names(db_connection) == ["Work", "Housing", "Food", "Presents"]


def test_categories_drawer_escape(posts):
    page, _ = posts
    expect(page.get_by_role("button", name="Move Work up")).to_be_disabled()
    with page.expect_navigation():
        page.keyboard.press("Escape")
    assert page.url.endswith(f"{FLOWS}?per=month")


@pytest.mark.parametrize("width", [1280, 390])
def test_move_arrows_are_44px_targets(posts, db_connection, width):
    page, _ = posts
    page.set_viewport_size({"width": width, "height": 900})
    # On a phone the drawer slides up; measure once it has arrived.
    page.wait_for_function(
        "document.getAnimations().every(a => a.playState === 'finished')"
    )
    boxes = [b.bounding_box() for b in page.locator(".cat-move button").all()]
    assert boxes
    for box in boxes:
        assert box is not None
        assert round(box["width"]) >= 44 and round(box["height"]) >= 44, box
    # Stacked targets do not overlap, within a row or across rows.
    spans = sorted((b["y"], b["y"] + b["height"]) for b in boxes if b is not None)
    assert all(a[1] <= b[0] + 0.5 for a, b in zip(spans, spans[1:])), spans

    # A tap near the top edge of Food's up target, outside its chip, moves it.
    up = page.get_by_role("button", name="Move Food up").bounding_box()
    assert up is not None
    with page.expect_navigation():
        page.mouse.click(up["x"] + 3, up["y"] + 3)
    assert category_names(db_connection) == ["Work", "Food", "Housing", "Gifts"]
