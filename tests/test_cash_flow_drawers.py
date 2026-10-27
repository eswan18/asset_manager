"""The Cash flows page's drawers: a cash flow's form (board R) and category
management (board T).

Each drawer renders the Cash flows page underneath, keeping its `?per=`
period; POSTs go back to the page (or, for categories, the drawer) with the
period, and validation errors re-render the drawer with a 400.
"""

import re
from decimal import Decimal

import pytest

from sensibility import repository as repo
from sensibility.cashflows import create_cash_flow, create_category
from sensibility.models import CashFlow, CashFlowDirection, FrequencyUnit
from sensibility.web.cash_flows_routes import form_rates
from sensibility.workspaces import create_workspace
from tests.support import USER_ID, WS
from tests.web_support import PAGES, STRANGER, add_user, login, session_for

INCOME, EXPENSE = CashFlowDirection.INCOME, CashFlowDirection.EXPENSE
DAY, WEEK, MONTH, YEAR = (
    FrequencyUnit.DAY,
    FrequencyUnit.WEEK,
    FrequencyUnit.MONTH,
    FrequencyUnit.YEAR,
)
PAGE = f"{PAGES}/cash-flows"
CATEGORIES = f"{PAGES}/cash-flow-categories"


def flow(name, amount, every=1, unit=MONTH, direction=EXPENSE, **extra) -> CashFlow:
    return CashFlow(
        name=name,
        direction=direction,
        amount=Decimal(amount),
        every=every,
        unit=unit,
        **extra,
    )


def drawer(text: str) -> str:
    """The drawer's markup alone."""
    start = text.index('<aside class="drawer"')
    return text[start : text.index("</aside>", start)]


def behind(text: str) -> str:
    """Everything but the drawer: the shell and the Cash flows page."""
    start = text.index('<aside class="drawer"')
    return text[:start] + text[text.index("</aside>", start) :]


def visible(html: str) -> str:
    """Visible text, whitespace collapsed."""
    body = re.sub(r"<style.*?</style>|<script.*?</script>", "", html, flags=re.S)
    return " ".join(re.sub(r"<[^>]+>", " ", body).split())


class Seed:
    """Like the mockups: Work holds only income, Gifts nothing."""

    def __init__(self, conn, workspace_id=WS):
        self.work = create_category(conn, workspace_id, "Work")
        self.housing = create_category(conn, workspace_id, "Housing")
        self.food = create_category(conn, workspace_id, "Food")
        self.transport = create_category(conn, workspace_id, "Transport")
        self.gifts = create_category(conn, workspace_id, "Gifts")
        add = lambda f: create_cash_flow(conn, workspace_id, f)  # noqa: E731
        self.salary = add(
            flow("Salary", "5100", 2, WEEK, INCOME, category_id=self.work.id)
        )
        self.side = add(flow("Side consulting", "800", direction=INCOME))
        self.mortgage = add(flow("Mortgage", "2450", category_id=self.housing.id))
        self.utilities = add(flow("Utilities", "260", category_id=self.housing.id))
        self.groceries = add(
            flow(
                "Groceries",
                "180",
                1,
                WEEK,
                category_id=self.food.id,
                is_estimate=True,
                description="Costco + weekly shop",
            )
        )
        self.restaurants = add(flow("Restaurants", "350", category_id=self.food.id))
        self.gas = add(flow("Gas", "120", category_id=self.transport.id))
        self.car = add(flow("Car insurance", "1140", 6, MONTH))


@pytest.fixture
def seed(db_connection):
    return Seed(db_connection)


def valid_form(**changes) -> dict:
    form = {
        "name": "Gym",
        "direction": "expense",
        "amount": "45",
        "every": "1",
        "unit": "month",
        "category_id": "",
        "description": "",
    }
    form.update(changes)
    return form


# --- the rates strip -----------------------------------------------------------


def rates_of(**changes):
    """form_rates() for a form as the routes build it."""
    return form_rates({**valid_form(**changes), "is_estimate": False})


class TestFormRates:
    def test_matches_rates(self):
        rates = rates_of(amount="100", unit="week")
        assert rates == {
            "per_day": "$14.29",
            "per_month": "$434.52",
            "per_year": "$5,214.29",
        }

    def test_income_and_expense_read_the_same(self):
        assert rates_of(direction="income") == rates_of()

    def test_rounds_the_amount_to_cents_first_as_a_save_does(self):
        # 0.005 a day saves as 0.01, so a year is 3.65, not 1.83.
        rates = rates_of(amount="0.005", unit="day")
        assert rates is not None and rates["per_year"] == "$3.65"

    def test_takes_money_text(self):
        rates = rates_of(amount="$1,200", every="2", unit="year")
        assert rates is not None and rates["per_year"] == "$600.00"

    @pytest.mark.parametrize(
        "changes",
        [
            {"amount": ""},
            {"amount": "abc"},
            {"amount": "1e3"},
            {"amount": "NaN"},
            {"amount": "-5"},
            {"amount": "10000000000000"},
            {"every": "0"},
            {"every": "1001"},
            {"every": "1.5"},
            {"every": ""},
            {"unit": "fortnight"},
        ],
    )
    def test_nothing_to_show(self, changes):
        assert rates_of(**changes) is None

    def test_the_largest_amounts_still_show(self):
        assert rates_of(amount="9999999999999.99", every="1000")


