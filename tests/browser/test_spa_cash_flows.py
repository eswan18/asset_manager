"""The Cash flows page and its drawers, in a real browser against the built
app: the page in every state and period, the period toggle (no reload), the
cash flow drawer (the rates strip against the service's arithmetic, the
header colors, save and delete), the categories drawer (rename on blur,
Enter's single save, the 44px move targets, delete, add), and every state
fitting a phone."""

import random
import re
from decimal import Decimal

import pytest
from playwright.sync_api import Page, expect

from sensibility.accounts import MAX_AMOUNT
from sensibility.cashflows import (
    MAX_EVERY,
    create_cash_flow,
    create_category,
    per_year,
    rates,
)
from sensibility.formulas import quantize_cents
from sensibility.models import CashFlow, CashFlowDirection, FrequencyUnit
from tests.browser.mobile import PHONE_WIDTHS, assert_fits_phone
from tests.support import USER_ID, WS

pytestmark = [pytest.mark.browser, pytest.mark.db]

APP = f"/workspaces/{WS}"
FLOWS = f"{APP}/cash-flows"
CATEGORIES = f"{APP}/cash-flow-categories"
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
    """Work holds only income, Gifts nothing; a seven-figure Gym."""
    conn = db_connection
    cats = {
        n: create_category(conn, WS, n) for n in ("Work", "Housing", "Food", "Gifts")
    }
    flows = {
        f.name: create_cash_flow(conn, WS, f)
        for f in [
            flow("Salary", "5100", 2, "week", "income", category_id=cats["Work"].id),
            flow("Mortgage", "2450", 1, "month", category_id=cats["Housing"].id),
            flow(
                "Groceries",
                "180",
                1,
                "week",
                category_id=cats["Food"].id,
                is_estimate=True,
            ),
            flow("Car insurance", "1140", 6, "month"),
            flow("Domain", "12.99", 1, "year"),
            flow("Coffee", "4.75", 1, "day", category_id=cats["Food"].id),
            flow("Gym", "1234567.89", 3, "year"),
        ]
    }
    conn.commit()
    return cats, flows


def _seed(conn, flows_by_category, income) -> dict:
    cats = {}
    for name, flows in flows_by_category.items():
        cat_id = None
        if name is not None:
            cats[name] = create_category(conn, WS, name)
            cat_id = cats[name].id
        for name_, amount, every, unit, *estimate in flows:
            create_cash_flow(
                conn,
                WS,
                flow(
                    name_,
                    amount,
                    every,
                    unit,
                    category_id=cat_id,
                    is_estimate=bool(estimate),
                ),
            )
    ids = {}
    for f in income:
        ids[f[0]] = create_cash_flow(conn, WS, flow(*f, "income")).id
    conn.commit()
    return {"cats": cats, "income": ids}


@pytest.fixture
def household(db_connection):
    """Six-figure income, long category names, estimates: the busy case."""
    return _seed(
        db_connection,
        {
            "Housing": [("Mortgage payment", "2650", 1, "month")],
            "Food & groceries": [
                ("Groceries", "260", 1, "week", "estimate"),
                ("Restaurants", "400", 1, "month"),
            ],
            "Kids & childcare": [("Daycare", "1900", 1, "month")],
            "Subscriptions": [("Spotify Family", "19.99", 1, "month")],
            None: [("Gym", "60", 1, "month")],
        },
        [("Ethan salary", "6200", 2, "week"), ("Jordan salary", "5400", 2, "week")],
    )


@pytest.fixture
def over(db_connection):
    """Expenses above income (board AA)."""
    return _seed(
        db_connection,
        {
            "Upkeep and repairs": [("Dock repairs", "300", 1, "month")],
            None: [("Lake house mortgage", "1650", 1, "month")],
        },
        [("Rental income", "1400", 1, "month")],
    )


def make_viewer(db_connection) -> None:
    db_connection.execute(
        "UPDATE workspace_members SET role = 'viewer'"
        " WHERE workspace_id = %s AND user_id = %s",
        (WS, USER_ID),
    )
    db_connection.commit()


def flow_id(db_connection, name: str) -> int:
    row = db_connection.execute(
        "SELECT id FROM cash_flows WHERE workspace_id = %s AND name = %s", (WS, name)
    ).fetchone()
    assert row is not None
    return row[0]


