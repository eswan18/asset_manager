"""Cash flows: the rate math, the rules, and the database's guarantees."""

from decimal import Decimal

import psycopg
import pytest
from hypothesis import given
from hypothesis import strategies as st

from sensibility import repository as repo
from sensibility.cashflows import (
    DEFAULT_PERIOD,
    CashFlowError,
    Period,
    category_totals,
    create_cash_flow,
    create_category,
    delete_cash_flow,
    delete_category,
    every_text,
    in_period,
    move_category,
    parse_period,
    per_year,
    percent_text,
    rates,
    share,
    totals,
    update_cash_flow,
    update_category,
)
from sensibility.models import (
    CashFlow,
    CashFlowCategory,
    CashFlowDirection,
    FrequencyUnit,
)
from sensibility.workspaces import create_workspace
from tests.support import USER_ID, WS

INCOME, EXPENSE = CashFlowDirection.INCOME, CashFlowDirection.EXPENSE
DAY, WEEK, MONTH, YEAR = (
    FrequencyUnit.DAY,
    FrequencyUnit.WEEK,
    FrequencyUnit.MONTH,
    FrequencyUnit.YEAR,
)


def flow(amount, every, unit, direction=EXPENSE, name="X", **extra) -> CashFlow:
    return CashFlow(
        name=name,
        direction=direction,
        amount=Decimal(amount),
        every=every,
        unit=unit,
        **extra,
    )


# --- rates -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("row", "per_day"),
    [
        # Rows from the spreadsheet this replaces, with its Amt/Day column.
        (flow("5103.83", 2, WEEK, INCOME), "364.56"),  # take-home pay
        (flow("3820.00", 1, MONTH), "-125.59"),  # rent
        (flow("30.00", 2, MONTH), "-0.49"),  # gasoline
        (flow("300.00", 1, YEAR), "-0.82"),  # clothes
        (flow("200.00", 2, YEAR), "-0.27"),  # car maintenance
        (flow("5.00", 3, MONTH), "-0.05"),  # Pinecast
        (flow("13.00", 1, MONTH), "-0.43"),  # Spotify
        (flow("0.00", 1, MONTH), "0.00"),  # cell phone, bundled
    ],
)
def test_per_day_matches_the_spreadsheet(row, per_day):
    assert rates(per_year(row))["per_day"] == per_day


def test_each_unit():
    assert rates(per_year(flow("10", 1, DAY, INCOME))) == {
        "per_day": "10.00",
        "per_month": "304.17",
        "per_year": "3650.00",
    }
    assert rates(per_year(flow("70", 1, WEEK, INCOME)))["per_day"] == "10.00"
    assert rates(per_year(flow("100", 1, MONTH, INCOME)))["per_year"] == "1200.00"
    assert rates(per_year(flow("100", 4, YEAR, INCOME)))["per_year"] == "25.00"


amounts = st.decimals(min_value=0, max_value=10**9, places=2)


@given(amount=amounts, n=st.integers(min_value=1, max_value=50))
def test_equivalent_frequencies_agree(amount, n):
    def yearly(every, unit):
        return per_year(flow(amount, every, unit))

    assert yearly(12 * n, MONTH) == yearly(n, YEAR)
    assert yearly(7 * n, DAY) == yearly(n, WEEK)


@given(amount=amounts, every=st.integers(min_value=1, max_value=1000))
def test_direction_only_flips_the_sign(amount, every):
    assert per_year(flow(amount, every, MONTH, INCOME)) == -per_year(
        flow(amount, every, MONTH, EXPENSE)
    )


def test_totals_round_once_after_summing():
    # Three expenses of 0.004/day each: rounded one by one they'd vanish.
    tiny = [flow("1.46", 1, YEAR, name=str(i)) for i in range(3)]
    pay = flow("3650", 1, YEAR, INCOME, name="pay")
    result = totals([pay, *tiny])
    assert result["income"]["per_day"] == "10.00"
    assert result["expenses"]["per_day"] == "-0.01"
    assert result["net"]["per_year"] == "3645.62"
    assert totals([]) == {
        k: {"per_day": "0.00", "per_month": "0.00", "per_year": "0.00"}
        for k in ("income", "expenses", "net")
    }


# --- per category and per period --------------------------------------------


def category(id_, name, position=0) -> CashFlowCategory:
    return CashFlowCategory(id=id_, workspace_id=WS, name=name, position=position)


