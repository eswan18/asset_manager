"""The Cash flows page's JSON: the overview and moving a category.

The first tests check the overview against the service's math
(cashflows.py) for many shapes of data, with hand-worked figures in
test_cash_flows_model.py; the rest go through HTTP against the container.
"""

from decimal import Decimal

import pytest

from sensibility import repository as repo
from sensibility.cashflows import (
    Period,
    category_totals,
    create_cash_flow,
    create_category,
    in_period,
    totals,
)
from sensibility.models import (
    CashFlow,
    CashFlowCategory,
    CashFlowDirection,
    FrequencyUnit,
    Role,
)
from sensibility.web.api_cash_flows import CashFlowsOverview, cash_flows_overview
from sensibility.workspaces import create_workspace
from tests.support import WS
from tests.web_support import STRANGER, add_user, login, session_for

INCOME, EXPENSE = CashFlowDirection.INCOME, CashFlowDirection.EXPENSE
DAY, WEEK, MONTH, YEAR = (
    FrequencyUnit.DAY,
    FrequencyUnit.WEEK,
    FrequencyUnit.MONTH,
    FrequencyUnit.YEAR,
)
OVERVIEW = f"/api/workspaces/{WS}/cash-flows/overview"
CATEGORIES = f"/api/workspaces/{WS}/cash-flow-categories"
OTHER_WS = 2

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


# Housing (position 1), Food (0), Travel (2, income only), Empty (3).
CATS = [
    category(1, "Housing", 1),
    category(2, "Food", 0),
    category(3, "Travel", 2),
    category(4, "Empty", 3),
]
NORMAL = [
    flow("Salary", "3000", direction=INCOME),
    flow("Rent", "1200", category_id=1),
    flow("Groceries", "100", 1, WEEK, category_id=2, is_estimate=True),
    flow("Insurance", "1800", 1, YEAR),
    flow("Refund", "50", 1, YEAR, direction=INCOME, category_id=3),
]
NO_INCOME = [flow("Rent", "1200", category_id=1), flow("Coffee", "4.5", 1, DAY)]
ZERO_INCOME = [flow("Nothing", "0", direction=INCOME), flow("Rent", "10")]
OVER = [
    flow("Salary", "1000", direction=INCOME, is_estimate=True),
    flow("Rent", "1200", category_id=1),
    flow("Food", "300", 2, WEEK, category_id=2),
]
EQUAL = [flow("Salary", "100", direction=INCOME), flow("Rent", "100", category_id=1)]
# More expense categories than the ramp has steps, and a zero expense.
MANY_CATS = [category(i, f"C{i}", i) for i in range(1, 7)]
MANY = [flow("Pay", "10000", direction=INCOME)] + [
    flow(f"F{i}", str(i * 100), category_id=i) for i in range(1, 7)
]
MANY.append(flow("Free", "0", category_id=1))
DATASETS = {
    "normal": (NORMAL, CATS),
    "no_income": (NO_INCOME, CATS),
    "zero_income": (ZERO_INCOME, CATS),
    "over": (OVER, CATS),
    "equal": (EQUAL, CATS),
    "many": (MANY, MANY_CATS),
    "empty": ([], CATS),
    "no_categories": ([flow("Pay", "500", direction=INCOME), flow("X", "1")], []),
}


def cents(amount: Decimal) -> str:
    return str(abs(amount).quantize(Decimal("0.01")))


# --- the overview follows the service's math -------------------------------------
# Hand-worked figures are in test_cash_flows_model.py; these hold for every
# shape of data and every period.


@pytest.mark.parametrize("period", list(Period))
@pytest.mark.parametrize("name", list(DATASETS))
def test_totals_and_cards_are_the_services(name, period):
    flows, cats = DATASETS[name]
    o = cash_flows_overview(flows, cats, period, can_edit=True)
    sums = totals(flows)

    assert o.income == cents(Decimal(sums["income"][f"per_{period.value}"]))
    assert o.expenses == cents(Decimal(sums["expenses"][f"per_{period.value}"]))
    assert Decimal(o.net) == Decimal(sums["net"][f"per_{period.value}"])
    groups = [g for g in category_totals(flows, cats) if g.flows]
    assert [(c.name, c.total) for c in o.cards[1:]] == [
        (g.name, cents(in_period(g.yearly, period))) for g in groups
    ]
    assert [c.flow_count for c in o.categories] == [
        sum(1 for f in flows if f.category_id == c.id) for c in cats_in_order(cats)
    ]


