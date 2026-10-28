"""The Cash flows page: its view model, and the page against the database."""

import re
from decimal import Decimal

import pytest

from sensibility.cashflows import CategoryTotal, Period, create_cash_flow
from sensibility.cashflows import create_category as create_flow_category
from sensibility.models import (
    CashFlow,
    CashFlowCategory,
    CashFlowDirection,
    FrequencyUnit,
)
from sensibility.web.cash_flows_model import EXPENSE_RAMP, expense_colors
from sensibility.web.cash_flows_routes import cash_flows_view, money
from sensibility.workspaces import create_workspace
from tests.support import USER_ID, WS
from tests.web_support import PAGES, login

INCOME, EXPENSE = CashFlowDirection.INCOME, CashFlowDirection.EXPENSE
WEEK, MONTH, YEAR = FrequencyUnit.WEEK, FrequencyUnit.MONTH, FrequencyUnit.YEAR
PAGE = f"{PAGES}/cash-flows"


def flow(name, amount, every=1, unit=MONTH, direction=EXPENSE, **extra) -> CashFlow:
    return CashFlow(
        name=name,
        direction=direction,
        amount=Decimal(amount),
        every=every,
        unit=unit,
        **extra,
    )


def category(id_, name, position) -> CashFlowCategory:
    return CashFlowCategory(id=id_, workspace_id=WS, name=name, position=position)


# A month of: 3000 income; Housing 1200 (position 1), Food 434.52 (100 a
# week, position 0), 150 uncategorized; 1215.48 left over.
CATEGORIES = [category(1, "Housing", 1), category(2, "Food", 0)]
FLOWS = [
    flow("Salary", "3000", direction=INCOME),
    flow("Rent", "1200", category_id=1),
    flow("Groceries", "100", 1, WEEK, category_id=2, is_estimate=True),
    flow("Insurance", "1800", 1, YEAR),
]


def slices(view):
    return [(s["label"], s["amount"], s["share"]) for s in view["slices"]]


# --- formatting -------------------------------------------------------------


@pytest.mark.parametrize(
    ("amount", "kwargs", "text"),
    [
        ("1234.5", {}, "$1,234.50"),
        ("-1234.5", {}, "−$1,234.50"),
        ("0", {"sign": True}, "$0.00"),
        ("6853.33", {"sign": True}, "+$6,853.33"),
        ("-12", {"sign": True}, "−$12.00"),
        ("82239.5", {"cents": False}, "$82,240"),
        ("-0.4", {"cents": False}, "$0"),
    ],
)
def test_money(amount, kwargs, text):
    assert money(Decimal(amount), **kwargs) == text


def _groups(*yearlies):
    return [CategoryTotal(None, (), Decimal(y)) for y in yearlies]


def test_expense_colors_go_by_size_largest_strongest():
    # Order is position order; the largest (most negative) gets the ramp's top.
    colors = expense_colors(_groups(-10, -300, -20, -200))
    assert colors == [
        EXPENSE_RAMP[3],
        EXPENSE_RAMP[0],
        EXPENSE_RAMP[2],
        EXPENSE_RAMP[1],
    ]


def test_expense_colors_past_four_share_the_palest():
    colors = expense_colors(_groups(-1, -600, -500, -400, -300, -2))
    assert colors == [
        EXPENSE_RAMP[3],
        EXPENSE_RAMP[0],
        EXPENSE_RAMP[1],
        EXPENSE_RAMP[2],
        EXPENSE_RAMP[3],
        EXPENSE_RAMP[3],
    ]
    assert all(c.startswith("var(--liability") for c in colors)


def test_expense_colors_break_ties_by_order():
    assert expense_colors(_groups(-5, -5)) == [EXPENSE_RAMP[0], EXPENSE_RAMP[1]]


# --- view model --------------------------------------------------------------