flows_strategy = st.lists(
    st.builds(
        flow,
        amount=amounts,
        every=st.integers(min_value=1, max_value=1000),
        unit=st.sampled_from(list(FrequencyUnit)),
        direction=st.sampled_from(list(CashFlowDirection)),
        # 1-3 exist below; 4 names a category that is not in the list.
        category_id=st.sampled_from([None, 1, 2, 3, 4]),
    ),
    max_size=30,
)
CATEGORIES = [category(1, "Housing", 2), category(2, "Food", 0), category(3, "Fun", 1)]


@given(flows=flows_strategy)
def test_category_totals_add_up_to_totals_exactly(flows):
    groups = category_totals(flows, CATEGORIES)
    # Unrounded, so the sum is exact and rounds to totals()'s figures.
    assert (
        rates(sum((g.yearly for g in groups), Decimal(0)))
        == (totals(flows)["expenses"])
    )
    # Every expense lands in exactly one group; no income does.
    grouped = [f for g in groups for f in g.flows]
    assert sorted(map(id, grouped)) == sorted(
        id(f) for f in flows if f.direction == EXPENSE
    )
    for g in groups:
        assert g.yearly == sum((per_year(f) for f in g.flows), Decimal(0))


def test_category_totals_round_once_per_category():
    # Three expenses of 0.004/day each: rounded one by one they'd vanish.
    tiny = [flow("1.46", 1, YEAR, name=str(i), category_id=1) for i in range(3)]
    [group] = category_totals(tiny, [category(1, "Tiny")])
    assert in_period(group.yearly, Period.DAY) == Decimal("-0.01")


def test_category_totals_follow_position_then_uncategorized():
    flows = [
        flow("1", 1, MONTH, name="a", category_id=1),
        flow("1", 1, MONTH, name="b", category_id=2),
        flow("1", 1, MONTH, name="c"),
    ]
    groups = category_totals(flows, CATEGORIES)
    # Food (0), Fun (1, no flows yet), Housing (2), then Uncategorized.
    assert [g.name for g in groups] == ["Food", "Fun", "Housing", "Uncategorized"]
    assert [g.category for g in groups][-1] is None
    assert [len(g.flows) for g in groups] == [1, 0, 1, 1]


def test_category_totals_break_position_ties_by_id():
    tied = [category(5, "Later", 0), category(2, "Earlier", 0)]
    assert [g.name for g in category_totals([], tied)] == ["Earlier", "Later"]


def test_uncategorized_collects_missing_and_unknown_categories_only():
    flows = [
        flow("10", 1, MONTH, name="none"),
        flow("20", 1, MONTH, name="unknown", category_id=99),
        flow("40", 1, MONTH, name="known", category_id=1),
        flow("80", 1, MONTH, INCOME, name="pay"),
        flow("160", 1, MONTH, INCOME, name="pay in a category", category_id=1),
    ]
    groups = category_totals(flows, [category(1, "Housing")])
    assert [(g.name, [f.name for f in g.flows]) for g in groups] == [
        ("Housing", ["known"]),
        ("Uncategorized", ["none", "unknown"]),
    ]
    assert [g.yearly for g in groups] == [Decimal(-480), Decimal(-360)]


def test_no_uncategorized_group_without_uncategorized_expenses():
    flows = [flow("1", 1, MONTH, INCOME, name="pay")]
    assert [g.name for g in category_totals(flows, CATEGORIES)] == [
        "Food",
        "Fun",
        "Housing",
    ]
    assert category_totals([], []) == []


@pytest.mark.parametrize(
    ("raw", "period"),
    [
        ("day", Period.DAY),
        ("month", Period.MONTH),
        ("year", Period.YEAR),
        (None, Period.MONTH),
        ("", Period.MONTH),
        ("week", Period.MONTH),
        ("Day", Period.MONTH),
        ("year ", Period.MONTH),
    ],
)
def test_parse_period_falls_back_to_month(raw, period):
    assert DEFAULT_PERIOD == Period.MONTH
    assert parse_period(raw) == period


def test_in_period_divides_then_rounds_once():
    yearly = Decimal("1000")
    assert in_period(yearly, Period.YEAR) == Decimal("1000.00")
    assert in_period(yearly, Period.MONTH) == Decimal("83.33")
    assert in_period(yearly, Period.DAY) == Decimal("2.74")
    assert in_period(Decimal("-1000"), Period.DAY) == Decimal("-2.74")