@pytest.mark.parametrize("period", list(Period))
@pytest.mark.parametrize("name", list(DATASETS))
def test_colors_agree_between_the_page_and_the_drawers(name, period):
    flows, cats = DATASETS[name]
    o = cash_flows_overview(flows, cats, period, can_edit=True)
    card_colors = {c.category_id: c.color for c in o.cards[1:]}

    for c in o.categories:
        # An expense put in it takes its card's color, else the ramp's first.
        assert c.expense_color == card_colors.get(c.id, "var(--liability)")
        holds_income = any(
            f.category_id == c.id and f.direction == INCOME for f in flows
        )
        assert c.color == card_colors.get(
            c.id, "var(--asset)" if holds_income else "var(--rule-strong)"
        )
    assert o.uncategorized_color == card_colors.get(None, "var(--liability)")
    for s in o.slices:
        expected = "var(--leftover)" if s.left_over else card_colors[s.category_id]
        assert s.color == expected
    if o.bar_state.value != "no_income" and o.slices:
        assert sum(Decimal(s.weight) for s in o.slices) == pytest.approx(
            Decimal(100), abs=Decimal("0.001")
        )
    if o.bar_state.value == "over":
        assert o.over_by == o.net.removeprefix("-")


def cats_in_order(cats):
    return sorted(cats, key=lambda c: (c.position, c.id))


def test_normal_month_in_detail():
    o = cash_flows_overview(NORMAL, CATS, Period.MONTH, can_edit=True)
    # 3004.17 income (with the 50/yr refund); Food 434.52, Housing 1200,
    # Uncategorized 150. The net is rounded once from the unrounded sums,
    # so it is not 3004.17 - 1784.52.
    assert (o.income, o.expenses, o.net) == ("3004.17", "1784.52", "1219.64")
    assert (o.other_period, o.other_net) == (Period.YEAR, "14635.71")
    assert (o.short, o.bar_state.value, o.estimates) == (False, "normal", 1)
    assert [(s.label, s.category_id, s.left_over) for s in o.slices] == [
        ("Food", 2, False),
        ("Housing", 1, False),
        ("Uncategorized", None, False),
        ("Left over", None, True),
    ]
    assert [(c.direction.value, c.category_id, c.name) for c in o.cards] == [
        ("income", None, "Income"),
        ("expense", 2, "Food"),
        ("expense", 1, "Housing"),
        ("expense", None, "Uncategorized"),
    ]
    groceries = o.cards[1].flows[0]
    assert groceries.model_dump(mode="json") | {"id": 0} == {
        "id": 0,
        "name": "Groceries",
        "direction": "expense",
        "amount": "100.00",
        "every": 1,
        "unit": "week",
        "every_text": "every week",
        "per_period": "434.52",
        "category_id": 2,
        "description": None,
        "is_estimate": True,
    }
    # Travel holds only income: blue in the categories drawer, but an
    # expense put there gets the ramp's first color. Empty has no color.
    travel, empty = o.categories[2], o.categories[3]
    assert (travel.color, travel.expense_color) == ("var(--asset)", "var(--liability)")
    assert (travel.expenses, travel.income, travel.flow_count) == (None, "4.17", 1)
    assert (empty.color, empty.flow_count) == ("var(--rule-strong)", 0)
    assert [c.name for c in o.categories] == ["Food", "Housing", "Travel", "Empty"]


def test_over_income():
    o = cash_flows_overview(OVER, CATS, Period.MONTH, can_edit=True)
    assert o.short and o.bar_state.value == "over"
    assert o.net.startswith("-")
    assert o.over_by == o.net.removeprefix("-")
    assert o.over_share is not None and o.marker is not None
    assert not any(s.left_over for s in o.slices)