def test_view_month():
    view = cash_flows_view(FLOWS, CATEGORIES, Period.MONTH)
    assert view["empty"] is False
    assert view["net"] == "+$1,215.48"
    assert view["income"] == "$3,000.00"
    assert view["other"] == "$14,586 a year"
    assert view["estimates"] == 1
    assert view["expenses"] == "$1,784.52"
    assert view["expenses_share"] == "59%"
    assert view["bar_state"] == "normal"
    assert view["over_by"] is None
    # Food (position 0), Housing (1), Uncategorized, then Left over.
    assert slices(view) == [
        ("Food", "$434.52", "14%"),
        ("Housing", "$1,200.00", "40%"),
        ("Uncategorized", "$150.00", "5%"),
        ("Left over", "$1,215.48", "41%"),
    ]
    assert [c["name"] for c in view["cards"]] == [
        "Income",
        "Food",
        "Housing",
        "Uncategorized",
    ]
    income, food, housing, other = view["cards"]
    assert (income["total"], income["note"]) == ("$3,000.00", "All income")
    assert income["color"] == "var(--asset)"
    assert (food["total"], food["note"]) == ("$434.52", "14% of income")
    assert food["rows"] == [
        {
            "id": None,  # not saved: the page links rows by id
            "name": "Groceries",
            "estimate": True,
            "amount": "$100.00",
            "every": "every week",
            "value": "$434.52",
        }
    ]
    assert other["rows"][0]["every"] == "every year"
    # Each card's + Add starts a flow in that card.
    assert [c["add_query"] for c in view["cards"]] == [
        "direction=income",
        "direction=expense&category_id=2",
        "direction=expense&category_id=1",
        "direction=expense",
    ]
    # Largest strongest: Housing, then Food, then Uncategorized.
    assert [food["color"], housing["color"], other["color"]] == [
        "var(--liability-2)",
        "var(--liability)",
        "var(--liability-3)",
    ]
    # The drawers look the colors up by category id (None: Uncategorized).
    assert view["colors"] == {
        2: "var(--liability-2)",
        1: "var(--liability)",
        None: "var(--liability-3)",
    }
    assert [s["color"] for s in view["slices"]] == [
        "var(--liability-2)",
        "var(--liability)",
        "var(--liability-3)",
        "var(--leftover)",
    ]


def test_slice_weights_are_unrounded_shares_of_income():
    view = cash_flows_view(FLOWS, CATEGORIES, Period.MONTH)
    weights = [Decimal(s["weight"]) for s in view["slices"]]
    # Groceries: 100 × 365/7 a year of 36,000 income = 14.4841…%
    assert weights[0] == Decimal("14.4841")
    assert sum(weights) == pytest.approx(Decimal(100), abs=Decimal("0.001"))


@pytest.mark.parametrize(
    ("period", "net", "other", "food"),
    [
        (Period.DAY, "+$39.96", "$14,586 a year", "$14.29"),
        (Period.MONTH, "+$1,215.48", "$14,586 a year", "$434.52"),
        (Period.YEAR, "+$14,585.71", "$1,215 a month", "$5,214.29"),
    ],
)
def test_view_each_period(period, net, other, food):
    view = cash_flows_view(FLOWS, CATEGORIES, period)
    assert view["period"] == period.value
    assert (view["net"], view["other"]) == (net, other)
    assert view["cards"][1]["total"] == food
    assert view["cards"][1]["rows"][0]["value"] == food


def test_view_no_income():
    flows = [flow("Rent", "1000")]
    view = cash_flows_view(flows, [], Period.MONTH)
    assert view["bar_state"] == "no_income"
    assert view["slices"] == []
    assert view["expenses_share"] is None
    assert view["net"] == "−$1,000.00"
    income, rent = view["cards"]
    assert (income["total"], income["rows"]) == ("$0.00", [])
    assert rent["note"] == "No income to compare"


def test_view_zero_income_flow_counts_as_no_income():
    flows = [flow("Paused job", "0", direction=INCOME), flow("Rent", "10")]
    assert cash_flows_view(flows, [], Period.MONTH)["bar_state"] == "no_income"


def test_view_expenses_above_income():
    flows = [
        flow("Pay", "1000", direction=INCOME),
        flow("Rent", "900", category_id=1),
        flow("Food", "300"),
    ]
    view = cash_flows_view(flows, [category(1, "Housing", 0)], Period.MONTH)
    assert view["bar_state"] == "over"
    assert view["over_by"] == "$200.00"
    assert view["net"] == "−$200.00"
    # 100% of the bar is expenses: no Left over, weights scaled to expenses.
    assert slices(view) == [
        ("Housing", "$900.00", "90%"),
        ("Uncategorized", "$300.00", "30%"),
    ]
    assert [s["weight"] for s in view["slices"]] == ["75.0000", "25.0000"]


