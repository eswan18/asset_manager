"""Cash flows on a phone (docs/superpowers/specs/2026-10-26-mobile-design.md):
the page in each state and period, and both drawers in each state, at 320px
and 390px. No sideways scrolling, 44px targets, 16px fields."""

from decimal import Decimal

import pytest
from playwright.sync_api import Page

from asset_manager.cashflows import create_cash_flow, create_category
from asset_manager.models import CashFlow, CashFlowDirection, FrequencyUnit
from tests.browser.mobile import PHONE_WIDTHS, assert_fits_phone
from tests.support import USER_ID, WS
from tests.web_support import PAGES

pytestmark = [pytest.mark.browser, pytest.mark.db]

FLOWS = f"{PAGES}/cash-flows"
CATEGORIES = f"{PAGES}/cash-flow-categories"


def page_fits(page: Page) -> None:
    """assert_fits_phone for what this page puts in main. The header is the
    shell's, checked by test_mobile_shell.py; allow_small would cover its
    targets but not its 15px workspace select, so it is taken out of the
    layout here. (Under a drawer the header is inert and skipped anyway.)"""
    page.add_style_tag(content="header.shell-header { display: none !important; }")
    assert_fits_phone(page)


def flow(name, amount, every, unit, direction="expense", **extra) -> CashFlow:
    return CashFlow(
        name=name,
        direction=CashFlowDirection(direction),
        amount=Decimal(amount),
        every=every,
        unit=FrequencyUnit(unit),
        **extra,
    )


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


def flow_id(db_connection, name: str) -> int:
    row = db_connection.execute(
        "SELECT id FROM cash_flows WHERE workspace_id = %s AND name = %s", (WS, name)
    ).fetchone()
    assert row is not None
    return row[0]


def check_one_row(page: Page, selector: str) -> None:
    """Every child of `selector` shares one bottom edge: one row, not stacked."""
    tops = page.eval_on_selector_all(
        f"{selector} > *",
        "els => els.map(e => Math.round(e.getBoundingClientRect().bottom))",
    )
    assert len(tops) > 1 and len(set(tops)) == 1, tops


# --- the page ---


@pytest.mark.parametrize("width", PHONE_WIDTHS)
@pytest.mark.parametrize("per", ["day", "month", "year"])
def test_the_page_fits_in_every_period(open_page, household, width, per):
    page = open_page(f"{FLOWS}?per={per}", phone=width)
    page_fits(page)
    # The period toggle spans the card in three equal segments.
    card = page.locator(".flows-top").bounding_box()
    toggle = page.locator(".flows-actions .toggle").bounding_box()
    assert card and toggle
    assert toggle["width"] > card["width"] - 2 * 24
    widths = {
        round(b["width"])
        for b in (a.bounding_box() for a in page.locator(".toggle a").all())
        if b
    }
    assert max(widths) - min(widths) <= 1
    # The figure stays on one line.
    figure = page.locator(".headline-figure")
    line = float(figure.evaluate("e => parseFloat(getComputedStyle(e).fontSize)"))
    box = figure.bounding_box()
    assert box and box["height"] < line * 1.5


def test_the_two_buttons_share_a_row_at_390(open_page, household):
    page = open_page(FLOWS, phone=390)
    check_one_row(page, ".flows-buttons")


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_expenses_above_income_fits(open_page, over, width):
    page = open_page(FLOWS, phone=width)
    assert page.locator(".headline-figure.short").is_visible()
    page_fits(page)
    # "▲ Income runs out" stays inside the card.
    card = page.locator(".flows-top").bounding_box()
    label = page.locator(".marker-label span").bounding_box()
    assert card and label
    assert (
        label["x"] >= card["x"]
        and label["x"] + label["width"] <= card["x"] + card["width"]
    )


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_the_viewer_page_fits(open_page, household, db_connection, width):
    db_connection.execute(
        "UPDATE workspace_members SET role = 'viewer' WHERE workspace_id = %s AND user_id = %s",
        (WS, USER_ID),
    )
    db_connection.commit()
    page = open_page(FLOWS, phone=width)
    assert page.locator("a.flow-row").count() == 0
    page_fits(page)


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_the_empty_page_fits(open_page, db_connection, width):
    page = open_page(FLOWS, phone=width)
    assert page.locator(".empty-card").is_visible()
    page_fits(page)


# --- the cash flow drawer ---


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
    assert_fits_phone(page)
    check_one_row(page, ".frequency")
    check_one_row(page, ".rates")
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
    check_one_row(page, ".rates")
    for cell in ("day", "month", "year"):
        strong = page.locator(f"#rate-{cell}")
        line = float(
            strong.evaluate("e => parseFloat(getComputedStyle(e).lineHeight) || 0")
        )
        size = float(strong.evaluate("e => parseFloat(getComputedStyle(e).fontSize)"))
        box = strong.bounding_box()
        assert box and box["height"] < max(line, size) * 1.6, cell
    assert page.locator("#rate-year").inner_text() == "$161,642.86"
    # Typing keeps it one row.
    page.fill("input[name=amount]", "98765.43")
    check_one_row(page, ".rates")


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_a_refused_flow_fits(open_page, household, width):
    page = open_page(f"{FLOWS}/new?direction=expense", phone=width)
    page.fill("input[name=name]", "Groceries")
    page.fill("input[name=amount]", "12.345.6")
    page.evaluate("() => { document.getElementById('flow-form').noValidate = true; }")
    page.click(".drawer-foot .btn-primary")
    page.locator(".drawer-error").wait_for()
    assert_fits_phone(page)
    check_one_row(page, ".frequency")


# --- the categories drawer ---


@pytest.mark.parametrize("width", PHONE_WIDTHS)
@pytest.mark.parametrize("query", ["", "&add=1"])
def test_the_categories_drawer_fits(open_page, household, width, query):
    page = open_page(f"{CATEGORIES}?per=month{query}", phone=width)
    assert page.locator(".cat-row").count() == 4
    assert_fits_phone(page)
    check_one_row(page, ".cat-add")
    # Each row: arrows, name field and delete side by side.
    for row in page.locator(".cat-row").all():
        boxes = [
            row.locator(s).bounding_box()
            for s in (".cat-move", ".cat-rename input", ".cat-delete")
        ]
        assert all(boxes)
        left = [b["x"] for b in boxes if b]
        assert left == sorted(left)


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_the_delete_confirm_fits(open_page, household, width):
    housing = household["cats"]["Housing"].id
    page = open_page(f"{CATEGORIES}?per=month&confirm={housing}", phone=width)
    assert_fits_phone(page)
    check_one_row(page, ".cat-confirm-actions")
    # Neither button's label wraps.
    for button in page.locator(".cat-confirm-actions .btn").all():
        box = button.bounding_box()
        assert box and box["height"] < 50


def test_a_rename_still_saves_on_blur_on_a_phone(open_page, household, db_connection):
    page = open_page(f"{CATEGORIES}?per=month", phone=320)
    field = page.locator(".cat-rename input").first
    field.fill("Home")
    with page.expect_navigation():
        page.locator(".categories-intro").click()
    assert page.locator(".cat-rename input").first.input_value() == "Home"
    assert_fits_phone(page)