def category_names(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT name FROM cash_flow_categories WHERE workspace_id = %s"
            " ORDER BY position, id",
            (WS,),
        )
        return [row[0] for row in cur.fetchall()]


def settled(page: Page) -> None:
    """On a phone a drawer slides up; measure once it has arrived."""
    page.wait_for_function(
        "document.getAnimations().every(a => a.playState === 'finished')"
    )


def check_one_row(page: Page, selector: str) -> None:
    """Every child of `selector` shares one bottom edge: one row, not stacked."""
    page.locator(selector).first.wait_for()
    tops = page.eval_on_selector_all(
        f"{selector} > *",
        "els => els.map(e => Math.round(e.getBoundingClientRect().bottom))",
    )
    assert len(tops) > 1 and len(set(tops)) == 1, tops


def writes(page: Page) -> list[str]:
    """The API writes the page sends, as "METHOD path", from now on."""
    sent: list[str] = []
    page.on(
        "request",
        lambda r: (
            sent.append(f"{r.method} {r.url.split('/api/', 1)[1]}")
            if r.method != "GET" and "/api/" in r.url
            else None
        ),
    )
    return sent


# --- the page ------------------------------------------------------------------


def test_the_page(open_page, household, db_connection):
    page = open_page(FLOWS)
    expect(page.get_by_text("Left over each month")).to_be_visible()
    assert page.title() == "Cash flows · Test · Sensibility"
    cards = page.locator("[data-slot=flow-card] h2")
    expect(cards).to_have_text(
        [
            "Income",
            "Housing",
            "Food & groceries",
            "Kids & childcare",
            "Subscriptions",
            "Uncategorized",
        ]
    )
    groceries = page.get_by_role("link", name=re.compile("^Groceries"))
    expect(groceries).to_have_attribute(
        "href", f"{FLOWS}/{flow_id(db_connection, 'Groceries')}/edit?per=month"
    )
    expect(groceries.get_by_title("Estimate")).to_be_visible()
    expect(page.get_by_role("link", name="Add to Kids & childcare")).to_be_visible()
    expect(page.get_by_role("img")).to_have_attribute(
        "aria-label",
        "Of $25,202.38 income each month: Housing 11%, Food & groceries 6%,"
        " Kids & childcare 8%, Subscriptions <1%, Uncategorized <1%, Left over 76%",
    )


def test_the_period_toggle_changes_the_page_in_place(open_page, household):
    page = open_page(FLOWS)
    expect(page.get_by_text("Left over each month")).to_be_visible()
    # Survives only if the document does: a reload would drop it.
    page.evaluate("window.notReloaded = true")
    toggle = page.get_by_role("radiogroup", name="Show amounts per")
    toggle.get_by_role("radio", name="Year").click()
    expect(page.get_by_text("Left over each year")).to_be_visible()
    assert page.url.endswith(f"{FLOWS}?per=year")
    assert page.evaluate("window.notReloaded") is True
    expect(page.get_by_role("link", name="Manage categories")).to_have_attribute(
        "href", f"{CATEGORIES}?per=year"
    )
    # Back is the month again.
    page.go_back()
    expect(page.get_by_text("Left over each month")).to_be_visible()
    assert page.evaluate("window.notReloaded") is True


def test_the_page_follows_the_dark_theme(open_page, seed):
    page = open_page(FLOWS)
    card = page.locator("[data-slot=flow-card]").first
    expect(card).to_be_visible()
    light = card.evaluate("e => getComputedStyle(e).backgroundColor")
    page.emulate_media(color_scheme="dark")
    dark = card.evaluate("e => getComputedStyle(e).backgroundColor")
    assert (light, dark) == ("rgb(255, 255, 255)", "rgb(22, 31, 28)")


@pytest.mark.parametrize("width", PHONE_WIDTHS)
@pytest.mark.parametrize("per", ["day", "month", "year"])
def test_the_page_fits_in_every_period(open_page, household, width, per):
    page = open_page(f"{FLOWS}?per={per}", phone=width)
    expect(page.get_by_text(f"Left over each {per}")).to_be_visible()
    assert_fits_phone(page)
    # The period toggle spans the card in three equal segments.
    card = page.locator("[data-slot=flows-top]").bounding_box()
    toggle = page.get_by_role("radiogroup").bounding_box()
    assert card and toggle
    assert toggle["width"] > card["width"] - 2 * 24
    widths = {
        round(b["width"])
        for b in (r.bounding_box() for r in page.get_by_role("radio").all())
        if b
    }
    assert max(widths) - min(widths) <= 1
    # The figure stays on one line.
    figure = page.locator("[data-slot=headline-figure]")
    line = float(figure.evaluate("e => parseFloat(getComputedStyle(e).fontSize)"))
    box = figure.bounding_box()
    assert box and box["height"] < line * 1.5


