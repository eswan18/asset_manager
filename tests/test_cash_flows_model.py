"""The Cash flows page's figures (web/cash_flows_model.py), as the JSON API
serves them (`api_cash_flows.cash_flows_overview`), worked by hand. The React
app only formats these (frontend/src/lib/cash-flows.ts, with its own tests).
"""

from decimal import Decimal

import pytest

from sensibility.cashflows import CategoryTotal, Period
from sensibility.models import (
    CashFlow,
    CashFlowCategory,
    CashFlowDirection,
    FrequencyUnit,
)
from sensibility.web.api_cash_flows import cash_flows_overview
from sensibility.web.cash_flows_model import EXPENSE_RAMP, expense_colors
from tests.support import WS

INCOME, EXPENSE = CashFlowDirection.INCOME, CashFlowDirection.EXPENSE
WEEK, MONTH, YEAR = FrequencyUnit.WEEK, FrequencyUnit.MONTH, FrequencyUnit.YEAR

_ids = iter(range(1, 10_000))


def flow(name, amount, every=1, unit=MONTH, direction=EXPENSE, **extra) -> CashFlow:
    return CashFlow(
        id=next(_ids),
        name=name,
        direction=direction,
        amount=Decimal(amount),
        every=every,
        unit=unit,
        **extra,
    )


def category(id_, name, position) -> CashFlowCategory:
    return CashFlowCategory(id=id_, workspace_id=WS, name=name, position=position)


def overview(flows, categories=(), period=Period.MONTH):
    return cash_flows_overview(list(flows), list(categories), period, can_edit=True)


def slices(o):
    return [(s.label, s.amount, s.share) for s in o.slices]


# A month of: 3000 income; Housing 1200 (position 1), Food 434.52 (100 a
# week, position 0), 150 uncategorized; 1215.48 left over.
CATEGORIES = [category(1, "Housing", 1), category(2, "Food", 0)]
FLOWS = [
    flow("Salary", "3000", direction=INCOME),
    flow("Rent", "1200", category_id=1),
    flow("Groceries", "100", 1, WEEK, category_id=2, is_estimate=True),
    flow("Insurance", "1800", 1, YEAR),
]


# --- expense colors ------------------------------------------------------------


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


# --- the figures -----------------------------------------------------------------


def test_a_month():
    o = overview(FLOWS, CATEGORIES)
    assert o.empty is False
    assert o.short is False
    assert (o.net, o.income, o.expenses) == ("1215.48", "3000.00", "1784.52")
    assert (o.other_period, o.other_net) == (Period.YEAR, "14585.71")
    assert (o.estimates, o.expenses_share, o.bar_state.value) == (1, "59%", "normal")
    assert (o.over_by, o.over_share, o.marker) == (None, None, None)
    # Food (position 0), Housing (1), Uncategorized, then Left over.
    assert slices(o) == [
        ("Food", "434.52", "14%"),
        ("Housing", "1200.00", "40%"),
        ("Uncategorized", "150.00", "5%"),
        ("Left over", "1215.48", "41%"),
    ]
    assert [(c.name, c.total, c.share) for c in o.cards] == [
        ("Income", "3000.00", None),
        ("Food", "434.52", "14%"),
        ("Housing", "1200.00", "40%"),
        ("Uncategorized", "150.00", "5%"),
    ]
    groceries = o.cards[1].flows[0]
    assert (groceries.name, groceries.is_estimate, groceries.amount) == (
        "Groceries",
        True,
        "100.00",
    )
    assert (groceries.every_text, groceries.per_period) == ("every week", "434.52")
    assert o.cards[3].flows[0].every_text == "every year"
    # Largest strongest: Housing, then Food, then Uncategorized.
    assert [c.color for c in o.cards] == [
        "var(--asset)",
        "var(--liability-2)",
        "var(--liability)",
        "var(--liability-3)",
    ]
    assert [s.color for s in o.slices] == [
        "var(--liability-2)",
        "var(--liability)",
        "var(--liability-3)",
        "var(--leftover)",
    ]
    # The drawers' colors, by category (and for Uncategorized).
    assert {c.id: c.expense_color for c in o.categories} == {
        2: "var(--liability-2)",
        1: "var(--liability)",
    }
    assert o.uncategorized_color == "var(--liability-3)"


def test_slice_weights_are_unrounded_shares_of_income():
    weights = [Decimal(s.weight) for s in overview(FLOWS, CATEGORIES).slices]
    # Groceries: 100 × 365/7 a year of 36,000 income = 14.4841…%
    assert weights[0] == Decimal("14.4841")
    assert sum(weights) == pytest.approx(Decimal(100), abs=Decimal("0.001"))


@pytest.mark.parametrize(
    ("period", "net", "other", "food"),
    [
        (Period.DAY, "39.96", (Period.YEAR, "14585.71"), "14.29"),
        (Period.MONTH, "1215.48", (Period.YEAR, "14585.71"), "434.52"),
        (Period.YEAR, "14585.71", (Period.MONTH, "1215.48"), "5214.29"),
    ],
)
def test_each_period(period, net, other, food):
    o = overview(FLOWS, CATEGORIES, period)
    assert o.period == period
    assert (o.net, (o.other_period, o.other_net)) == (net, other)
    assert o.cards[1].total == food
    assert o.cards[1].flows[0].per_period == food