# --- the page's controls ---------------------------------------------------------


@pytest.mark.db
class TestPageControls:
    def test_rows_open_their_drawer_keeping_the_period(self, client, seed):
        login(client)
        html = client.get(f"{PAGE}?per=year").text
        assert (
            f'<a class="row flow-row" href="{PAGE}/{seed.groceries.id}/edit?per=year">'
            in html
        )
        assert html.count('class="row flow-row" href=') == 8

    def test_each_card_adds_into_itself(self, client, seed):
        login(client)
        html = client.get(f"{PAGE}?per=day").text
        new = f"{PAGE}/new?"
        assert (
            f'href="{new}direction=income&amp;per=day" aria-label="Add to Income"'
            in html
        )
        assert (
            f'href="{new}direction=expense&amp;category_id={seed.food.id}&amp;per=day"'
            ' aria-label="Add to Food"' in html
        )
        assert (
            f'href="{new}direction=expense&amp;per=day" aria-label="Add to Uncategorized"'
            in html
        )

    def test_add_new_category_and_manage(self, client, seed):
        login(client)
        html = client.get(f"{PAGE}?per=year").text
        assert f'href="{PAGE}/new?per=year">+ Add cash flow</a>' in html
        assert f'href="{CATEGORIES}?per=year">Manage categories</a>' in html
        assert (
            f'<a class="new-category" href="{CATEGORIES}?per=year&amp;add=1">'
            "+ New category</a>" in html
        )

    def test_the_empty_page_offers_one_button_income_first(self, client, db_connection):
        # Board Y: one button; the drawer can switch the flow to an expense.
        login(client)
        html = client.get(PAGE).text
        assert f'href="{PAGE}/new?direction=income&amp;per=month">+ Add income' in html
        assert "direction=expense" not in html
        assert "Manage categories" not in html

    def test_viewers_get_no_controls(self, client, db_connection, seed):
        add_user(db_connection, STRANGER, "viewer")
        session_for(client, STRANGER)
        html = client.get(PAGE).text
        main = html.split("<main", 1)[1]
        assert "Groceries" in main
        for control in ("+ Add", "New category", "Manage categories", "/edit"):
            assert control not in main
        assert "<a " not in main.split("Where income goes")[1]

    def test_viewers_empty_page_has_no_controls(self, client, db_connection):
        add_user(db_connection, STRANGER, "viewer")
        session_for(client, STRANGER)
        main = client.get(PAGE).text.split("<main", 1)[1]
        assert "No cash flows yet" in main
        assert "+ Add" not in main and "Manage categories" not in main


# --- the cash flow drawer --------------------------------------------------------