def test_the_two_buttons_share_a_row_at_390(open_page, household):
    page = open_page(FLOWS, phone=390)
    check_one_row(page, "[data-slot=flows-buttons]")


@pytest.mark.parametrize("width", [None, *PHONE_WIDTHS])
def test_expenses_above_income(open_page, over, width):
    page = open_page(FLOWS, phone=width)
    expect(page.get_by_text("Short each month")).to_be_visible()
    figure = page.locator("[data-slot=headline-figure]")
    expect(figure).to_have_text("−$550.00")
    danger = figure.evaluate("e => getComputedStyle(e).color")
    assert danger == "rgb(180, 35, 24)"
    if width:
        assert_fits_phone(page)
    # "▲ Income runs out" stays inside the card.
    card = page.locator("[data-slot=flows-top]").bounding_box()
    label = page.get_by_text("▲ Income runs out").bounding_box()
    assert card and label
    assert (
        label["x"] >= card["x"]
        and label["x"] + label["width"] <= card["x"] + card["width"]
    )


@pytest.mark.parametrize("width", [None, *PHONE_WIDTHS])
def test_the_viewer_page(open_page, household, db_connection, width):
    make_viewer(db_connection)
    page = open_page(FLOWS, phone=width)
    expect(page.get_by_text("Left over each month")).to_be_visible()
    assert page.locator("main a").count() == 0
    if width:
        assert_fits_phone(page)


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_the_empty_page_fits(open_page, db_connection, width):
    page = open_page(FLOWS, phone=width)
    expect(page.get_by_role("heading", name="No cash flows yet")).to_be_visible()
    expect(page.get_by_role("link", name="+ Add income")).to_be_visible()
    assert_fits_phone(page)


# --- the cash flow drawer: the rates strip and header ---------------------------


def strip(page: Page) -> list[str]:
    return [page.locator(f"#rate-{p}").inner_text() for p in ("day", "month", "year")]


def server(amount: str, every: str, unit: str) -> list[str]:
    """The strip the service's own arithmetic gives for the drawer's fields:
    plain digits only (a $ and commas allowed), an amount the service would
    store and an `every` it accepts, rounded to cents, then `rates()`.
    Anything else shows dashes."""
    cleaned = re.sub(r"[$,\s]", "", amount)
    if not re.fullmatch(r"[0-9]+\.?[0-9]*|\.[0-9]+", cleaned):
        return DASHES
    if not re.fullmatch(r"[0-9]+", every.strip()):
        return DASHES
    value, count = Decimal(cleaned), int(every)
    if value >= MAX_AMOUNT or not 1 <= count <= MAX_EVERY:
        return DASHES
    flow = CashFlow(
        name="",
        direction=CashFlowDirection.INCOME,
        amount=quantize_cents(value),
        every=count,
        unit=FrequencyUnit(unit),
    )
    found = rates(per_year(flow))
    return [f"${Decimal(found[k]):,.2f}" for k in ("per_day", "per_month", "per_year")]


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
def test_rates_strip_matches_the_server(open_page, seed, name):
    """A flow's own values give the strip the service's arithmetic gives."""
    _, flows = seed
    f = flows[name]
    page = open_page(f"{FLOWS}/{f.id}/edit?per=month")
    expect(page.get_by_role("dialog", name=name)).to_be_visible()
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
    rng = random.Random(20261028)
    for _ in range(40):
        amount = f"{rng.randrange(0, 10 ** rng.randrange(1, 10))}.{rng.randrange(0, 1000):03d}"
        every = str(rng.choice([1, 2, 3, 6, 7, 12, 13, 52, 365, 1000]))
        unit = rng.choice(["day", "week", "month", "year"])
        enter(page, amount, every, unit)
        assert strip(page) == server(amount, every, unit), (amount, every, unit)