def test_no_income_has_no_bar_but_says_how_far_over():
    o = cash_flows_overview(NO_INCOME, CATS, Period.MONTH, can_edit=True)
    assert (o.bar_state.value, o.slices, o.short) == ("no_income", [], False)
    assert (o.income, o.expenses_share, o.marker) == ("0.00", None, None)
    assert o.over_by == o.expenses
    assert all(c.share is None for c in o.cards)


def test_empty_never_says_minus_zero():
    o = cash_flows_overview([], CATS, Period.DAY, can_edit=False)
    assert o.empty and not o.can_edit
    assert (o.net, o.income, o.expenses, o.other_net) == ("0.00",) * 4
    assert [c.name for c in o.cards] == ["Income"]
    assert o.cards[0].total == "0.00"


# --- over HTTP ------------------------------------------------------------------


@pytest.fixture
def seeded(db_connection):
    """Food (position 0) and Housing (1), and NORMAL's flows without the
    refund, in the seeded workspace."""
    food = create_category(db_connection, WS, "Food")
    housing = create_category(db_connection, WS, "Housing")
    for f in (
        flow("Salary", "3000", direction=INCOME),
        flow("Rent", "1200", category_id=housing.id),
        flow("Groceries", "100", 1, WEEK, category_id=food.id, is_estimate=True),
        flow("Insurance", "1800", 1, YEAR),
    ):
        create_cash_flow(db_connection, WS, f.model_copy(update={"id": None}))
    return food, housing


@pytest.mark.db
class TestOverviewEndpoint:
    def test_serves_the_overview_for_each_period(self, client, db_connection, seeded):
        login(client)
        flows = repo.get_cash_flows(db_connection, WS)
        cats = repo.get_cash_flow_categories(db_connection, WS)
        for period in Period:
            response = client.get(OVERVIEW, params={"per": period.value})
            assert response.status_code == 200
            body = CashFlowsOverview.model_validate(response.json())
            assert body.period == period and body.can_edit is True
            assert response.json() == cash_flows_overview(
                flows, cats, period, can_edit=True
            ).model_dump(mode="json")
        # And by hand: test_cash_flows_model.py's figures, from the database.
        day = client.get(OVERVIEW, params={"per": "day"}).json()
        year = client.get(OVERVIEW, params={"per": "year"}).json()
        assert (day["net"], year["net"]) == ("39.96", "14585.71")

    def test_month_figures(self, client, seeded):
        login(client)
        body = client.get(OVERVIEW).json()
        assert body["period"] == "month"
        assert (body["net"], body["income"], body["expenses"]) == (
            "1215.48",
            "3000.00",
            "1784.52",
        )
        assert body["expenses_share"] == "59%"
        assert [(s["label"], s["amount"], s["share"]) for s in body["slices"]] == [
            ("Food", "434.52", "14%"),
            ("Housing", "1200.00", "40%"),
            ("Uncategorized", "150.00", "5%"),
            ("Left over", "1215.48", "41%"),
        ]
        assert body["over_by"] is None and body["marker"] is None

    def test_an_unknown_period_is_month_as_on_the_page(self, client, seeded):
        login(client)
        assert client.get(OVERVIEW, params={"per": "fortnight"}).json()["period"] == (
            "month"
        )

    def test_a_viewer_reads_but_cannot_edit(self, client, db_connection, seeded):
        add_user(db_connection, STRANGER, "viewer")
        session_for(client, STRANGER)
        response = client.get(OVERVIEW)
        assert response.status_code == 200
        assert response.json()["can_edit"] is False

    def test_an_editor_can_edit(self, client, db_connection, seeded):
        add_user(db_connection, STRANGER, "editor")
        session_for(client, STRANGER)
        assert client.get(OVERVIEW).json()["can_edit"] is True

    def test_another_workspace_is_404_and_its_flows_never_appear(
        self, client, db_connection, seeded
    ):
        add_user(db_connection, STRANGER)
        create_workspace(db_connection, STRANGER["id"], "Theirs")
        create_cash_flow(
            db_connection, OTHER_WS, flow("Theirs", "5").model_copy(update={"id": None})
        )
        session_for(client, STRANGER)

        assert client.get(OVERVIEW).status_code == 404
        theirs = client.get(f"/api/workspaces/{OTHER_WS}/cash-flows/overview").json()
        names = [f["name"] for c in theirs["cards"] for f in c["flows"]]
        assert names == ["Theirs"]
        assert theirs["categories"] == []

    def test_logged_out_is_401(self, client):
        assert client.get(OVERVIEW).status_code == 401