@given(flows=flows_strategy)
def test_in_period_agrees_with_rates(flows):
    yearly = sum((per_year(f) for f in flows), Decimal(0))
    expected = rates(yearly)
    for period in Period:
        assert str(in_period(yearly, period)) == expected[f"per_{period.value}"]


def test_share_never_divides_by_zero():
    assert share(Decimal(-25), Decimal(100)) == Decimal("0.25")
    assert share(Decimal(25), Decimal(100)) == Decimal("0.25")
    assert share(Decimal(150), Decimal(100)) == Decimal("1.5")
    assert share(Decimal(10), Decimal(0)) is None
    assert share(Decimal(0), Decimal(0)) is None
    assert share(Decimal(10), Decimal(-5)) is None


@pytest.mark.parametrize(
    ("fraction", "text"),
    [
        ("0.2845", "28%"),
        ("0.285", "29%"),  # half up
        ("0.995", "100%"),
        ("1.19", "119%"),
        ("0", "0%"),
        ("0.0049", "<1%"),
        ("0.005", "1%"),
        ("1", "100%"),
    ],
)
def test_percent_text(fraction, text):
    assert percent_text(Decimal(fraction)) == text


@pytest.mark.parametrize(
    ("every", "unit", "text"),
    [
        (1, WEEK, "every week"),
        (2, WEEK, "every 2 weeks"),
        (1, MONTH, "every month"),
        (6, MONTH, "every 6 months"),
        (1, DAY, "every day"),
        (14, DAY, "every 14 days"),
        (1, YEAR, "every year"),
        (3, YEAR, "every 3 years"),
    ],
)
def test_every_text(every, unit, text):
    assert every_text(every, unit) == text


# --- rules -----------------------------------------------------------------