def test_header_follows_direction_and_category(open_page, seed):
    _, flows = seed
    page = open_page(f"{FLOWS}/{flows['Groceries'].id}/edit")
    dialog = page.get_by_role("dialog", name="Groceries")
    eyebrow = dialog.locator("[data-slot=eyebrow]")

    def section() -> str:
        return dialog.evaluate("el => el.style.getPropertyValue('--section').trim()")

    def rule() -> str:
        return dialog.locator("[data-slot=sheet-head]").evaluate(
            "el => getComputedStyle(el).borderBottomColor"
        )

    # Each expense's color is its card's on the page.
    overview = page.request.get(f"/api/workspaces/{WS}/cash-flows/overview").json()
    colors = {c["name"]: c["expense_color"] for c in overview["categories"]}

    expect(eyebrow).to_have_text("Edit expense · Food")
    food = section()
    assert food == colors["Food"]

    dialog.get_by_text("Income", exact=True).click()
    expect(eyebrow).to_have_text("Edit income · Food")
    assert section() == "var(--asset)"
    assert rule() == "rgb(23, 105, 79)"  # --asset, light

    dialog.get_by_text("Expense", exact=True).click()
    expect(eyebrow).to_have_text("Edit expense · Food")
    assert section() == food

    select = dialog.get_by_role("combobox", name="Category")
    select.select_option(label="Housing")
    expect(eyebrow).to_have_text("Edit expense · Housing")
    assert section() == colors["Housing"] not in (food, "var(--asset)")

    select.select_option(label="Uncategorized")
    expect(eyebrow).to_have_text("Edit expense")
    assert section() == overview["uncategorized_color"]


def test_flow_drawer_is_modal_and_escape_closes_it(open_page, seed):
    _, flows = seed
    page = open_page(f"{FLOWS}/{flows['Mortgage'].id}/edit?per=year")
    dialog = page.get_by_role("dialog", name="Mortgage")
    expect(dialog).to_be_visible()
    assert page.evaluate("getComputedStyle(document.body).overflow") == "hidden"
    behind = page.locator("[data-slot=flow-row]").first
    behind.evaluate("el => el.focus()")
    expect(behind).not_to_be_focused()
    page.keyboard.press("Escape")
    page.wait_for_url(f"**{FLOWS}?per=year")
    expect(dialog).to_have_count(0)
    # The seven-figure Gym puts the seed's expenses above its income.
    expect(page.get_by_text("Short each year")).to_be_visible()


# --- the cash flow drawer: writes ------------------------------------------------


def test_add_a_flow(open_page, seed, db_connection):
    cats, _ = seed
    page = open_page(f"{FLOWS}?per=year")
    page.get_by_role("link", name="Add to Housing").click()
    dialog = page.get_by_role("dialog", name="New cash flow")
    expect(dialog.locator("[data-slot=eyebrow]")).to_have_text("New expense · Housing")
    form = page.locator("#flow-form")
    form.locator("[name=name]").fill("  Gym pass  ")
    form.locator("[name=amount]").fill("$1,045.505")
    form.locator("[name=every]").fill("2")
    form.locator("[name=unit]").select_option("week")
    dialog.get_by_text("This is an estimate").click()
    form.locator("[name=description]").fill(" Monthly pass ")
    dialog.get_by_role("button", name="Save").click()

    expect(page.get_by_role("status")).to_contain_text(
        "Added Gym pass: $2,271.49 a month."
    )
    page.wait_for_url(f"**{FLOWS}?per=year")
    expect(page.get_by_role("link", name="Gym pass")).to_be_visible()
    db_connection.rollback()
    saved = db_connection.execute(
        "SELECT amount, every, unit, category_id, is_estimate, description"
        " FROM cash_flows WHERE workspace_id = %s AND name = 'Gym pass'",
        (WS,),
    ).fetchone()
    assert saved == (
        Decimal("1045.51"),
        2,
        "week",
        cats["Housing"].id,
        True,
        "Monthly pass",
    )