# --- moving a category ----------------------------------------------------------


def move(client, category_id, direction, workspace_id=WS):
    return client.post(
        f"/api/workspaces/{workspace_id}/cash-flow-categories/{category_id}/move",
        json={"direction": direction},
    )


@pytest.fixture
def three(db_connection):
    return [create_category(db_connection, WS, name) for name in ("A", "B", "C")]


def order(response) -> list[tuple[str, int]]:
    return [(c["name"], c["position"]) for c in response.json()["categories"]]


@pytest.mark.db
class TestMoveCategory:
    def test_up_and_down_swap_with_the_neighbour(self, client, three):
        login(client)
        a, b, c = three

        up = move(client, b.id, "up")
        assert up.status_code == 200
        assert order(up) == [("B", 0), ("A", 1), ("C", 2)]

        down = move(client, b.id, "down")
        assert order(down) == [("A", 0), ("B", 1), ("C", 2)]
        # The list endpoint agrees.
        listed = client.get(CATEGORIES).json()["categories"]
        assert [x["name"] for x in listed] == ["A", "B", "C"]

    def test_the_first_up_and_the_last_down_change_nothing(self, client, three):
        login(client)
        a, _, c = three
        assert order(move(client, a.id, "up")) == [("A", 0), ("B", 1), ("C", 2)]
        assert order(move(client, c.id, "down")) == [("A", 0), ("B", 1), ("C", 2)]

    def test_tied_positions_come_out_renumbered(self, client, db_connection, three):
        db_connection.execute("UPDATE cash_flow_categories SET position = 5")
        db_connection.commit()
        login(client)
        a, b, _ = three
        assert order(move(client, b.id, "up")) == [("B", 0), ("A", 1), ("C", 2)]

    def test_a_bad_direction_is_422(self, client, three):
        login(client)
        assert move(client, three[0].id, "sideways").status_code == 422
        assert client.post(f"{CATEGORIES}/{three[0].id}/move", json={}).status_code == (
            422
        )

    def test_an_unknown_category_is_404(self, client, three):
        login(client)
        response = move(client, 999, "up")
        assert response.status_code == 404
        assert response.json() == {"error": "Category not found"}

    def test_another_workspaces_category_is_404_and_does_not_move(
        self, client, db_connection, three
    ):
        add_user(db_connection, STRANGER)
        create_workspace(db_connection, STRANGER["id"], "Theirs")
        theirs = [create_category(db_connection, OTHER_WS, name) for name in ("X", "Y")]
        session_for(client, STRANGER)

        # Their own workspace's path, our category id.
        assert move(client, three[1].id, "up", OTHER_WS).status_code == 404
        # Our workspace's path: not a member.
        assert move(client, theirs[1].id, "up").status_code == 404
        assert [c.name for c in repo.get_cash_flow_categories(db_connection, WS)] == [
            "A",
            "B",
            "C",
        ]
        assert [
            c.name for c in repo.get_cash_flow_categories(db_connection, OTHER_WS)
        ] == ["X", "Y"]

    def test_viewers_cannot_move_editors_can(self, client, db_connection, three):
        add_user(db_connection, STRANGER, "viewer")
        session_for(client, STRANGER)
        assert move(client, three[1].id, "up").status_code == 403
        assert [c.name for c in repo.get_cash_flow_categories(db_connection, WS)] == [
            "A",
            "B",
            "C",
        ]

        repo.set_member_role(db_connection, WS, STRANGER["id"], Role.EDITOR)
        db_connection.commit()
        assert order(move(client, three[1].id, "up"))[0] == ("B", 0)