def test_no_income():
    o = overview([flow("Rent", "1000")])
    assert (o.bar_state.value, o.slices, o.expenses_share) == ("no_income", [], None)
    assert o.net == "-1000.00"
    income, rent = o.cards
    assert (income.total, income.flows) == ("0.00", [])
    assert rent.share is None  # "No income to compare"


def test_a_zero_income_flow_counts_as_no_income():
    flows = [flow("Paused job", "0", direction=INCOME), flow("Rent", "10")]
    o = overview(flows)
    assert (o.bar_state.value, o.slices) == ("no_income", [])


def test_expenses_above_income():
    flows = [
        flow("Pay", "1000", direction=INCOME),
        flow("Rent", "900", category_id=1),
        flow("Food", "300"),
    ]
    o = overview(flows, [category(1, "Housing", 0)])
    assert (o.bar_state.value, o.short) == ("over", True)
    assert (o.over_by, o.net) == ("200.00", "-200.00")
    # 100% of the bar is expenses: no Left over, weights scaled to expenses.
    assert slices(o) == [
        ("Housing", "900.00", "90%"),
        ("Uncategorized", "300.00", "30%"),
    ]
    assert [s.weight for s in o.slices] == ["75.0000", "25.0000"]


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
    ("period", "net", "over_by", "other"),
    [
        (Period.DAY, "-25.07", "25.07", (Period.YEAR, "-9150.00")),
        (Period.MONTH, "-762.50", "762.50", (Period.YEAR, "-9150.00")),
        (Period.YEAR, "-9150.00", "9150.00", (Period.MONTH, "-762.50")),
    ],
)
def test_over_income_each_period(period, net, over_by, other):
    o = overview(OVER, OVER_CATEGORIES, period)
    assert (o.bar_state.value, o.short) == ("over", True)  # "Short each …"
    assert (o.net, o.over_by, (o.other_period, o.other_net)) == (net, over_by, other)
    # The share of income it is over by, display-rounded: 762.50 / 4,200.
    assert o.over_share == "18%"


def test_the_over_income_marker_is_income_on_the_expense_scale():
    o = overview(OVER, OVER_CATEGORIES)
    # 4,200 / 4,962.50 = 84.6347…%, unrounded to the bar's precision.
    assert o.marker == "84.6348"
    assert (o.expenses, o.income) == ("4962.50", "4200.00")
    assert [s.weight for s in o.slices] == ["53.4005", "30.2267", "16.3728"]
    # Cards keep "of income", so they can add past 100%.
    assert [c.share for c in o.cards] == [None, "63%", "36%", "19%"]


def test_over_income_by_a_hair():
    o = overview([flow("Pay", "3000", direction=INCOME), flow("Rent", "3001")])
    assert (o.over_by, o.over_share, o.marker) == ("1.00", "<1%", "99.9667")


def test_not_over_has_no_marker():
    o = overview(FLOWS, CATEGORIES, Period.DAY)
    assert o.short is False  # "Left over each day"
    assert (o.marker, o.over_share, o.over_by) == (None, None, None)
    no_income = overview([flow("Rent", "10")])
    assert no_income.short is False
    assert (no_income.marker, no_income.over_share) == (None, None)


def test_expenses_equal_to_income_have_no_left_over_slice():
    o = overview([flow("Pay", "100", direction=INCOME), flow("Rent", "100")])
    assert (o.bar_state.value, o.short, o.net) == ("normal", False, "0.00")
    assert [s.label for s in o.slices] == ["Uncategorized"]


def test_categories_without_expenses_get_no_card_or_slice():
    flows = [
        flow("Pay", "100", direction=INCOME, category_id=1),
        flow("Rent", "10", category_id=3),
    ]
    categories = [
        category(1, "Work", 0),
        category(2, "Unused", 1),
        category(3, "Home", 2),
    ]
    o = overview(flows, categories)
    assert [c.name for c in o.cards] == ["Income", "Home"]
    assert [s.label for s in o.slices] == ["Home", "Left over"]
    # The categories drawer lists them all, colored by what they hold.
    assert [(c.name, c.color, c.flow_count) for c in o.categories] == [
        ("Work", "var(--asset)", 1),
        ("Unused", "var(--rule-strong)", 0),
        ("Home", "var(--liability)", 1),
    ]


def test_zero_slices_are_skipped_but_their_card_stays():
    o = overview([flow("Pay", "100", direction=INCOME), flow("Free trial", "0")])
    assert [s.label for s in o.slices] == ["Left over"]
    assert [c.name for c in o.cards] == ["Income", "Uncategorized"]


def test_empty():
    assert overview([], [category(1, "Housing", 0)]).empty is True


def test_estimates_count_income_and_expenses():
    flows = [
        flow("Pay", "100", direction=INCOME, is_estimate=True),
        flow("Food", "10", is_estimate=True),
        flow("Rent", "10"),
    ]
    assert overview(flows).estimates == 2