@pytest.mark.parametrize(
    ("amount", "every", "message"),
    [
        ("12.345.6", "1", "Amount must be a number"),
        ("-5", "1", "Amount cannot be negative; set the direction to expense instead"),
        ("10000000000000", "1", "Amount is too large"),
        ("5", "0", "Every must be between 1 and 1000"),
        ("5", "1.5", "Every must be a whole number, e.g. 2 for every 2 weeks"),
        ("5.", "1", None),
        (".5", "1", None),
    ],
)
def test_every_refusal_shows_in_the_drawer(open_page, seed, amount, every, message):
    page = open_page(f"{FLOWS}/new")
    dialog = page.get_by_role("dialog", name="New cash flow")
    form = page.locator("#flow-form")
    form.locator("[name=name]").fill(f"Test {amount}")
    form.locator("[name=amount]").fill(amount)
    form.locator("[name=every]").fill(every)
    dialog.get_by_role("button", name="Save").click()
    if message is None:
        page.wait_for_url(f"**{FLOWS}?per=month")
        return
    expect(dialog.get_by_role("alert")).to_have_text(message)
    expect(form.locator("[name=amount]")).to_have_value(amount)


def test_a_taken_name_is_refused(open_page, seed):
    _, flows = seed
    page = open_page(f"{FLOWS}/{flows['Groceries'].id}/edit")
    dialog = page.get_by_role("dialog", name="Groceries")
    page.locator("#flow-form [name=name]").fill("Mortgage")
    dialog.get_by_role("button", name="Save").click()
    expect(dialog.get_by_role("alert")).to_have_text(
        "A cash flow named 'Mortgage' already exists"
    )


def test_edit_and_delete(open_page, seed, db_connection):
    _, flows = seed
    page = open_page(f"{FLOWS}?per=day")
    page.get_by_role("link", name="Coffee").click()
    dialog = page.get_by_role("dialog", name="Coffee")
    page.locator("#flow-form [name=amount]").fill("5.25")
    page.locator("#flow-form [name=category_id]").select_option(label="Uncategorized")
    dialog.get_by_role("button", name="Save").click()
    expect(page.get_by_role("status")).to_contain_text("Saved Coffee: $159.69 a month.")
    page.wait_for_url(f"**{FLOWS}?per=day")
    db_connection.rollback()
    row = db_connection.execute(
        "SELECT amount, category_id FROM cash_flows WHERE id = %s",
        (flows["Coffee"].id,),
    ).fetchone()
    assert row == (Decimal("5.25"), None)

    page.get_by_role("link", name="Coffee").click()
    page.get_by_role("dialog", name="Coffee").get_by_role(
        "button", name="Delete"
    ).click()
    page.wait_for_url(f"**{FLOWS}?per=day")
    expect(page.get_by_text("Deleted Coffee")).to_be_visible()
    expect(page.get_by_role("link", name="Coffee")).to_have_count(0)
    db_connection.rollback()
    assert (
        db_connection.execute(
            "SELECT 1 FROM cash_flows WHERE id = %s", (flows["Coffee"].id,)
        ).fetchone()
        is None
    )


# --- the cash flow drawer on a phone ------------------------------------------------


def drawer_states(db_connection) -> dict[str, str]:
    return {
        "new income": f"{FLOWS}/new?direction=income",
        "new expense": f"{FLOWS}/new?direction=expense",
        "edit": f"{FLOWS}/{flow_id(db_connection, 'Ethan salary')}/edit",
    }


@pytest.mark.parametrize("width", PHONE_WIDTHS)
@pytest.mark.parametrize("state", ["new income", "new expense", "edit"])
def test_the_flow_drawer_fits(open_page, household, db_connection, width, state):
    page = open_page(drawer_states(db_connection)[state], phone=width)
    expect(page.get_by_role("dialog")).to_be_visible()
    settled(page)
    assert_fits_phone(page)
    check_one_row(page, "[data-slot=frequency]")
    check_one_row(page, "[data-slot=rates]")
    # The amount takes the room left over, and shows a whole amount.
    amount = page.locator("input[name=amount]").bounding_box()
    unit = page.locator("select[name=unit]").bounding_box()
    assert amount and unit and amount["width"] >= unit["width"] * 0.85


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_the_rates_strip_keeps_six_figures_on_one_line(
    open_page, household, db_connection, width
):
    # Ethan salary: $6,200 every 2 weeks is $161,642.86 a year.
    page = open_page(
        f"{FLOWS}/{flow_id(db_connection, 'Ethan salary')}/edit", phone=width
    )
    expect(page.locator("#rate-year")).to_have_text("$161,642.86")
    settled(page)
    check_one_row(page, "[data-slot=rates]")
    for cell in ("day", "month", "year"):
        strong = page.locator(f"#rate-{cell}")
        line = float(
            strong.evaluate("e => parseFloat(getComputedStyle(e).lineHeight) || 0")
        )
        size = float(strong.evaluate("e => parseFloat(getComputedStyle(e).fontSize)"))
        box = strong.bounding_box()
        assert box and box["height"] < max(line, size) * 1.6, cell
    # Typing keeps it one row.
    page.fill("input[name=amount]", "98765.43")
    check_one_row(page, "[data-slot=rates]")


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_a_refused_flow_fits(open_page, household, width):
    page = open_page(f"{FLOWS}/new?direction=expense", phone=width)
    dialog = page.get_by_role("dialog")
    page.fill("input[name=name]", "Groceries")
    page.fill("input[name=amount]", "12.345.6")
    dialog.get_by_role("button", name="Save").click()
    expect(dialog.get_by_role("alert")).to_be_visible()
    settled(page)
    assert_fits_phone(page)
    check_one_row(page, "[data-slot=frequency]")