@pytest.mark.db
class TestFlowDrawer:
    def test_renders_the_page_underneath_inert(self, client, seed):
        login(client)
        response = client.get(f"{PAGE}/{seed.groceries.id}/edit?per=year")
        assert response.status_code == 200
        text = response.text
        page = behind(text)
        assert "Left over each year" in visible(page)
        assert '<header class="shell-header" inert>' in text
        assert '<main class="container" inert>' in text
        assert '<body class="drawer-open">' in text
        assert 'class="scrim"' in text
        assert re.search(
            rf'<a href="{PAGE}" aria-current="page">(<svg class="tab-icon".*?</svg>)?Cash flows</a>',
            page,
            flags=re.S,
        )
        assert "<title>Groceries · Test · " in text
        assert "event.key === 'Escape'" in text

    def test_the_toggle_still_links_to_the_page(self, client, seed):
        login(client)
        html = client.get(f"{PAGE}/{seed.groceries.id}/edit?per=year").text
        for period in ("day", "month", "year"):
            assert f'href="{PAGE}?per={period}"' in behind(html)
        assert re.findall(r'aria-current="true">(\w+)<', html) == ["Year"]

    def test_the_picker_maps_to_cash_flows(self, client, db_connection, seed):
        other = create_workspace(db_connection, USER_ID, "Other")
        login(client)
        html = client.get(f"{PAGE}/{seed.groceries.id}/edit").text
        assert f'value="/workspaces/{other.id}/cash-flows"' in html

    def test_edit_header(self, client, seed):
        login(client)
        d = drawer(client.get(f"{PAGE}/{seed.groceries.id}/edit").text)
        assert 'role="dialog"' in d and 'aria-modal="true"' in d
        assert (
            '<span class="drawer-eyebrow" id="drawer-eyebrow">Edit expense · Food</span>'
            in d
        )
        assert '<h1 id="drawer-title">Groceries</h1>' in d
        # Food is the second-largest expense category: the second ramp color,
        # as its card on the page.
        assert 'style="--section: var(--liability-2);"' in d
        assert 'data-verb="Edit"' in d

    def test_income_header_is_blue(self, client, seed):
        login(client)
        d = drawer(client.get(f"{PAGE}/{seed.salary.id}/edit").text)
        assert ">Edit income · Work</span>" in d
        assert 'style="--section: var(--asset);"' in d

    def test_uncategorized_expense_takes_its_cards_color(self, client, seed):
        login(client)
        d = drawer(client.get(f"{PAGE}/{seed.car.id}/edit").text)
        assert ">Edit expense</span>" in d
        assert 'style="--section: var(--liability-3);"' in d

    def test_fields_prefilled(self, client, seed):
        login(client)
        d = drawer(client.get(f"{PAGE}/{seed.groceries.id}/edit?per=day").text)
        assert re.search(r'name="direction" value="expense"\s*checked', d)
        assert not re.search(r'name="direction" value="income"\s*checked', d)
        assert re.search(r'<input[^>]*name="name" value="Groceries"[^>]*autofocus', d)
        assert 'name="amount" value="180.00"' in d
        assert 'name="every" value="1"' in d
        assert '<option value="week" selected>week</option>' in d
        assert re.search(
            rf'<option value="{seed.food.id}" data-color="var\(--liability-2\)"\s*selected>Food',
            d,
        )
        assert re.search(r'name="is_estimate"\s*checked', d)
        assert "Costco + weekly shop</textarea>" in d

    def test_category_options_carry_their_page_colors(self, client, seed):
        login(client)
        d = drawer(client.get(f"{PAGE}/{seed.groceries.id}/edit").text)
        assert re.search(
            r'<option value="" data-color="var\(--liability-3\)"\s*>Uncategorized', d
        )
        assert f'value="{seed.housing.id}" data-color="var(--liability)"' in d
        # No expenses, so no card and no color of its own on the page.
        assert f'value="{seed.gifts.id}" data-color="var(--liability)"' in d
        names = re.findall(r'<option value="\d*" data-color="[^"]+"[^>]*>(\w+)', d)
        assert names == [
            "Uncategorized",
            "Work",
            "Housing",
            "Food",
            "Transport",
            "Gifts",
        ]

    def test_rates_strip_matches_the_page(self, client, seed):
        login(client)
        html = client.get(f"{PAGE}/{seed.groceries.id}/edit").text
        d = drawer(html)
        assert '<strong id="rate-day">$25.71</strong>' in d
        assert '<strong id="rate-month">$782.14</strong>' in d
        assert '<strong id="rate-year">$9,385.71</strong>' in d
        # The row on the page, per month, is the same figure.
        assert "Groceries ≈ $180.00 every week $782.14" in visible(behind(html))

    def test_close_cancel_save_and_delete_keep_the_period(self, client, seed):
        login(client)
        d = drawer(client.get(f"{PAGE}/{seed.groceries.id}/edit?per=day").text)
        gid = seed.groceries.id
        assert f'class="drawer-close" href="{PAGE}?per=day" aria-label="Close"' in d
        assert f'<a class="btn btn-outline" href="{PAGE}?per=day">Cancel</a>' in d
        assert f'action="{PAGE}/{gid}?per=day"' in d
        assert f'action="{PAGE}/{gid}/delete?per=day"' in d
        assert 'form="delete-form">Delete</button>' in d
        assert 'class="btn btn-primary" form="flow-form">Save</button>' in d

    def test_an_unknown_period_is_the_default(self, client, seed):
        login(client)
        d = drawer(client.get(f"{PAGE}/{seed.gas.id}/edit?per=fortnight").text)
        assert f'href="{PAGE}?per=month"' in d

    def test_edit_of_a_missing_flow_is_404(self, client, seed):
        login(client)
        assert client.get(f"{PAGE}/9999/edit").status_code == 404


