"""The eight MCP tools as plain functions, against the test database."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from sensibility import clock
from sensibility.accounts import create_account, retire_account, save_snapshot
from sensibility.cashflows import Period, create_cash_flow
from sensibility.cashflows import create_category as create_flow_category
from sensibility.config import get_settings
from sensibility.mcp import tools
from sensibility.mcp.tools import FormulaInput, ToolFailure
from sensibility.models import (
    AccountCategory,
    CashFlow,
    CashFlowDirection,
    FrequencyUnit,
    ProportionalFormula,
    RecordType,
)
from sensibility.repository import (
    get_account,
    get_all_records,
    get_cash_flow_categories,
    get_cash_flows,
)
from sensibility.web.cash_flows_routes import cash_flows_view as page_view
from tests.mcp_support import caller
from tests.support import WS
from tests.web_support import STRANGER, add_user

pytestmark = pytest.mark.db

# 1 PM in Chicago (the default zone) on Oct 27, 2026; already Oct 28 in Tokyo.
NOW = datetime(2026, 10, 27, 18, 0, tzinfo=UTC)
TODAY = date(2026, 10, 27)
ASSET, LIABILITY = RecordType.ASSET, RecordType.LIABILITY
ME = caller()
READ_ONLY = caller(scopes=("sensibility:read",))


@pytest.fixture(autouse=True)
def frozen(monkeypatch, db_url):
    monkeypatch.setenv("DATABASE_URL", db_url)
    get_settings.cache_clear()
    monkeypatch.setattr(clock, "now", lambda: NOW)
    yield
    get_settings.cache_clear()


@pytest.fixture
def ids(db_connection) -> dict[str, int]:
    """Five accounts and three snapshots in workspace WS.

    Tax on gains = 15% × (Schwab + Fidelity − 1000).
    Aug 31: Checking 1000, Schwab 5000, Fidelity 3000, Visa 200 (tax 1050)
    Sep 27: Checking 1500, Schwab 5500, Fidelity 3000, Visa 300 (tax 1125)
    Oct 20: Checking 2000, Schwab 6000, Fidelity 3500, Visa 250 (tax 1275)
    """
    conn = db_connection
    bank = AccountCategory.BANK_ACCOUNTS
    invest = AccountCategory.INVESTMENT_ACCOUNTS
    made = {
        "Checking": create_account(conn, WS, "Checking", ASSET, category=bank),
        "Schwab": create_account(conn, WS, "Schwab", ASSET, category=invest),
        "Fidelity": create_account(conn, WS, "Fidelity", ASSET, category=invest),
        "Visa": create_account(
            conn, WS, "Visa", LIABILITY, category=AccountCategory.CREDIT_CARDS
        ),
    }
    made["Tax on gains"] = create_account(
        conn,
        WS,
        "Tax on gains",
        LIABILITY,
        ProportionalFormula(rate=Decimal("0.15"), cost_basis=Decimal("1000")),
        [made["Schwab"].id, made["Fidelity"].id],  # type: ignore[list-item]
        AccountCategory.TAX_LIABILITY,
    )
    result = {name: a.id for name, a in made.items()}
    for day, values in [
        (date(2026, 8, 31), (1000, 5000, 3000, 200)),
        (date(2026, 9, 27), (1500, 5500, 3000, 300)),
        (date(2026, 10, 20), (2000, 6000, 3500, 250)),
    ]:
        names = ["Checking", "Schwab", "Fidelity", "Visa"]
        save_snapshot(
            conn,
            WS,
            {result[n]: Decimal(v) for n, v in zip(names, values)},
            {},
            day,
        )
    return result  # type: ignore[return-value]


def second_workspace(conn, role: str = "owner", name: str = "Other") -> int:
    with conn.cursor() as cur:
        cur.execute("INSERT INTO workspaces (name) VALUES (%s) RETURNING id", (name,))
        row = cur.fetchone()
        assert row is not None
        cur.execute(
            "INSERT INTO workspace_members (workspace_id, user_id, role) "
            "VALUES (%s, 1, %s)",
            (row[0], role),
        )
    conn.commit()
    return row[0]


def accounts_of(result) -> dict[str, dict]:
    return {
        a.name: a.model_dump(mode="json")
        for side in (result.assets, result.liabilities)
        for g in side.categories
        for a in g.accounts
    }


def failure(fn, *args, **kwargs) -> str:
    with pytest.raises(ToolFailure) as caught:
        fn(*args, **kwargs)
    return str(caught.value)


# --- workspaces ---------------------------------------------------------------


class TestWorkspaces:
    def test_list_workspaces(self, db_connection, ids):
        second_workspace(db_connection, "viewer")
        result = tools.list_workspaces(db_connection, ME)
        assert [w.model_dump(mode="json") for w in result.workspaces] == [
            {
                "name": "Test",
                "role": "owner",
                "latest_snapshot": "2026-10-20",
                "net_worth": "9975.00",
            },
            {
                "name": "Other",
                "role": "viewer",
                "latest_snapshot": None,
                "net_worth": None,
            },
        ]
        assert result.summary().startswith(
            "2 workspaces: Test (owner; net worth $9,975.00"
        )

    def test_the_only_workspace_needs_no_name(self, db_connection, ids):
        assert tools.get_balances(db_connection, ME).workspace == "Test"

    def test_names_match_case_insensitively(self, db_connection, ids):
        second_workspace(db_connection)
        assert (
            tools.get_balances(db_connection, ME, workspace=" test ").workspace
            == "Test"
        )

    def test_several_workspaces_need_a_name(self, db_connection, ids):
        second_workspace(db_connection)
        message = failure(tools.get_balances, db_connection, ME)
        assert message == (
            "You belong to 2 workspaces, so say which with `workspace`: "
            "'Test' or 'Other'."
        )

    def test_unknown_workspace_lists_candidates(self, db_connection, ids):
        second_workspace(db_connection, name="Household")
        message = failure(tools.get_balances, db_connection, ME, workspace="House")
        assert message == "No workspace named 'House'. Did you mean 'Household'?"
        message = failure(tools.get_balances, db_connection, ME, workspace="zzz")
        assert message == (
            "No workspace named 'zzz'. The workspaces are: 'Household', 'Test'."
        )

    def test_ambiguous_workspace(self, db_connection, ids):
        second_workspace(db_connection, name="test")
        message = failure(tools.get_balances, db_connection, ME, workspace="TEST")
        assert "2 of your workspaces are named" in message

    def test_another_users_workspace_is_unknown(self, db_connection, ids):
        add_user(db_connection, STRANGER)
        stranger = caller(STRANGER)
        assert "not a member of any workspace" in failure(
            tools.get_balances, db_connection, stranger
        )
        assert tools.list_workspaces(db_connection, stranger).workspaces == []


# --- get_balances ---------------------------------------------------------------


class TestGetBalances:
    def test_latest_snapshot(self, db_connection, ids):
        result = tools.get_balances(db_connection, ME)
        assert result.as_of == date(2026, 10, 20)
        assert result.days_since == 7
        assert result.net_worth == "9975.00"
        # The dashboard's change: the snapshot closest to 30 days back.
        assert result.change is not None
        assert result.change.model_dump(mode="json") == {
            "since": "2026-09-27",
            "amount": "1400.00",
            "percent": "16.3",
        }
        assert result.assets.total == "11500.00"
        assert result.liabilities.total == "1525.00"
        assert [
            (g.category, g.total, [a.name for a in g.accounts])
            for g in result.assets.categories + result.liabilities.categories
        ] == [
            ("Bank Accounts", "2000.00", ["Checking"]),
            ("Investment Accounts", "9500.00", ["Fidelity", "Schwab"]),
            ("Credit Cards", "250.00", ["Visa"]),
            ("Tax Liability", "1275.00", ["Tax on gains"]),
        ]
        tax = accounts_of(result)["Tax on gains"]
        assert tax == {
            "name": "Tax on gains",
            "type": "liability",
            "category": "Tax Liability",
            "amount": "1275.00",
            "computed": True,
            "formula": {
                "kind": "proportional",
                "rate_percent": "15",
                "cost_basis": "1000.00",
                "inputs": ["Schwab", "Fidelity"],
                "text": "15% × (Schwab + Fidelity − basis)",
            },
            "retired_on": None,
            "source": None,
        }
        assert result.summary() == (
            "Test: net worth $9,975.00 on 2026-10-20 (7 days ago); assets "
            "$11,500.00, liabilities $1,525.00. +$1,400.00 (+16.3%) since 2026-09-27."
        )

    def test_days_since_is_in_the_given_zone(self, db_connection, ids):
        result = tools.get_balances(db_connection, ME, timezone="Asia/Tokyo")
        assert result.days_since == 8

    def test_unknown_zone(self, db_connection, ids):
        message = failure(tools.get_balances, db_connection, ME, timezone="Mars/Base")
        assert "'Mars/Base' is not a known time zone" in message

    def test_retired_accounts_are_left_out(self, db_connection, ids):
        retire_account(db_connection, WS, ids["Visa"], date(2026, 10, 21))
        assert "Visa" not in accounts_of(tools.get_balances(db_connection, ME))

    def test_no_snapshot_yet(self, db_connection):
        create_account(db_connection, WS, "Cash", ASSET)
        result = tools.get_balances(db_connection, ME)
        assert (result.as_of, result.net_worth, result.change) == (None, None, None)
        assert accounts_of(result)["Cash"]["amount"] is None
        assert "no snapshot yet" in result.summary()

    def test_viewers_read(self, db_connection, ids):
        add_user(db_connection, STRANGER, "viewer")
        result = tools.get_balances(
            db_connection, caller(STRANGER, ["sensibility:read"])
        )
        assert result.net_worth == "9975.00"


# --- get_history ------------------------------------------------------------------


class TestGetHistory:
    @pytest.fixture
    def more(self, db_connection, ids):
        """An extra Oct 5 snapshot, and Visa retired after Oct 20 with an Oct
        25 snapshot."""
        values = {
            ids[n]: Decimal(v)
            for n, v in [
                ("Checking", 1800),
                ("Schwab", 5800),
                ("Fidelity", 3200),
                ("Visa", 100),
            ]
        }
        save_snapshot(db_connection, WS, values, {}, date(2026, 10, 5))
        retire_account(db_connection, WS, ids["Visa"], date(2026, 10, 21))
        save_snapshot(
            db_connection,
            WS,
            {ids["Checking"]: Decimal(2200)},
            {},
            date(2026, 10, 25),
            carry_forward=True,
        )
        return ids

    def rows(self, result):
        return [(r.period, r.date.isoformat(), r.net_worth) for r in result.rows]

    def test_month_takes_each_months_last_snapshot(self, db_connection, more):
        result = tools.get_history(db_connection, ME)
        assert self.rows(result) == [
            ("2026-08", "2026-08-31", "7750.00"),
            ("2026-09", "2026-09-27", "8575.00"),
            ("2026-10", "2026-10-25", "10425.00"),
        ]
        # The default range: a year back from the latest snapshot.
        assert (result.start, result.end) == (date(2025, 10, 25), date(2026, 10, 25))

    def test_snapshot_quarter_year(self, db_connection, more):
        snapshot = tools.get_history(db_connection, ME, interval="snapshot")
        assert [r.period for r in snapshot.rows] == [
            "2026-08-31",
            "2026-09-27",
            "2026-10-05",
            "2026-10-20",
            "2026-10-25",
        ]
        quarter = tools.get_history(db_connection, ME, interval="quarter")
        assert self.rows(quarter) == [
            ("2026-Q3", "2026-09-27", "8575.00"),
            ("2026-Q4", "2026-10-25", "10425.00"),
        ]
        year = tools.get_history(db_connection, ME, interval="year")
        assert self.rows(year) == [("2026", "2026-10-25", "10425.00")]

    def test_start_and_end(self, db_connection, more):
        result = tools.get_history(
            db_connection, ME, start=date(2026, 9, 1), end=date(2026, 10, 19)
        )
        assert self.rows(result) == [
            ("2026-09", "2026-09-27", "8575.00"),
            ("2026-10", "2026-10-05", "9500.00"),
        ]
        assert "start (2026-10-19) is after end" in failure(
            tools.get_history,
            db_connection,
            ME,
            start=date(2026, 10, 19),
            end=date(2026, 9, 1),
        )

    def test_named_accounts_and_a_retired_series_ending(self, db_connection, more):
        result = tools.get_history(
            db_connection, ME, interval="snapshot", accounts=["visa", "Tax on gains"]
        )
        assert [r.accounts for r in result.rows][-3:] == [
            {"Visa": "100.00", "Tax on gains": "1200.00"},
            {"Visa": "250.00", "Tax on gains": "1275.00"},
            {"Visa": None, "Tax on gains": "1275.00"},
        ]
        assert result.rows[-1].liabilities == "1275.00"

    def test_unknown_account(self, db_connection, ids):
        message = failure(tools.get_history, db_connection, ME, accounts=["Fidelty"])
        assert message == "No account named 'Fidelty'. Did you mean 'Fidelity'?"

    def test_no_snapshots(self, db_connection):
        result = tools.get_history(db_connection, ME)
        assert result.rows == []
        assert result.summary() == "Test has no snapshots yet."


# --- get_cash_flows -----------------------------------------------------------------


def seed_flows(conn) -> None:
    housing = create_flow_category(conn, WS, "Housing")
    food = create_flow_category(conn, WS, "Food")
    income, expense = CashFlowDirection.INCOME, CashFlowDirection.EXPENSE
    for flow in [
        CashFlow(
            name="Salary",
            direction=income,
            amount=Decimal("5100"),
            every=2,
            unit=FrequencyUnit.WEEK,
        ),
        CashFlow(
            name="Mortgage",
            direction=expense,
            amount=Decimal("2450"),
            unit=FrequencyUnit.MONTH,
            category_id=housing.id,
        ),
        CashFlow(
            name="Groceries",
            direction=expense,
            amount=Decimal("150"),
            unit=FrequencyUnit.WEEK,
            category_id=food.id,
            is_estimate=True,
            description="Roughly",
        ),
        CashFlow(
            name="Car insurance",
            direction=expense,
            amount=Decimal("1140"),
            every=6,
            unit=FrequencyUnit.MONTH,
        ),
    ]:
        create_cash_flow(conn, WS, flow)


def plain(text: str | None) -> str | None:
    """A page amount as a decimal string: "−$1,234.56" -> "-1234.56"."""
    if text is None:
        return None
    return text.replace("−", "-").replace("$", "").replace(",", "")


class TestGetCashFlows:
    @pytest.mark.parametrize("per", ["day", "month", "year"])
    def test_matches_the_page(self, db_connection, per):
        seed_flows(db_connection)
        result = tools.get_cash_flows(db_connection, ME, per=per)
        page = page_view(
            get_cash_flows(db_connection, WS),
            get_cash_flow_categories(db_connection, WS),
            Period(per),
        )
        assert result.income == plain(page["income"])
        assert result.expenses == plain(page["expenses"])
        assert result.left_over == plain(page["net"]).lstrip("+")
        assert result.expenses_share == page["expenses_share"]
        assert result.estimates == page["estimates"]
        cards = page["cards"][1:]
        assert [(c.name, c.total) for c in result.expense_categories] == [
            (c["name"], plain(c["total"])) for c in cards
        ]
        assert [c.share_of_income for c in result.expense_categories] == [
            c["note"].removesuffix(" of income") for c in cards
        ]
        assert [
            (f.name, f.per_period) for c in result.expense_categories for f in c.flows
        ] == [(r["name"], plain(r["value"])) for c in cards for r in c["rows"]]

    def test_month(self, db_connection):
        seed_flows(db_connection)
        result = tools.get_cash_flows(db_connection, ME)
        assert (result.income, result.expenses, result.left_over) == (
            "11080.36",
            "3291.79",
            "7788.57",
        )
        groceries = result.expense_categories[1].flows[0]
        assert groceries.model_dump(mode="json") == {
            "name": "Groceries",
            "direction": "expense",
            "amount": "150.00",
            "every": 1,
            "unit": "week",
            "every_text": "every week",
            "per_period": "651.79",
            "category": "Food",
            "note": "Roughly",
            "estimate": True,
        }
        assert [c.name for c in result.expense_categories] == [
            "Housing",
            "Food",
            "Uncategorized",
        ]
        assert result.summary() == (
            "Per month: income $11,080.36, expenses $3,291.79 (30% of income), "
            "$7,788.57 left over."
        )

    def test_empty(self, db_connection):
        result = tools.get_cash_flows(db_connection, ME)
        assert result.summary() == "Test has no cash flows yet."
        assert result.expenses_share is None


# --- update_balances ------------------------------------------------------------------


class TestUpdateBalances:
    def test_saves_today_with_sources(self, db_connection, ids):
        result = tools.update_balances(
            db_connection, ME, {"checking": "2,100", "VISA": 260}
        )
        assert result.saved and not result.replaced
        assert result.date == TODAY
        assert result.before is not None
        assert result.before.model_dump(mode="json") == {
            "date": "2026-10-20",
            "net_worth": "9975.00",
        }
        assert result.balances.net_worth == "10065.00"
        assert result.balances.days_since == 0
        sources = {n: a["source"] for n, a in accounts_of(result.balances).items()}
        assert sources == {
            "Checking": "updated",
            "Visa": "updated",
            "Schwab": "carried_forward",
            "Fidelity": "carried_forward",
            "Tax on gains": "computed",
        }
        saved = {
            r.description: r.amount
            for r in get_all_records(db_connection, WS)
            if r.date == TODAY
        }
        assert saved["Checking"] == Decimal("2100") and len(saved) == 5
        assert result.summary() == (
            "Saved the snapshot for 2026-10-27: net worth went from $9,975.00 "
            "(2026-10-20) to $10,065.00 (2 updated, 2 carried forward, 1 computed)."
        )

    def test_preview_saves_nothing(self, db_connection, ids):
        result = tools.update_balances(
            db_connection,
            ME,
            {"Checking": 2100},
            cost_bases={"Tax on gains": 2000},
            preview=True,
        )
        assert not result.saved
        # Tax = 15% × (9500 − 2000) = 1125, with the new basis shown.
        tax = accounts_of(result.balances)["Tax on gains"]
        assert tax["amount"] == "1125.00"
        assert tax["formula"]["cost_basis"] == "2000.00"
        assert result.balances.net_worth == "10225.00"
        assert result.summary().startswith(
            "Preview, nothing saved: net worth would go from $9,975.00 (2026-10-20) "
            "to $10,225.00 on 2026-10-27"
        )
        assert max(r.date for r in get_all_records(db_connection, WS)) == date(
            2026, 10, 20
        )
        tax_account = get_account(db_connection, WS, ids["Tax on gains"])
        assert tax_account is not None and tax_account.formula is not None
        assert tax_account.formula.cost_basis == Decimal("1000")

    def test_second_save_today_needs_overwrite(self, db_connection, ids):
        tools.update_balances(db_connection, ME, {"Checking": 2100})
        message = failure(tools.update_balances, db_connection, ME, {"Checking": 2200})
        assert message.startswith(
            "'Test' already has a snapshot for today (2026-10-27), saved at "
        )
        assert "net worth $10,075.00" in message
        assert "Checking $2,100.00" in message
        assert "overwrite: true" in message
        # A preview works either way, and says it would replace.
        preview = tools.update_balances(
            db_connection, ME, {"Checking": 2200}, preview=True
        )
        assert preview.replaced and preview.balances.net_worth == "10175.00"
        saved = tools.update_balances(
            db_connection, ME, {"Checking": 2200}, overwrite=True
        )
        assert saved.replaced and saved.balances.net_worth == "10175.00"
        assert "replaces the earlier save" in saved.summary()

    def test_already_saved_time_is_in_the_zone(self, db_connection, ids, monkeypatch):
        tools.update_balances(db_connection, ME, {"Checking": 2100})
        with db_connection.cursor() as cur:
            cur.execute(
                "UPDATE snapshots SET created_at = %s WHERE date = %s",
                (datetime(2026, 10, 27, 14, 5, tzinfo=UTC), TODAY),
            )
        db_connection.commit()
        message = failure(tools.update_balances, db_connection, ME, {"Checking": 1})
        assert "saved at 9:05 AM CDT" in message

    def test_today_is_in_the_given_zone(self, db_connection, ids):
        result = tools.update_balances(
            db_connection, ME, {"Checking": 1}, timezone="Asia/Tokyo"
        )
        assert result.date == date(2026, 10, 28)

    def test_computed_account_says_what_to_set(self, db_connection, ids):
        message = failure(tools.update_balances, db_connection, ME, {"Tax on gains": 5})
        assert message == (
            "'Tax on gains' is computed (15% × (Schwab + Fidelity − basis)), so it "
            "cannot be set directly. Set its inputs (Schwab, Fidelity) in balances, "
            "or its cost basis in cost_bases, instead."
        )

    def test_every_bad_name_is_reported(self, db_connection, ids):
        message = failure(
            tools.update_balances, db_connection, ME, {"Chekcing": 1, "Amex": 2}
        )
        assert "No account named 'Chekcing'. Did you mean 'Checking'?" in message
        assert "No account named 'Amex'. The accounts are: 'Checking'," in message
        assert get_all_records(db_connection, WS)[-1].date == date(2026, 10, 20)

    def test_retired_and_not_computed(self, db_connection, ids):
        retire_account(db_connection, WS, ids["Visa"], date(2026, 10, 21))
        assert "'Visa' is retired" in failure(
            tools.update_balances, db_connection, ME, {"Visa": 1}
        )
        assert "'Checking' is not a computed account" in failure(
            tools.update_balances, db_connection, ME, {}, cost_bases={"Checking": 1}
        )

    def test_bad_amount(self, db_connection, ids):
        assert "Checking: 'lots' is not a number" in failure(
            tools.update_balances, db_connection, ME, {"Checking": "lots"}
        )

    def test_service_errors_save_nothing(self, db_connection, ids):
        # An account with no row on the latest snapshot must be sent.
        create_account(db_connection, WS, "New", ASSET)
        message = failure(tools.update_balances, db_connection, ME, {"Checking": 1})
        assert message == "Missing value for New. Nothing was saved."

    def test_viewers_cannot_save(self, db_connection, ids):
        add_user(db_connection, STRANGER, "viewer")
        message = failure(
            tools.update_balances, db_connection, caller(STRANGER), {"Checking": 1}
        )
        assert message == (
            "You are a viewer in 'Test', and this needs the editor role. An owner "
            "of 'Test' can change your role in its settings."
        )

    def test_read_scope_cannot_save(self, db_connection, ids):
        assert "can only read" in failure(
            tools.update_balances, db_connection, READ_ONLY, {"Checking": 1}
        )


# --- save_cash_flow / delete_cash_flow --------------------------------------------------


class TestCashFlowWrites:
    def test_create_with_a_new_category(self, db_connection):
        seed_flows(db_connection)
        result = tools.save_cash_flow(
            db_connection,
            ME,
            "Flights",
            amount=2400,
            direction="expense",
            unit="year",
            category="Travel",
            estimate=True,
        )
        assert result.action == "created"
        assert result.created_category == "Travel"
        assert result.flow.per_period == "200.00"
        assert result.flow.category == "Travel"
        assert "Travel" in [c.name for c in result.cash_flows.expense_categories]
        assert "Created the category 'Travel'." in result.summary()

    def test_update_by_name(self, db_connection):
        seed_flows(db_connection)
        result = tools.save_cash_flow(
            db_connection, ME, "mortgage", amount="2500", category="food", note=""
        )
        assert result.action == "updated"
        assert result.created_category is None
        assert (result.flow.name, result.flow.amount, result.flow.category) == (
            "Mortgage",
            "2500.00",
            "Food",
        )
        result = tools.save_cash_flow(db_connection, ME, "Groceries", note="")
        assert result.flow.note is None
        result = tools.save_cash_flow(db_connection, ME, "Mortgage", category="")
        assert result.flow.category is None

    def test_rename(self, db_connection):
        seed_flows(db_connection)
        result = tools.save_cash_flow(db_connection, ME, "Salary", new_name="Pay")
        assert result.flow.name == "Pay"
        assert "No cash flow named 'Bonus'" in failure(
            tools.save_cash_flow, db_connection, ME, "Bonus", new_name="X"
        )

    def test_create_needs_amount_direction_and_unit(self, db_connection):
        seed_flows(db_connection)
        message = failure(
            tools.save_cash_flow, db_connection, ME, "Mortgage payment", amount=100
        )
        assert message == (
            "There is no cash flow named 'Mortgage payment' yet. To create it, also "
            "give direction, unit. To change an existing one, did you mean 'Mortgage'?"
        )

    def test_nothing_to_change(self, db_connection):
        seed_flows(db_connection)
        assert "Nothing to change in 'Salary'" in failure(
            tools.save_cash_flow, db_connection, ME, "Salary"
        )

    def test_a_refused_flow_leaves_no_new_category(self, db_connection):
        message = failure(
            tools.save_cash_flow,
            db_connection,
            ME,
            "Gift",
            amount=-5,
            direction="expense",
            unit="year",
            category="Presents",
        )
        assert message == (
            "Amount cannot be negative; set the direction to expense instead. "
            "Nothing was saved."
        )
        assert get_cash_flow_categories(db_connection, WS) == []
        assert "Every must be between 1 and 1000" in failure(
            tools.save_cash_flow,
            db_connection,
            ME,
            "Gift",
            amount=5,
            direction="expense",
            unit="year",
            every=0,
        )

    def test_delete(self, db_connection):
        seed_flows(db_connection)
        result = tools.delete_cash_flow(db_connection, ME, "car INSURANCE")
        assert result.deleted == "Car insurance"
        assert [c.name for c in result.cash_flows.expense_categories] == [
            "Housing",
            "Food",
        ]
        assert "Did you mean 'Car insurance'?" not in failure(
            tools.delete_cash_flow, db_connection, ME, "Car insurance"
        )
        assert failure(tools.delete_cash_flow, db_connection, ME, "Grocery") == (
            "No cash flow named 'Grocery'. Did you mean 'Groceries'?"
        )

    def test_viewers_and_read_scope_cannot_write(self, db_connection):
        seed_flows(db_connection)
        add_user(db_connection, STRANGER, "viewer")
        assert "needs the editor role" in failure(
            tools.delete_cash_flow, db_connection, caller(STRANGER), "Salary"
        )
        assert "can only read" in failure(
            tools.save_cash_flow, db_connection, READ_ONLY, "Salary", amount=1
        )
        assert len(get_cash_flows(db_connection, WS)) == 4


# --- save_account -------------------------------------------------------------------------


class TestSaveAccount:
    def test_create(self, db_connection, ids):
        result = tools.save_account(
            db_connection, ME, "Savings", type="asset", category="bank accounts"
        )
        assert result.actions == ["created"]
        assert result.account.model_dump(mode="json") == {
            "name": "Savings",
            "type": "asset",
            "category": "Bank Accounts",
            "amount": None,
            "computed": False,
            "formula": None,
            "retired_on": None,
            "source": None,
        }

    def test_create_needs_a_type(self, db_connection, ids):
        assert failure(tools.save_account, db_connection, ME, "Savings") == (
            "There is no account named 'Savings'. To create it, give type (asset "
            "or liability)."
        )

    def test_create_computed(self, db_connection, ids):
        result = tools.save_account(
            db_connection,
            ME,
            "State tax",
            type="liability",
            formula=FormulaInput(rate_percent="4.95", inputs=["schwab"]),
        )
        assert result.account.formula is not None
        assert result.account.formula.text == "4.95% × (Schwab − basis)"
        assert result.account.formula.cost_basis == "0.00"
        assert "is computed and cannot be an input" in failure(
            tools.save_account,
            db_connection,
            ME,
            "Bad",
            type="liability",
            formula=FormulaInput(rate_percent=1, inputs=["Tax on gains"]),
        )

    def test_update(self, db_connection, ids):
        result = tools.save_account(
            db_connection, ME, "checking", new_name="Joint checking", category=""
        )
        assert result.actions == ["updated"]
        assert (result.account.name, result.account.category) == (
            "Joint checking",
            None,
        )
        assert result.account.amount == "2000.00"
        # Changing the formula keeps the basis unless one is given.
        result = tools.save_account(
            db_connection,
            ME,
            "Tax on gains",
            formula=FormulaInput(rate_percent=20, inputs=["Schwab"]),
        )
        assert result.account.formula is not None
        assert (
            result.account.formula.rate_percent,
            result.account.formula.cost_basis,
        ) == (
            "20",
            "1000.00",
        )
        result = tools.save_account(db_connection, ME, "Tax on gains", make_plain=True)
        assert result.account.computed is False

    def test_retire_blocked_by_a_computed_account(self, db_connection, ids):
        message = failure(
            tools.save_account,
            db_connection,
            ME,
            "Schwab",
            retired=True,
            new_name="Renamed",
        )
        assert (
            message == "Schwab is an input to Tax on gains. Retire or edit those first."
        )
        schwab = get_account(db_connection, WS, ids["Schwab"])
        assert schwab is not None and schwab.is_active and schwab.name == "Schwab"

    def test_retire_warns_about_a_last_value(self, db_connection, ids):
        result = tools.save_account(db_connection, ME, "Checking", retired=True)
        assert result.actions == ["retired"]
        assert result.account.retired_on == TODAY
        assert result.warnings == [
            "Last saved at $2,000.00 on October 20, 2026. Retiring stops counting "
            "it from the next snapshot on. History is kept."
        ]
        assert "already retired" in failure(
            tools.save_account, db_connection, ME, "Checking", retired=True
        )
        result = tools.save_account(db_connection, ME, "Checking", retired=False)
        assert result.actions == ["unretired"] and result.account.retired_on is None

    def test_asset_and_liability_sharing_a_name(self, db_connection, ids):
        result = tools.save_account(db_connection, ME, "Checking", type="liability")
        assert result.warnings and "separate account" in result.warnings[0]
        assert "names both an asset and a liability" in failure(
            tools.save_account, db_connection, ME, "Checking", category=""
        )
        result = tools.save_account(
            db_connection, ME, "Checking (liability)", category="Credit Cards"
        )
        assert (result.account.type, result.account.category) == (
            "liability",
            "Credit Cards",
        )

    def test_bad_category(self, db_connection, ids):
        assert "'Cash' is not a category. Use one of Bank Accounts" in failure(
            tools.save_account, db_connection, ME, "Checking", category="Cash"
        )

    def test_nothing_to_change(self, db_connection, ids):
        assert "Nothing to change in 'Checking'" in failure(
            tools.save_account, db_connection, ME, "Checking"
        )

    def test_viewers_cannot_write(self, db_connection, ids):
        add_user(db_connection, STRANGER, "viewer")
        assert "needs the editor role" in failure(
            tools.save_account,
            db_connection,
            caller(STRANGER),
            "Checking",
            retired=True,
        )


def test_tool_sets_cover_the_registered_tools():
    from sensibility.mcp.server import server

    import anyio

    names = {t.name for t in anyio.run(server.list_tools)}
    assert names == tools.READ_TOOLS | tools.WRITE_TOOLS
    assert not tools.READ_TOOLS & tools.WRITE_TOOLS