# --- the categories drawer -------------------------------------------------------


@pytest.fixture
def categories(open_page, seed):
    """The categories drawer, and the API writes it sends."""
    page = open_page(f"{CATEGORIES}?per=month")
    expect(page.get_by_role("dialog", name="Categories")).to_be_visible()
    return page, writes(page)


def test_rename_saves_on_blur(categories, seed, db_connection):
    page, sent = categories
    food = page.get_by_label("Name of Food")
    food.fill("Food & drink")
    food.blur()
    expect(page.get_by_role("status")).to_have_text("Saved Food & drink")
    food_id = seed[0]["Food"].id
    assert sent == [f"PATCH workspaces/{WS}/cash-flow-categories/{food_id}"]
    assert category_names(db_connection) == ["Work", "Housing", "Food & drink", "Gifts"]
    expect(page.get_by_label("Name of Food & drink")).to_have_value("Food & drink")


def test_unchanged_or_whitespace_rename_does_not_save(categories, db_connection):
    page, sent = categories
    work = page.get_by_label("Name of Work")
    work.focus()
    work.blur()
    work.fill("  Work  ")
    work.blur()
    page.get_by_label("New category name").focus()
    page.wait_for_timeout(300)
    assert sent == []
    assert category_names(db_connection) == ["Work", "Housing", "Food", "Gifts"]


def test_enter_saves_a_rename_once(categories, db_connection):
    """Enter saves; the field losing focus after it must not save again."""
    page, sent = categories
    gifts = page.get_by_label("Name of Gifts")
    gifts.fill("Presents")
    gifts.press("Enter")
    page.get_by_label("New category name").focus()
    expect(page.get_by_role("status")).to_have_text("Saved Presents")
    page.get_by_label("Name of Presents").focus()
    page.get_by_label("New category name").focus()
    page.wait_for_timeout(300)
    assert len(sent) == 1, sent
    assert category_names(db_connection) == ["Work", "Housing", "Food", "Presents"]


def test_a_refused_rename_stays_in_its_row(categories, db_connection):
    page, _ = categories
    food = page.get_by_label("Name of Food")
    food.fill("Housing")
    food.press("Enter")
    expect(page.get_by_role("dialog").get_by_role("alert")).to_have_text(
        "A category named 'Housing' already exists"
    )
    expect(food).to_have_value("Housing")
    expect(food).to_have_attribute("aria-invalid", "true")
    expect(food).to_be_focused()
    assert category_names(db_connection) == ["Work", "Housing", "Food", "Gifts"]


def test_categories_drawer_escape(categories):
    page, _ = categories
    expect(page.get_by_role("button", name="Move Work up")).to_be_disabled()
    page.keyboard.press("Escape")
    page.wait_for_url(f"**{FLOWS}?per=month")
    expect(page.get_by_role("dialog")).to_have_count(0)


@pytest.mark.parametrize("width", [1280, 390])
def test_move_arrows_are_44px_targets(categories, db_connection, width):
    page, _ = categories
    page.set_viewport_size({"width": width, "height": 900})
    settled(page)
    boxes = [
        b.bounding_box() for b in page.locator("[data-slot=cat-move] button").all()
    ]
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
    page.mouse.click(up["x"] + 3, up["y"] + 3)
    expect(page.get_by_role("status")).to_have_text("Moved Food up")
    assert category_names(db_connection) == ["Work", "Food", "Housing", "Gifts"]
    names = page.locator("[data-slot=cat-rename] input")
    assert names.evaluate_all("els => els.map(e => e.value)") == [
        "Work",
        "Food",
        "Housing",
        "Gifts",
    ]