@pytest.mark.db
class TestNewFlow:
    def test_defaults_to_an_uncategorized_monthly_expense(self, client, seed):
        login(client)
        response = client.get(f"{PAGE}/new")
        assert response.status_code == 200
        d = drawer(response.text)
        assert ">New expense</span>" in d
        assert '<h1 id="drawer-title">New cash flow</h1>' in d
        assert re.search(r'name="direction" value="expense"\s*checked', d)
        assert 'name="amount" value=""' in d
        assert 'name="every" value="1"' in d
        assert '<option value="month" selected>month</option>' in d
        assert re.search(
            r'<option value="" data-color="[^"]+"\s*selected>Uncategorized', d
        )
        assert not re.search(r'name="is_estimate"\s*checked', d)
        assert '<strong id="rate-month">—</strong>' in d
        assert f'action="{PAGE}?per=month"' in d
        assert "Delete" not in d and "delete-form" not in d
        assert "<title>New cash flow · Test · " in response.text

    def test_prefills_income(self, client, seed):
        login(client)
        d = drawer(client.get(f"{PAGE}/new?direction=income&per=year").text)
        assert ">New income</span>" in d
        assert re.search(r'name="direction" value="income"\s*checked', d)
        assert 'style="--section: var(--asset);"' in d
        assert f'action="{PAGE}?per=year"' in d

    def test_prefills_the_category(self, client, seed):
        login(client)
        d = drawer(
            client.get(f"{PAGE}/new?direction=expense&category_id={seed.food.id}").text
        )
        assert ">New expense · Food</span>" in d
        assert re.search(rf'<option value="{seed.food.id}"[^>]*selected>Food', d)
        assert 'style="--section: var(--liability-2);"' in d

    @pytest.mark.parametrize("query", ["direction=sideways", "direction="])
    def test_an_unknown_direction_is_expense(self, client, seed, query):
        login(client)
        d = drawer(client.get(f"{PAGE}/new?{query}").text)
        assert re.search(r'name="direction" value="expense"\s*checked', d)

    def test_another_workspaces_category_is_not_prefilled(
        self, client, db_connection, seed
    ):
        other = create_workspace(db_connection, USER_ID, "Other")
        theirs = create_category(db_connection, other.id, "Theirs")
        login(client)
        response = client.get(f"{PAGE}/new?category_id={theirs.id}")
        assert response.status_code == 200
        d = drawer(response.text)
        assert "Theirs" not in d
        assert re.search(r'<option value="" data-color="[^"]+"\s*selected>', d)

    def test_over_an_empty_page(self, client, db_connection):
        login(client)
        text = client.get(f"{PAGE}/new").text
        assert "No cash flows yet" in behind(text)
        names = re.findall(
            r'<option value="\d*" data-color="[^"]+"[^>]*>(\w+)', drawer(text)
        )
        assert names == ["Uncategorized"]