# Board AA's sample month: 4,200 income; 2,650 + 1,500 + 812.50 out.
OVER_CATEGORIES = [
    category(1, "Housing", 0),
    category(2, "Childcare", 1),
    category(3, "Food", 2),
]
OVER = [
    flow("Part-time job", "4200", direction=INCOME),
    flow("Rent", "2400", category_id=1),
    flow("Utilities", "250", category_id=1),
    flow("Daycare", "1500", category_id=2),
    flow("Groceries", "812.50", category_id=3),
]


@pytest.mark.parametrize(
    ("period", "headline", "net", "over_by", "other"),
    [
        (Period.DAY, "Short each day", "−$25.07", "$25.07", "−$9,150 a year"),
        (Period.MONTH, "Short each month", "−$762.50", "$762.50", "−$9,150 a year"),
        (Period.YEAR, "Short each year", "−$9,150.00", "$9,150.00", "−$763 a month"),
    ],
)
def test_view_over_income_each_period(period, headline, net, over_by, other):
    view = cash_flows_view(OVER, OVER_CATEGORIES, period)
    assert view["bar_state"] == "over"
    assert view["headline"] == headline
    assert (view["net"], view["over_by"], view["other"]) == (net, over_by, other)
    # The share of income it is over by, display-rounded: 762.50 / 4,200.
    assert view["over_share"] == "18%"


def test_view_over_income_marker_is_income_on_the_expense_scale():
    view = cash_flows_view(OVER, OVER_CATEGORIES, Period.MONTH)
    # 4,200 / 4,962.50 = 84.6347…%, unrounded to the bar's precision.
    assert view["marker"] == "84.6348"
    assert view["expenses"] == "$4,962.50"
    assert view["income"] == "$4,200.00"
    assert [s["weight"] for s in view["slices"]] == ["53.4005", "30.2267", "16.3728"]
    # Cards keep "of income", so they can add past 100%.
    assert [c["note"] for c in view["cards"]] == [
        "All income",
        "63% of income",
        "36% of income",
        "19% of income",
    ]


def test_view_over_income_by_a_hair():
    flows = [flow("Pay", "3000", direction=INCOME), flow("Rent", "3001")]
    view = cash_flows_view(flows, [], Period.MONTH)
    assert view["over_by"] == "$1.00"
    assert view["over_share"] == "<1%"
    assert view["marker"] == "99.9667"


def test_view_not_over_has_no_marker():
    view = cash_flows_view(FLOWS, CATEGORIES, Period.DAY)
    assert view["headline"] == "Left over each day"
    assert (view["marker"], view["over_share"], view["over_by"]) == (None, None, None)
    no_income = cash_flows_view([flow("Rent", "10")], [], Period.MONTH)
    assert no_income["headline"] == "Left over each month"
    assert (no_income["marker"], no_income["over_share"]) == (None, None)


def test_view_expenses_equal_to_income_has_no_left_over_slice():
    flows = [flow("Pay", "100", direction=INCOME), flow("Rent", "100")]
    view = cash_flows_view(flows, [], Period.MONTH)
    assert view["bar_state"] == "normal"
    assert [s["label"] for s in view["slices"]] == ["Uncategorized"]
    assert view["net"] == "$0.00"


def test_view_leaves_out_categories_without_expenses():
    flows = [
        flow("Pay", "100", direction=INCOME, category_id=1),
        flow("Rent", "10", category_id=3),
    ]
    categories = [
        category(1, "Work", 0),
        category(2, "Unused", 1),
        category(3, "Home", 2),
    ]
    view = cash_flows_view(flows, categories, Period.MONTH)
    assert [c["name"] for c in view["cards"]] == ["Income", "Home"]
    assert [s["label"] for s in view["slices"]] == ["Home", "Left over"]


def test_view_skips_zero_slices_but_keeps_their_card():
    flows = [flow("Pay", "100", direction=INCOME), flow("Free trial", "0")]
    view = cash_flows_view(flows, [], Period.MONTH)
    assert [s["label"] for s in view["slices"]] == ["Left over"]
    assert [c["name"] for c in view["cards"]] == ["Income", "Uncategorized"]


def test_view_empty():
    view = cash_flows_view([], [category(1, "Housing", 0)], Period.MONTH)
    assert view["empty"] is True