@pytest.mark.db
class TestCashFlowRules:
    def test_create_cleans_and_rounds(self, db_connection):
        created = create_cash_flow(
            db_connection,
            WS,
            flow("12.345", 1, MONTH, name="  Spotify   Premium ", description="  "),
        )
        assert (created.name, created.amount, created.description) == (
            "Spotify Premium",
            Decimal("12.35"),
            None,
        )
        assert created.workspace_id == WS and created.is_estimate is False

    @pytest.mark.parametrize(
        ("bad", "message"),
        [
            (flow("-1", 1, MONTH), "cannot be negative"),
            (flow("1e14", 1, MONTH), "too large"),
            (flow("1", 0, MONTH), "between 1 and 1000"),
            (flow("1", 1001, MONTH), "between 1 and 1000"),
            (flow("1", 1, MONTH, name="   "), "Name is required"),
            (flow("1", 1, MONTH, category_id=99), "Category 99 does not exist"),
        ],
    )
    def test_create_rejects(self, db_connection, bad, message):
        with pytest.raises(CashFlowError, match=message):
            create_cash_flow(db_connection, WS, bad)
        assert repo.get_cash_flows(db_connection, WS) == []

    def test_names_are_unique_per_workspace(self, db_connection):
        create_cash_flow(db_connection, WS, flow("1", 1, MONTH, name="Rent"))
        with pytest.raises(CashFlowError, match="already exists"):
            create_cash_flow(db_connection, WS, flow("2", 1, MONTH, name="Rent"))
        other = create_workspace(db_connection, USER_ID, "Other")
        create_cash_flow(db_connection, other.id, flow("3", 1, MONTH, name="Rent"))

    def test_another_workspaces_category_is_unknown(self, db_connection):
        other = create_workspace(db_connection, USER_ID, "Other")
        theirs = create_category(db_connection, other.id, "Fitness")
        with pytest.raises(CashFlowError, match="does not exist"):
            create_cash_flow(
                db_connection, WS, flow("1", 1, MONTH, category_id=theirs.id)
            )

    def test_update_changes_only_what_is_given(self, db_connection):
        fitness = create_category(db_connection, WS, "Fitness")
        gym = create_cash_flow(
            db_connection,
            WS,
            flow(
                "579", 1, YEAR, name="Gym", category_id=fitness.id, description="Annual"
            ),
        )

        updated = update_cash_flow(
            db_connection, WS, gym.id, {"amount": Decimal("600"), "is_estimate": True}
        )

        assert (updated.amount, updated.is_estimate) == (Decimal("600.00"), True)
        assert (updated.name, updated.category_id, updated.description) == (
            "Gym",
            fitness.id,
            "Annual",
        )
        assert updated.updated_at is not None and gym.updated_at is not None
        assert updated.updated_at > gym.updated_at

    def test_update_validates_like_create(self, db_connection):
        a = create_cash_flow(db_connection, WS, flow("1", 1, MONTH, name="A"))
        create_cash_flow(db_connection, WS, flow("1", 1, MONTH, name="B"))
        with pytest.raises(CashFlowError, match="already exists"):
            update_cash_flow(db_connection, WS, a.id, {"name": "B"})
        with pytest.raises(CashFlowError, match="cannot be negative"):
            update_cash_flow(db_connection, WS, a.id, {"amount": Decimal("-5")})
        # Changes are applied without model validation, so the service's own
        # check is what stops these.
        for bad in ("NaN", "Infinity", "sNaN"):
            with pytest.raises(CashFlowError, match="must be a number"):
                update_cash_flow(db_connection, WS, a.id, {"amount": Decimal(bad)})
        with pytest.raises(CashFlowError, match="does not exist"):
            update_cash_flow(db_connection, WS, 999, {"name": "C"})
        loaded = repo.get_cash_flow(db_connection, WS, a.id)
        assert loaded is not None and (loaded.name, loaded.amount) == (
            "A",
            Decimal("1.00"),
        )

    def test_another_workspaces_flow_cannot_be_changed(self, db_connection):
        other = create_workspace(db_connection, USER_ID, "Other")
        theirs = create_cash_flow(db_connection, other.id, flow("1", 1, MONTH))
        with pytest.raises(CashFlowError, match="does not exist"):
            update_cash_flow(db_connection, WS, theirs.id, {"name": "Mine"})
        with pytest.raises(CashFlowError, match="does not exist"):
            delete_cash_flow(db_connection, WS, theirs.id)
        assert repo.get_cash_flow(db_connection, other.id, theirs.id) == theirs

    def test_list_order_is_income_then_category_order_then_name(self, db_connection):
        subs = create_category(db_connection, WS, "Subscriptions")
        fitness = create_category(db_connection, WS, "Fitness")
        update_category(db_connection, WS, fitness.id, position=-1)
        for name, direction, category in [
            ("spotify", EXPENSE, subs),
            ("Apple One", EXPENSE, subs),
            ("Gym", EXPENSE, fitness),
            ("Haircut", EXPENSE, None),
            ("Pay", INCOME, None),
        ]:
            create_cash_flow(
                db_connection,
                WS,
                flow(
                    "1",
                    1,
                    MONTH,
                    direction,
                    name=name,
                    category_id=category.id if category else None,
                ),
            )
        names = [f.name for f in repo.get_cash_flows(db_connection, WS)]
        assert names == ["Pay", "Gym", "Apple One", "spotify", "Haircut"]