def test_delete_a_category(categories, db_connection):
    page, _ = categories
    dialog = page.get_by_role("dialog")
    dialog.get_by_role("button", name="Delete Food").click()
    expect(dialog).to_contain_text(
        "Delete Food? 2 flows. They move to Uncategorized; nothing else is deleted."
    )
    expect(dialog.get_by_role("button", name="Keep")).to_be_focused()
    dialog.get_by_role("button", name="Delete category").click()
    expect(page.get_by_role("status")).to_have_text("Deleted Food")
    assert category_names(db_connection) == ["Work", "Housing", "Gifts"]
    # Behind the drawer, its flows now sit under Uncategorized.
    page.keyboard.press("Escape")
    uncategorized = page.locator("[data-slot=flow-card]").filter(
        has=page.get_by_role("heading", name="Uncategorized")
    )
    expect(uncategorized.get_by_role("link", name="Groceries")).to_be_visible()


def test_add_a_category(categories, db_connection):
    page, _ = categories
    field = page.get_by_label("New category name")
    field.fill(" Pets ")
    field.press("Enter")
    expect(page.get_by_role("status")).to_have_text("Added Pets")
    expect(field).to_have_value("")
    expect(field).to_be_focused()
    assert category_names(db_connection)[-1] == "Pets"
    field.fill("Food")
    page.get_by_role("button", name="+ Add").click()
    expect(page.get_by_role("dialog").get_by_role("alert")).to_have_text(
        "A category named 'Food' already exists"
    )
    expect(field).to_have_value("Food")


def test_new_category_starts_in_the_new_name(open_page, seed):
    page = open_page(FLOWS)
    page.get_by_role("link", name="+ New category").click()
    page.wait_for_url(f"**{CATEGORIES}?per=month&add=1")
    expect(page.get_by_label("New category name")).to_be_focused()


@pytest.mark.parametrize("width", PHONE_WIDTHS)
@pytest.mark.parametrize("query", ["", "&add=1"])
def test_the_categories_drawer_fits(open_page, household, width, query):
    page = open_page(f"{CATEGORIES}?per=month{query}", phone=width)
    rows = page.locator("[data-slot=cat-row]")
    expect(rows).to_have_count(4)
    settled(page)
    assert_fits_phone(page)
    check_one_row(page, "[data-slot=cat-add]")
    # Each row: arrows, name field and delete side by side.
    for row in rows.all():
        boxes = [
            row.locator(s).bounding_box()
            for s in ("[data-slot=cat-move]", "input", "button[aria-label^=Delete]")
        ]
        assert all(boxes)
        left = [b["x"] for b in boxes if b]
        assert left == sorted(left)


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_the_delete_confirm_fits(open_page, household, width):
    page = open_page(f"{CATEGORIES}?per=month", phone=width)
    page.get_by_role("button", name="Delete Housing").click()
    expect(page.locator("[data-slot=cat-confirm]")).to_be_visible()
    settled(page)
    assert_fits_phone(page)
    check_one_row(page, "[data-slot=cat-confirm-actions]")
    # Neither button's label wraps.
    for button in page.locator("[data-slot=cat-confirm-actions] button").all():
        box = button.bounding_box()
        assert box and box["height"] < 50


def test_a_rename_still_saves_on_blur_on_a_phone(open_page, household, db_connection):
    page = open_page(f"{CATEGORIES}?per=month", phone=320)
    field = page.locator("[data-slot=cat-rename] input").first
    field.fill("Home")
    page.get_by_text("Order here is the order").click()
    expect(page.get_by_role("status")).to_have_text("Saved Home")
    expect(page.locator("[data-slot=cat-rename] input").first).to_have_value("Home")
    assert_fits_phone(page)


# --- roles ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path", ["cash-flows/new?per=year", "cash-flow-categories?per=year"]
)
def test_a_viewer_is_sent_back_from_a_drawer(open_page, seed, db_connection, path):
    make_viewer(db_connection)
    page = open_page(f"{APP}/{path}")
    page.wait_for_url(f"**{FLOWS}?per=year")
    expect(page.get_by_role("dialog")).to_have_count(0)