@pytest.mark.db
class TestCreate:
    def test_creates_and_goes_back_to_the_page_with_the_period(
        self, client, db_connection, seed
    ):
        login(client)
        response = client.post(
            f"{PAGE}?per=year",
            data=valid_form(
                name="  Gym  ",
                amount="$1,045.505",
                every="2",
                unit="week",
                category_id=str(seed.housing.id),
                is_estimate="on",
                description=" Monthly pass ",
            ),
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == f"{PAGE}?per=year"
        created = [f for f in repo.get_cash_flows(db_connection, WS) if f.name == "Gym"]
        assert len(created) == 1
        gym = created[0]
        assert gym.direction == EXPENSE
        assert gym.amount == Decimal("1045.51")
        assert (gym.every, gym.unit) == (2, WEEK)
        assert gym.category_id == seed.housing.id
        assert gym.is_estimate is True
        assert gym.description == "Monthly pass"
        page = client.get(response.headers["location"]).text
        assert "Added Gym: $2,271.49 a month." in page
        assert "Left over each year" in visible(page)

    def test_creates_income_without_a_category(self, client, db_connection):
        login(client)
        response = client.post(
            PAGE,
            data=valid_form(name="Pay", direction="income", amount="10"),
            follow_redirects=False,
        )
        assert response.headers["location"] == f"{PAGE}?per=month"
        (pay,) = repo.get_cash_flows(db_connection, WS)
        assert (pay.direction, pay.category_id, pay.is_estimate, pay.description) == (
            INCOME,
            None,
            False,
            None,
        )

    @pytest.mark.parametrize(
        ("changes", "message"),
        [
            ({"name": "   "}, "Name is required"),
            (
                {"name": "Mortgage"},
                "A cash flow named &#39;Mortgage&#39; already exists",
            ),
            ({"amount": "-5"}, "Amount cannot be negative"),
            ({"amount": "(5)"}, "Amount must be a number"),
            ({"amount": "abc"}, "Amount must be a number"),
            ({"amount": ""}, "Amount must be a number"),
            ({"amount": "NaN"}, "Amount must be a number"),
            ({"amount": "1e3"}, "Amount must be a number"),
            ({"amount": "10000000000000"}, "Amount is too large"),
            ({"every": "0"}, "Every must be between 1 and 1000"),
            ({"every": "1001"}, "Every must be between 1 and 1000"),
            ({"every": "1.5"}, "Every must be a whole number"),
            ({"every": "-2"}, "Every must be a whole number"),
            ({"direction": "sideways"}, "Choose income or expense"),
            ({"unit": "fortnight"}, "Choose day, week, month or year"),
            ({"category_id": "9999"}, "Category 9999 does not exist"),
            ({"category_id": "food"}, "Choose a category from the list"),
        ],
    )
    def test_errors_rerender_the_drawer_with_the_input(
        self, client, db_connection, seed, changes, message
    ):
        before = repo.get_cash_flows(db_connection, WS)
        login(client)
        form = valid_form(
            name="Gym", amount="45", description="My note", is_estimate="on"
        )
        form.update(changes)
        response = client.post(f"{PAGE}?per=day", data=form)
        assert response.status_code == 400
        text = response.text
        d = drawer(text)
        assert 'class="drawer-error" role="alert"' in d
        assert message in d
        # In the drawer, not behind the scrim.
        assert '<div class="error">' not in behind(text)
        assert f'name="name" value="{form["name"]}"' in d
        assert f'name="amount" value="{form["amount"]}"' in d
        assert f'name="every" value="{form["every"]}"' in d
        assert re.search(r'name="is_estimate"\s*checked', d)
        assert "My note</textarea>" in d
        # Still over the page, in the same period, and still a new flow.
        assert "Left over each day" in visible(behind(text))
        assert f'action="{PAGE}?per=day"' in d
        assert '<h1 id="drawer-title">New cash flow</h1>' in d
        db_connection.rollback()
        assert repo.get_cash_flows(db_connection, WS) == before

    def test_another_workspaces_category_cannot_be_used(
        self, client, db_connection, seed
    ):
        other = create_workspace(db_connection, USER_ID, "Other")
        theirs = create_category(db_connection, other.id, "Theirs")
        login(client)
        response = client.post(PAGE, data=valid_form(category_id=str(theirs.id)))
        assert response.status_code == 400
        assert f"Category {theirs.id} does not exist" in drawer(response.text)

    def test_error_keeps_the_choices(self, client, seed):
        login(client)
        response = client.post(
            PAGE,
            data=valid_form(
                name="",
                direction="income",
                unit="year",
                category_id=str(seed.work.id),
            ),
        )
        d = drawer(response.text)
        assert re.search(r'name="direction" value="income"\s*checked', d)
        assert '<option value="year" selected>year</option>' in d
        assert re.search(rf'<option value="{seed.work.id}"[^>]*selected>', d)
        assert ">New income · Work</span>" in d
        # The strip shows what the valid fields come to.
        assert '<strong id="rate-year">$45.00</strong>' in d


@pytest.mark.db
class TestUpdate:
    def test_saves_every_field_and_goes_back(self, client, db_connection, seed):
        login(client)
        response = client.post(
            f"{PAGE}/{seed.groceries.id}?per=day",
            data=valid_form(
                name="Food shop",
                direction="income",
                amount="200",
                every="3",
                unit="day",
                category_id="",
                description="",
            ),
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == f"{PAGE}?per=day"
        saved = repo.get_cash_flow(db_connection, WS, seed.groceries.id)
        assert saved is not None
        assert saved.name == "Food shop"
        assert saved.direction == INCOME
        assert (saved.amount, saved.every, saved.unit) == (Decimal("200.00"), 3, DAY)
        # Cleared: the category, the note, and the unchecked estimate box.
        assert (saved.category_id, saved.description, saved.is_estimate) == (
            None,
            None,
            False,
        )
        assert "Saved Food shop: $2,027.78 a month." in (
            client.get(response.headers["location"]).text
        )

    def test_moves_to_another_category(self, client, db_connection, seed):
        login(client)
        client.post(
            f"{PAGE}/{seed.gas.id}",
            data=valid_form(name="Gas", amount="120", category_id=str(seed.food.id)),
        )
        saved = repo.get_cash_flow(db_connection, WS, seed.gas.id)
        assert saved is not None and saved.category_id == seed.food.id

    def test_error_keeps_the_saved_title_and_the_input(
        self, client, db_connection, seed
    ):
        login(client)
        response = client.post(
            f"{PAGE}/{seed.groceries.id}?per=year",
            data=valid_form(name="Restaurants", amount="99", unit="year"),
        )
        assert response.status_code == 400
        d = drawer(response.text)
        assert "A cash flow named &#39;Restaurants&#39; already exists" in d
        assert '<h1 id="drawer-title">Groceries</h1>' in d
        assert 'name="name" value="Restaurants"' in d
        assert 'name="amount" value="99"' in d
        assert f'action="{PAGE}/{seed.groceries.id}?per=year"' in d
        assert 'form="delete-form">Delete</button>' in d
        # The eyebrow follows the form: no category chosen now.
        assert ">Edit expense</span>" in d
        db_connection.rollback()
        saved = repo.get_cash_flow(db_connection, WS, seed.groceries.id)
        assert saved is not None and saved.name == "Groceries"
        assert saved.amount == Decimal("180.00")

    def test_missing_flow_is_404(self, client, seed):
        login(client)
        assert client.post(f"{PAGE}/9999", data=valid_form()).status_code == 404


@pytest.mark.db
class TestDelete:
    def test_deletes_and_goes_back(self, client, db_connection, seed):
        login(client)
        response = client.post(
            f"{PAGE}/{seed.gas.id}/delete?per=year", follow_redirects=False
        )
        assert response.status_code == 303
        assert response.headers["location"] == f"{PAGE}?per=year"
        assert repo.get_cash_flow(db_connection, WS, seed.gas.id) is None
        assert len(repo.get_cash_flows(db_connection, WS)) == 7
        assert "Deleted Gas" in client.get(response.headers["location"]).text

    def test_missing_flow_is_404(self, client, seed):
        login(client)
        assert client.post(f"{PAGE}/9999/delete").status_code == 404


@pytest.mark.db
class TestFlowIsolation:
    """Another workspace's cash flow ids behave as nonexistent."""

    def test_another_workspaces_flow_is_404_everywhere(self, client, db_connection):
        Seed(db_connection)
        other = create_workspace(db_connection, USER_ID, "Other")
        theirs = create_cash_flow(db_connection, other.id, flow("Theirs", "5"))
        login(client)
        assert client.get(f"{PAGE}/{theirs.id}/edit").status_code == 404
        assert client.post(f"{PAGE}/{theirs.id}", data=valid_form()).status_code == 404
        assert client.post(f"{PAGE}/{theirs.id}/delete").status_code == 404
        saved = repo.get_cash_flow(db_connection, other.id, theirs.id)
        assert saved is not None and saved.name == "Theirs"


# --- the categories drawer -------------------------------------------------------


def rows(d: str) -> list[str]:
    """The categories' names, in the drawer's order."""
    return re.findall(r'name="name" value="([^"]*)" data-saved', d)


@pytest.mark.db
class TestCategoriesDrawer:
    def test_renders_over_the_page(self, client, seed):
        login(client)
        response = client.get(f"{CATEGORIES}?per=year")
        assert response.status_code == 200
        text = response.text
        assert "Left over each year" in visible(behind(text))
        assert '<body class="drawer-open">' in text
        assert "<title>Categories · Test · " in text
        d = drawer(text)
        assert '<h1 id="drawer-title">Categories</h1>' in d
        assert "Renaming or reordering saves right away." in d
        assert f'class="drawer-close" href="{PAGE}?per=year"' in d
        assert f'<a class="btn btn-primary" href="{PAGE}?per=year">Done</a>' in d

    def test_lists_categories_in_order_with_meta_and_colors(self, client, seed):
        login(client)
        d = drawer(client.get(CATEGORIES).text)
        assert rows(d) == ["Work", "Housing", "Food", "Transport", "Gifts"]
        text = visible(d)
        assert "1 flow · income $11,080.36/mo" in text
        assert "2 flows · $2,710.00/mo" in text
        assert "2 flows · $1,132.14/mo" in text
        assert "1 flow · $120.00/mo" in text
        assert "No flows yet" in text
        swatches = re.findall(r'class="cat-swatch" style="background: ([^;]+);"', d)
        assert swatches == [
            "var(--asset)",
            "var(--liability)",
            "var(--liability-2)",
            "var(--liability-4)",
            "var(--rule-strong)",
        ]

    def test_meta_follows_the_period(self, client, seed):
        login(client)
        text = visible(drawer(client.get(f"{CATEGORIES}?per=year").text))
        assert "2 flows · $32,520.00/yr" in text
        text = visible(drawer(client.get(f"{CATEGORIES}?per=day").text))
        assert "1 flow · $3.95/day" in text

    def test_a_category_with_both_directions_shows_both(
        self, client, db_connection, seed
    ):
        create_cash_flow(
            db_connection,
            WS,
            flow("Bonus", "1200", 1, YEAR, INCOME, category_id=seed.food.id),
        )
        login(client)
        text = visible(drawer(client.get(CATEGORIES).text))
        assert "3 flows · $1,132.14/mo · income $100.00/mo" in text

    def test_the_ends_cannot_move_further(self, client, seed):
        login(client)
        d = drawer(client.get(CATEGORIES).text)
        assert re.search(r'aria-label="Move Work up"\s+disabled', d)
        assert not re.search(r'aria-label="Move Work down"\s+disabled', d)
        assert not re.search(r'aria-label="Move Housing up"\s+disabled', d)
        assert re.search(r'aria-label="Move Gifts down"\s+disabled', d)
        assert len(re.findall(r"\sdisabled>", d)) == 2

    def test_forms_keep_the_period(self, client, seed):
        login(client)
        d = drawer(client.get(f"{CATEGORIES}?per=day").text)
        fid = seed.food.id
        assert f'action="{CATEGORIES}/{fid}?per=day"' in d
        assert f'action="{CATEGORIES}/{fid}/move?per=day"' in d
        assert (
            f'href="{CATEGORIES}?per=day&amp;confirm={fid}" aria-label="Delete Food"'
            in d
        )
        assert f'class="cat-add" method="post" action="{CATEGORIES}?per=day"' in d

    def test_add_focuses_the_new_name(self, client, seed):
        login(client)
        assert re.search(
            r'aria-label="New category name" required autofocus',
            drawer(client.get(f"{CATEGORIES}?add=1").text),
        )
        assert "autofocus" not in drawer(client.get(CATEGORIES).text)

    def test_no_categories_yet(self, client, db_connection):
        login(client)
        d = drawer(client.get(CATEGORIES).text)
        assert "No categories yet" in d
        assert rows(d) == []


@pytest.mark.db
class TestCategoryCreate:
    def test_adds_last_and_stays_in_the_drawer(self, client, db_connection, seed):
        login(client)
        response = client.post(
            f"{CATEGORIES}?per=year", data={"name": " Pets "}, follow_redirects=False
        )
        assert response.status_code == 303
        assert response.headers["location"] == f"{CATEGORIES}?per=year&add=1"
        names = [c.name for c in repo.get_cash_flow_categories(db_connection, WS)]
        assert names[-1] == "Pets"
        text = client.get(response.headers["location"]).text
        d = drawer(text)
        assert '<span class="drawer-status" role="status">Added Pets</span>' in d
        assert rows(d)[-1] == "Pets"
        # Only in the drawer: the page behind is under the scrim.
        assert "Added Pets" not in behind(text)

    @pytest.mark.parametrize(
        ("name", "message"),
        [
            ("  ", "Name is required"),
            ("Food", "A category named &#39;Food&#39; already exists"),
        ],
    )
    def test_errors_keep_the_input(self, client, db_connection, seed, name, message):
        login(client)
        response = client.post(f"{CATEGORIES}?per=day", data={"name": name})
        assert response.status_code == 400
        d = drawer(response.text)
        assert message in d and 'class="drawer-error" role="alert"' in d
        assert f'name="name" value="{name}" placeholder="New category name"' in d
        assert re.search(r'aria-label="New category name" required autofocus', d)
        assert "Left over each day" in visible(behind(response.text))
        db_connection.rollback()
        assert len(repo.get_cash_flow_categories(db_connection, WS)) == 5


@pytest.mark.db
class TestCategoryRename:
    def test_renames_and_stays(self, client, db_connection, seed):
        login(client)
        response = client.post(
            f"{CATEGORIES}/{seed.food.id}?per=year",
            data={"name": "Groceries & eating out"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == f"{CATEGORIES}?per=year"
        saved = repo.get_cash_flow_category(db_connection, WS, seed.food.id)
        assert saved is not None and saved.name == "Groceries & eating out"
        d = drawer(client.get(response.headers["location"]).text)
        assert "Saved Groceries &amp; eating out" in d

    @pytest.mark.parametrize(
        ("name", "message"),
        [
            ("", "Name is required"),
            ("Housing", "A category named &#39;Housing&#39; already exists"),
        ],
    )
    def test_errors_keep_the_input_in_its_row(
        self, client, db_connection, seed, name, message
    ):
        login(client)
        response = client.post(f"{CATEGORIES}/{seed.food.id}", data={"name": name})
        assert response.status_code == 400
        d = drawer(response.text)
        assert message in d
        assert re.search(
            rf'name="name" value="{name}" data-saved="Food" aria-label="Name of Food"'
            r' required aria-invalid="true" autofocus',
            d,
        )
        # The other rows are as saved.
        assert rows(d) == ["Work", "Housing", name, "Transport", "Gifts"]
        db_connection.rollback()
        saved = repo.get_cash_flow_category(db_connection, WS, seed.food.id)
        assert saved is not None and saved.name == "Food"


@pytest.mark.db
class TestCategoryMove:
    def test_moves_up_and_down(self, client, db_connection, seed):
        login(client)
        response = client.post(
            f"{CATEGORIES}/{seed.food.id}/move?per=day",
            data={"direction": "up"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == f"{CATEGORIES}?per=day"
        d = drawer(client.get(response.headers["location"]).text)
        assert rows(d) == ["Work", "Food", "Housing", "Transport", "Gifts"]
        assert "Moved Food up" in d
        client.post(f"{CATEGORIES}/{seed.work.id}/move", data={"direction": "down"})
        names = [c.name for c in repo.get_cash_flow_categories(db_connection, WS)]
        assert names == ["Food", "Work", "Housing", "Transport", "Gifts"]

    def test_the_cards_follow_the_order(self, client, seed):
        login(client)
        client.post(f"{CATEGORIES}/{seed.food.id}/move", data={"direction": "up"})
        text = visible(client.get(PAGE).text)
        assert text.index("Restaurants") < text.index("Mortgage")

    @pytest.mark.parametrize("direction", ["", "left", "UP"])
    def test_needs_up_or_down(self, client, db_connection, seed, direction):
        login(client)
        response = client.post(
            f"{CATEGORIES}/{seed.food.id}/move", data={"direction": direction}
        )
        assert response.status_code == 400
        names = [c.name for c in repo.get_cash_flow_categories(db_connection, WS)]
        assert names == ["Work", "Housing", "Food", "Transport", "Gifts"]


@pytest.mark.db
class TestCategoryDelete:
    def test_confirm_asks_in_the_row(self, client, seed):
        login(client)
        d = drawer(client.get(f"{CATEGORIES}?per=year&confirm={seed.food.id}").text)
        text = visible(d)
        assert (
            "Delete Food? 2 flows. They move to Uncategorized; nothing else is deleted."
            in text
        )
        assert (
            f'<a class="btn btn-outline" href="{CATEGORIES}?per=year" autofocus>Keep</a>'
            in d
        )
        assert f'action="{CATEGORIES}/{seed.food.id}/delete?per=year"' in d
        assert ">Delete category</button>" in d
        # The confirmation takes the row's place.
        assert "Food" not in rows(d)
        assert rows(d) == ["Work", "Housing", "Transport", "Gifts"]

    def test_confirm_counts_one_flow_and_none(self, client, seed):
        login(client)
        one = visible(
            drawer(client.get(f"{CATEGORIES}?confirm={seed.transport.id}").text)
        )
        assert "Delete Transport? 1 flow. It moves to Uncategorized" in one
        none = visible(drawer(client.get(f"{CATEGORIES}?confirm={seed.gifts.id}").text))
        assert "Delete Gifts? It has no flows; nothing else is deleted." in none

    def test_confirm_of_an_unknown_id_shows_the_plain_list(self, client, seed):
        login(client)
        d = drawer(client.get(f"{CATEGORIES}?confirm=9999").text)
        assert "Delete category" not in d
        assert len(rows(d)) == 5

    def test_delete_uncategorizes_its_flows(self, client, db_connection, seed):
        login(client)
        response = client.post(
            f"{CATEGORIES}/{seed.food.id}/delete?per=year", follow_redirects=False
        )
        assert response.status_code == 303
        assert response.headers["location"] == f"{CATEGORIES}?per=year"
        assert repo.get_cash_flow_category(db_connection, WS, seed.food.id) is None
        for f in (seed.groceries, seed.restaurants):
            saved = repo.get_cash_flow(db_connection, WS, f.id)
            assert saved is not None and saved.category_id is None
        assert len(repo.get_cash_flows(db_connection, WS)) == 8
        assert "Deleted Food" in drawer(client.get(response.headers["location"]).text)
        # On the page they now sit under Uncategorized.
        text = visible(client.get(PAGE).text)
        uncategorized = text.index("Uncategorized")
        assert uncategorized < text.index("Groceries", uncategorized)


@pytest.mark.db
class TestCategoryIsolation:
    """Another workspace's category ids behave as nonexistent."""

    def test_404_everywhere_and_nothing_changes(self, client, db_connection):
        Seed(db_connection)
        other = create_workspace(db_connection, USER_ID, "Other")
        theirs = create_category(db_connection, other.id, "Theirs")
        create_category(db_connection, other.id, "Second")
        login(client)
        base = f"{CATEGORIES}/{theirs.id}"
        assert client.post(base, data={"name": "Mine"}).status_code == 404
        assert (
            client.post(f"{base}/move", data={"direction": "down"}).status_code == 404
        )
        assert client.post(f"{base}/delete").status_code == 404
        d = drawer(client.get(f"{CATEGORIES}?confirm={theirs.id}").text)
        assert "Theirs" not in d
        listed = repo.get_cash_flow_categories(db_connection, other.id)
        assert [(c.name, c.position) for c in listed] == [("Theirs", 0), ("Second", 1)]

    def test_missing_category_is_404(self, client, seed):
        login(client)
        assert client.post(f"{CATEGORIES}/9999", data={"name": "X"}).status_code == 404
        assert (
            client.post(f"{CATEGORIES}/9999/move", data={"direction": "up"}).status_code
            == 404
        )
        assert client.post(f"{CATEGORIES}/9999/delete").status_code == 404


# --- roles -----------------------------------------------------------------------


@pytest.mark.db
class TestRoles:
    """The drawers exist only to write, so they are editor-only, like the
    new-account drawer; viewers see the page without the controls."""

    def test_viewers_cannot_open_or_post(self, client, db_connection, seed):
        add_user(db_connection, STRANGER, "viewer")
        session_for(client, STRANGER)
        gid, fid = seed.groceries.id, seed.food.id
        for path in (f"{PAGE}/new", f"{PAGE}/{gid}/edit", CATEGORIES):
            assert client.get(path).status_code == 403, path
        for path, data in (
            (PAGE, valid_form()),
            (f"{PAGE}/{gid}", valid_form()),
            (f"{PAGE}/{gid}/delete", {}),
            (CATEGORIES, {"name": "X"}),
            (f"{CATEGORIES}/{fid}", {"name": "X"}),
            (f"{CATEGORIES}/{fid}/move", {"direction": "up"}),
            (f"{CATEGORIES}/{fid}/delete", {}),
        ):
            assert client.post(path, data=data).status_code == 403, path
        assert len(repo.get_cash_flows(db_connection, WS)) == 8
        assert len(repo.get_cash_flow_categories(db_connection, WS)) == 5

    def test_editors_can_use_both_drawers(self, client, db_connection, seed):
        add_user(db_connection, STRANGER, "editor")
        session_for(client, STRANGER)
        assert client.get(f"{PAGE}/{seed.gas.id}/edit").status_code == 200
        assert client.get(CATEGORIES).status_code == 200
        response = client.post(PAGE, data=valid_form(), follow_redirects=False)
        assert response.status_code == 303
        html = client.get(PAGE).text
        assert "+ Add cash flow" in html and "/edit?per=" in html