def test_view_estimates_count_income_and_expenses():
    flows = [
        flow("Pay", "100", direction=INCOME, is_estimate=True),
        flow("Food", "10", is_estimate=True),
        flow("Rent", "10"),
    ]
    assert cash_flows_view(flows, [], Period.MONTH)["estimates"] == 2


# --- the page ----------------------------------------------------------------


def _seed(conn, workspace_id=WS):
    housing = create_flow_category(conn, workspace_id, "Housing")
    for f in [
        flow("Salary", "5100", 2, WEEK, INCOME),
        flow("Mortgage", "2450", category_id=housing.id),
        flow("Car insurance", "1140", 6, MONTH, is_estimate=True),
    ]:
        create_cash_flow(conn, workspace_id, f)


def _text(html: str) -> str:
    """The page's visible text, whitespace collapsed."""
    body = re.sub(r"<style.*?</style>|<script.*?</script>", "", html, flags=re.S)
    return " ".join(re.sub(r"<[^>]+>", " ", body).split())


@pytest.mark.db
class TestCashFlowsPage:
    def test_renders_with_data(self, client, db_connection):
        _seed(db_connection)
        login(client)
        response = client.get(PAGE)
        assert response.status_code == 200
        text = _text(response.text)
        assert "Left over each month" in text
        # 5100 × 365/14 / 12 = 11,080.36 income; 2450 + 190 out.
        assert "+$8,440.36" in text
        assert "of $11,080.36 income · $101,284 a year · ≈ 1 estimate " in text
        assert "Expenses $2,640.00 · 24%" in text
        assert "Housing $2,450.00 22%" in text
        assert "Uncategorized $190.00 2%" in text
        assert "Left over $8,440.36 76%" in text
        assert "Salary $5,100.00 every 2 weeks $11,080.36" in text
        assert "Car insurance ≈ $1,140.00 every 6 months $190.00" in text
        assert "All income" in text and "22% of income" in text
        # Cards in order: Income, Housing, Uncategorized.
        assert text.index("Salary") < text.index("Mortgage")
        assert text.index("Mortgage") < text.index("Car insurance")

    def test_nav_marks_cash_flows_current(self, client, db_connection):
        login(client)
        # The tab icons (phones only) aside.
        icons = re.compile(r'<svg class="tab-icon".*?</svg>', re.S)
        html = icons.sub("", client.get(PAGE).text)
        assert f'<a href="{PAGE}" aria-current="page">Cash flows</a>' in html
        assert f'<a href="{PAGES}/accounts">Accounts</a>' in html
        accounts = icons.sub("", client.get(f"{PAGES}/accounts").text)
        assert f'<a href="{PAGE}">Cash flows</a>' in accounts

    @pytest.mark.parametrize(
        ("query", "label", "net", "current"),
        [
            ("?per=day", "Left over each day", "+$277.49", "Day"),
            ("?per=month", "Left over each month", "+$8,440.36", "Month"),
            ("?per=year", "Left over each year", "+$101,284.29", "Year"),
            ("", "Left over each month", "+$8,440.36", "Month"),
            ("?per=fortnight", "Left over each month", "+$8,440.36", "Month"),
            ("?per=", "Left over each month", "+$8,440.36", "Month"),
        ],
    )
    def test_each_period(self, client, db_connection, query, label, net, current):
        _seed(db_connection)
        login(client)
        response = client.get(PAGE + query)
        assert response.status_code == 200
        text = _text(response.text)
        assert f"{label} {net}" in text
        html = response.text
        assert re.findall(r'aria-current="true">(\w+)<', html) == [current]
        for period in ("day", "month", "year"):
            assert f'href="{PAGE}?per={period}"' in html

    def test_year_shows_the_month_as_its_second_figure(self, client, db_connection):
        _seed(db_connection)
        login(client)
        text = _text(client.get(f"{PAGE}?per=year").text)
        assert "$8,440 a month" in text
        assert "Mortgage $2,450.00 every month $29,400.00" in text

    def test_empty_state(self, client, db_connection):
        create_flow_category(db_connection, WS, "Housing")
        login(client)
        response = client.get(PAGE)
        assert response.status_code == 200
        assert "No cash flows yet" in response.text
        assert "Where income goes" not in response.text

    def test_no_income(self, client, db_connection):
        create_cash_flow(db_connection, WS, flow("Rent", "1400"))
        login(client)
        text = _text(client.get(PAGE).text)
        assert "No income yet. Add an income cash flow" in text
        assert "−$1,400.00" in text
        assert "No income to compare" in text
        assert "%" not in text.split("Where income goes")[1]

    def test_expenses_above_income(self, client, db_connection):
        create_cash_flow(db_connection, WS, flow("Job", "1500", direction=INCOME))
        create_cash_flow(db_connection, WS, flow("Rent", "1400"))
        create_cash_flow(db_connection, WS, flow("Food", "200", is_estimate=True))
        login(client)
        html = client.get(PAGE).text
        text = _text(html)
        assert "Short each month −$100.00" in text
        assert re.search(r'<span class="headline-figure short">−\$100\.00</span>', html)
        assert (
            "Expenses $1,600.00 vs income $1,500.00 · −$1,200 a year · ≈ 1 estimate "
            in text
        )
        assert "Expenses exceed income by $100.00 (7%)" in text
        assert "Left over" not in text
        # The marker sits at income's share of expenses: 1,500 / 1,600.
        assert html.count("--marker: 93.7500%") == 2
        assert "▲ Income runs out" in text
        assert "Past income $100.00" in text
        # The key gives amounts; shares of income are on the cards.
        assert "Uncategorized $1,600.00 Past income" in text
        assert "107% of income" in text

    def test_expenses_above_income_per_year(self, client, db_connection):
        create_cash_flow(db_connection, WS, flow("Job", "1500", direction=INCOME))
        create_cash_flow(db_connection, WS, flow("Rent", "1600"))
        login(client)
        text = _text(client.get(f"{PAGE}?per=year").text)
        assert "Short each year −$1,200.00" in text
        assert "· −$100 a month" in text
        assert "Expenses exceed income by $1,200.00 (7%)" in text
        assert "Past income $1,200.00" in text

    # The editing controls (row links, + Add, categories) are tested with
    # their drawers, in test_cash_flow_drawers.py.

    def test_another_workspaces_flows_never_appear(self, client, db_connection):
        other = create_workspace(db_connection, USER_ID, "Other")
        theirs = create_flow_category(db_connection, other.id, "Their Category")
        create_cash_flow(
            db_connection, other.id, flow("Their Pay", "9999", direction=INCOME)
        )
        create_cash_flow(
            db_connection, other.id, flow("Their Rent", "777", category_id=theirs.id)
        )
        create_cash_flow(db_connection, WS, flow("My Rent", "100"))
        login(client)
        text = client.get(PAGE).text
        for name in ("Their Pay", "Their Rent", "Their Category", "9,999", "777"):
            assert name not in text
        assert "My Rent" in text
        # And the other workspace's page shows only its own.
        theirs_text = client.get(f"/workspaces/{other.id}/cash-flows").text
        assert "Their Rent" in theirs_text and "My Rent" not in theirs_text

    def test_non_member_gets_404(self, client, db_connection):
        from tests.web_support import STRANGER, add_user, session_for

        _seed(db_connection)
        add_user(db_connection, STRANGER)
        session_for(client, STRANGER)
        response = client.get(PAGE, headers={"Accept": "application/json"})
        assert response.status_code == 404
        assert client.get("/workspaces/999/cash-flows").status_code == 404

    def test_viewer_can_read(self, client, db_connection):
        from tests.web_support import STRANGER, add_user, session_for

        _seed(db_connection)
        add_user(db_connection, STRANGER, role="viewer")
        session_for(client, STRANGER)
        response = client.get(PAGE)
        assert response.status_code == 200
        assert "Mortgage" in response.text

    def test_logged_out_redirects_to_login(self, client):
        response = client.get(PAGE, follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/login"

    def test_carries_both_themes(self, client, db_connection):
        _seed(db_connection)
        login(client)
        html = client.get(PAGE).text
        assert "color-scheme: light" in html and "color-scheme: dark" in html

    def test_database_error_shows_a_message(self, client, monkeypatch):
        import sensibility.web.cash_flows_routes as routes

        login(client)

        def broken(conn, workspace_id):
            raise RuntimeError("database down")

        monkeypatch.setattr(routes.repo, "get_cash_flows", broken)
        response = client.get(PAGE)
        assert response.status_code == 200
        assert "An error occurred while loading your data" in response.text
        assert "Where income goes" not in response.text