@pytest.mark.db
class TestCategories:
    def test_new_categories_go_last(self, db_connection):
        names = ["Necessities", "Fitness", "Subscriptions"]
        for name in names:
            create_category(db_connection, WS, name)
        listed = repo.get_cash_flow_categories(db_connection, WS)
        assert [c.name for c in listed] == names
        assert [c.position for c in listed] == [0, 1, 2]

    def test_names_are_unique_per_workspace(self, db_connection):
        create_category(db_connection, WS, "Fitness")
        other = create_category(db_connection, WS, "Other")
        with pytest.raises(CashFlowError, match="already exists"):
            create_category(db_connection, WS, " Fitness ")
        with pytest.raises(CashFlowError, match="already exists"):
            update_category(db_connection, WS, other.id, name="Fitness")

    def test_deleting_a_category_uncategorizes_its_flows(self, db_connection):
        fitness = create_category(db_connection, WS, "Fitness")
        gym = create_cash_flow(
            db_connection, WS, flow("1", 1, MONTH, name="Gym", category_id=fitness.id)
        )

        delete_category(db_connection, WS, fitness.id)

        loaded = repo.get_cash_flow(db_connection, WS, gym.id)
        assert loaded is not None
        assert (loaded.category_id, loaded.workspace_id) == (None, WS)

    def test_move_swaps_with_the_neighbour_and_renumbers(self, db_connection):
        a, b, c = (create_category(db_connection, WS, n) for n in "ABC")
        moved = move_category(db_connection, WS, c.id, -1)
        assert (moved.id, moved.position) == (c.id, 1)
        listed = repo.get_cash_flow_categories(db_connection, WS)
        assert [x.name for x in listed] == ["A", "C", "B"]
        assert [x.position for x in listed] == [0, 1, 2]
        move_category(db_connection, WS, a.id, 1)
        listed = repo.get_cash_flow_categories(db_connection, WS)
        assert [x.name for x in listed] == ["C", "A", "B"]

    @pytest.mark.parametrize(("name", "step"), [("A", -1), ("C", 1)])
    def test_move_past_an_end_changes_nothing(self, db_connection, name, step):
        made = {n: create_category(db_connection, WS, n) for n in "ABC"}
        moved = move_category(db_connection, WS, made[name].id, step)
        assert moved.position == (0 if name == "A" else 2)
        listed = repo.get_cash_flow_categories(db_connection, WS)
        assert [(x.name, x.position) for x in listed] == [("A", 0), ("B", 1), ("C", 2)]

    def test_move_untangles_tied_positions(self, db_connection):
        # Positions set through the API can tie; display order breaks ties
        # by id, and a move works on that order.
        a, b, c = (create_category(db_connection, WS, n) for n in "ABC")
        for x in (a, b, c):
            update_category(db_connection, WS, x.id, position=5)
        move_category(db_connection, WS, c.id, -1)
        listed = repo.get_cash_flow_categories(db_connection, WS)
        assert [(x.name, x.position) for x in listed] == [
            ("A", 0),
            ("C", 1),
            ("B", 2),
        ]

    @pytest.mark.parametrize("step", [0, 2, -2])
    def test_move_is_one_step(self, db_connection, step):
        a = create_category(db_connection, WS, "A")
        with pytest.raises(CashFlowError, match="one place"):
            move_category(db_connection, WS, a.id, step)

    def test_another_workspaces_category_cannot_be_changed(self, db_connection):
        other = create_workspace(db_connection, USER_ID, "Other")
        theirs = create_category(db_connection, other.id, "Fitness")
        with pytest.raises(CashFlowError, match="does not exist"):
            update_category(db_connection, WS, theirs.id, name="Mine")
        with pytest.raises(CashFlowError, match="does not exist"):
            delete_category(db_connection, WS, theirs.id)
        with pytest.raises(CashFlowError, match="does not exist"):
            move_category(db_connection, WS, theirs.id, 1)
        assert repo.get_cash_flow_categories(db_connection, other.id) == [theirs]


@pytest.mark.db
def test_the_database_refuses_a_category_from_another_workspace(db_connection):
    other = create_workspace(db_connection, USER_ID, "Other")
    theirs = create_category(db_connection, other.id, "Fitness")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db_connection.execute(
            """
            INSERT INTO cash_flows (workspace_id, name, direction, amount, every, unit, category_id)
            VALUES (%s, 'Gym', 'expense', 1, 1, 'month', %s)
            """,
            (WS, theirs.id),
        )


@pytest.mark.db
class TestWorkspaceScoping:
    """Each workspace's lists hold only its own rows, and the repository
    refuses another workspace's ids even without the service's checks."""

    def _two_workspaces(self, conn):
        other = create_workspace(conn, USER_ID, "Other")
        mine = create_cash_flow(conn, WS, flow("1", 1, MONTH, name="Mine"))
        theirs = create_cash_flow(conn, other.id, flow("2", 1, MONTH, name="Theirs"))
        create_category(conn, WS, "My Category")
        create_category(conn, other.id, "Their Category")
        return other, mine, theirs

    def test_lists_hold_only_their_own_workspace(self, db_connection):
        other, _, _ = self._two_workspaces(db_connection)
        for workspace_id, flow_name, category in [
            (WS, "Mine", "My Category"),
            (other.id, "Theirs", "Their Category"),
        ]:
            flows = repo.get_cash_flows(db_connection, workspace_id)
            assert [f.name for f in flows] == [flow_name]
            categories = repo.get_cash_flow_categories(db_connection, workspace_id)
            assert [c.name for c in categories] == [category]

    def test_repository_writes_ignore_another_workspaces_ids(self, db_connection):
        other, _, theirs = self._two_workspaces(db_connection)
        renamed = theirs.model_copy(update={"name": "Hijacked"})

        repo.update_cash_flow(db_connection, WS, renamed)
        assert repo.delete_cash_flow(db_connection, WS, theirs.id) is False
        db_connection.commit()

        assert repo.get_cash_flow(db_connection, other.id, theirs.id) == theirs
