"""Pure tests for the dashboard's numbers and its Plotly figure."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from asset_manager.models import (
    Account,
    AccountCategory,
    ProportionalFormula,
    Record,
    RecordType,
)
from asset_manager.web.charts import build_figure
from asset_manager.web.dashboard import (
    Point,
    account_cards,
    change_since,
    computed_label,
    daily_totals,
    filter_range,
    latest_category_totals,
    long_date,
    money,
    months_before,
    parse_range,
    ramp_color,
    short_date,
    signed_money,
    signed_percent,
)

A, L = RecordType.ASSET, RecordType.LIABILITY
LATEST = date(2026, 10, 24)


def rec(day, account_id, amount, type=A, name=None):
    return Record(
        date=day,
        account_id=account_id,
        type=type,
        description=name or f"account {account_id}",
        amount=Decimal(amount),
    )


def pt(day, net_worth, liabilities="0"):
    """A point with the given net worth."""
    liab = Decimal(liabilities)
    return Point(day, Decimal(net_worth) + liab, liab)


def days_ago(n):
    return LATEST - timedelta(days=n)


class TestDailyTotals:
    def test_sums_each_date_by_type_oldest_first(self):
        records = [
            rec(date(2026, 2, 1), 1, "100"),
            rec(date(2026, 1, 1), 1, "50"),
            rec(date(2026, 1, 1), 2, "25"),
            rec(date(2026, 1, 1), 3, "30", L),
            rec(date(2026, 2, 1), 3, "40", L),
        ]
        assert daily_totals(records) == [
            Point(date(2026, 1, 1), Decimal("75"), Decimal("30")),
            Point(date(2026, 2, 1), Decimal("100"), Decimal("40")),
        ]

    def test_a_date_with_only_liabilities_has_zero_assets(self):
        [point] = daily_totals([rec(date(2026, 1, 1), 1, "10", L)])
        assert point.assets == 0
        assert point.net_worth == Decimal("-10")

    def test_empty(self):
        assert daily_totals([]) == []


class TestChangeSince:
    def test_no_snapshots_or_one_snapshot_has_no_change(self):
        assert change_since([]) is None
        assert change_since([pt(LATEST, "100")]) is None

    def test_picks_the_snapshot_closest_to_30_days_before_the_latest(self):
        points = [
            pt(days_ago(60), "50"),
            pt(days_ago(31), "80"),
            pt(days_ago(20), "90"),
            pt(LATEST, "100"),
        ]
        change = change_since(points)
        assert change is not None
        assert change.since == days_ago(31)
        assert change.amount == Decimal("20")
        assert change.percent == Decimal("25")

    def test_a_snapshot_exactly_30_days_back_wins(self):
        points = [pt(days_ago(32), "1"), pt(days_ago(30), "2"), pt(days_ago(28), "3")]
        change = change_since([*points, pt(LATEST, "10")])
        assert change is not None and change.since == days_ago(30)

    def test_closer_after_the_target_beats_further_before(self):
        points = [pt(days_ago(45), "1"), pt(days_ago(25), "2"), pt(LATEST, "3")]
        change = change_since(points)
        assert change is not None and change.since == days_ago(25)

    def test_a_gap_takes_whichever_side_is_closer(self):
        points = [pt(days_ago(100), "1"), pt(days_ago(5), "2"), pt(LATEST, "3")]
        change = change_since(points)
        assert change is not None and change.since == days_ago(5)
        points = [pt(days_ago(50), "1"), pt(days_ago(5), "2"), pt(LATEST, "3")]
        change = change_since(points)
        assert change is not None and change.since == days_ago(50)

    def test_nothing_that_far_back_uses_the_earliest(self):
        points = [pt(days_ago(12), "1"), pt(days_ago(3), "2"), pt(LATEST, "3")]
        change = change_since(points)
        assert change is not None and change.since == days_ago(12)

    def test_never_compares_the_latest_with_itself(self):
        """With one older snapshot far back, it is still the base, even
        though the latest itself is nearer the target."""
        change = change_since([pt(days_ago(100), "40"), pt(LATEST, "50")])
        assert change is not None
        assert change.since == days_ago(100)
        assert change.amount == Decimal("10")

    def test_a_tie_goes_to_the_older_snapshot(self):
        points = [pt(days_ago(35), "1"), pt(days_ago(25), "2"), pt(LATEST, "3")]
        change = change_since(points)
        assert change is not None and change.since == days_ago(35)

    def test_a_drop_is_negative(self):
        change = change_since([pt(days_ago(30), "200"), pt(LATEST, "150")])
        assert change is not None
        assert change.amount == Decimal("-50")
        assert change.percent == Decimal("-25")

    def test_zero_base_has_no_percent(self):
        change = change_since([pt(days_ago(30), "0"), pt(LATEST, "150")])
        assert change is not None
        assert change.amount == Decimal("150")
        assert change.percent is None

    def test_negative_base_keeps_the_sign_of_the_change(self):
        change = change_since([pt(days_ago(30), "-200"), pt(LATEST, "-100")])
        assert change is not None
        assert change.amount == Decimal("100")
        assert change.percent == Decimal("50")

    def test_uses_net_worth_not_assets(self):
        points = [pt(days_ago(30), "100", liabilities="900"), pt(LATEST, "110", "10")]
        change = change_since(points)
        assert change is not None and change.amount == Decimal("10")


class TestRanges:
    @pytest.mark.parametrize("value", ["6m", "1y", "all"])
    def test_valid_values_pass(self, value):
        assert parse_range(value) == value

    @pytest.mark.parametrize("value", [None, "", "6M", "1Y", "ALL", "2y", "3m", " 6m"])
    def test_anything_else_is_one_year(self, value):
        assert parse_range(value) == "1y"

    @pytest.mark.parametrize(
        "day, months, expected",
        [
            (date(2026, 10, 24), 6, date(2026, 4, 24)),
            (date(2026, 10, 24), 12, date(2025, 10, 24)),
            (date(2026, 3, 31), 1, date(2026, 2, 28)),
            (date(2024, 3, 31), 1, date(2024, 2, 29)),
            (date(2024, 2, 29), 12, date(2023, 2, 28)),
            (date(2026, 1, 15), 1, date(2025, 12, 15)),
            (date(2026, 8, 31), 6, date(2026, 2, 28)),
        ],
    )
    def test_months_before(self, day, months, expected):
        assert months_before(day, months) == expected

    def test_counts_back_from_the_latest_snapshot_inclusive(self):
        dates = [
            date(2025, 10, 23),
            date(2025, 10, 24),
            date(2026, 4, 23),
            date(2026, 4, 24),
            LATEST,
        ]
        points = [pt(d, "1") for d in dates]
        assert [p.date for p in filter_range(points, "1y")] == dates[1:]
        assert [p.date for p in filter_range(points, "6m")] == dates[3:]
        assert [p.date for p in filter_range(points, "all")] == dates

    def test_a_range_with_nothing_older_still_shows_the_latest(self):
        points = [pt(date(2020, 1, 1), "1"), pt(LATEST, "2")]
        assert [p.date for p in filter_range(points, "6m")] == [LATEST]

    def test_the_anchor_is_the_latest_snapshot_not_today(self):
        """A workspace last saved years ago still shows its last months."""
        old = [pt(date(2020, 1, 1), "1"), pt(date(2020, 3, 1), "2")]
        assert filter_range(old, "6m") == old

    def test_empty(self):
        assert filter_range([], "6m") == []
        assert filter_range([], "all") == []


def account(id, type=A, category=None, name=None, **kwargs):
    return Account(
        id=id, name=name or f"account {id}", type=type, category=category, **kwargs
    )


BANK = AccountCategory.BANK_ACCOUNTS
INVEST = AccountCategory.INVESTMENT_ACCOUNTS
CARDS = AccountCategory.CREDIT_CARDS
TAX = AccountCategory.TAX_LIABILITY


class TestLatestCategoryTotals:
    def test_splits_the_latest_snapshot_by_category_largest_first(self):
        accounts = [
            account(1, A, BANK),
            account(2, A, INVEST),
            account(3, A, INVEST),
            account(4, A, None),
            account(5, L, CARDS),
            account(6, L, TAX),
        ]
        old = days_ago(30)
        records = [
            rec(old, 1, "999999"),  # an older snapshot never counts
            rec(LATEST, 1, "100"),
            rec(LATEST, 2, "300"),
            rec(LATEST, 3, "200"),
            rec(LATEST, 4, "50"),
            rec(LATEST, 5, "40", L),
            rec(LATEST, 6, "70", L),
        ]
        totals = latest_category_totals(records, accounts)
        assert [(c.label, c.amount, c.color) for c in totals[A]] == [
            ("Investment Accounts", Decimal("500"), "var(--asset)"),
            ("Bank Accounts", Decimal("100"), "var(--asset-2)"),
            ("Uncategorized", Decimal("50"), ramp_color(A, 2)),
        ]
        assert [(c.label, c.amount, c.color) for c in totals[L]] == [
            ("Tax Liability", Decimal("70"), "var(--liability)"),
            ("Credit Cards", Decimal("40"), "var(--liability-2)"),
        ]

    def test_columns_add_up_to_where_the_lines_end(self):
        accounts = [account(1, A, BANK), account(2, A), account(3, L, CARDS)]
        records = [
            rec(days_ago(10), 1, "5"),
            rec(LATEST, 1, "10.25"),
            rec(LATEST, 2, "20.50"),
            rec(LATEST, 3, "7.10", L),
        ]
        totals = latest_category_totals(records, accounts)
        end = daily_totals(records)[-1]
        assert sum(c.amount for c in totals[A]) == end.assets
        assert sum(c.amount for c in totals[L]) == end.liabilities

    def test_zero_categories_are_left_out(self):
        accounts = [account(1, A, BANK), account(2, A, INVEST)]
        records = [rec(LATEST, 1, "0"), rec(LATEST, 2, "5")]
        totals = latest_category_totals(records, accounts)
        assert [c.label for c in totals[A]] == ["Investment Accounts"]
        assert totals[L] == []

    def test_a_tie_orders_by_name(self):
        accounts = [account(1, A, INVEST), account(2, A, BANK)]
        records = [rec(LATEST, 1, "5"), rec(LATEST, 2, "5")]
        labels = [c.label for c in latest_category_totals(records, accounts)[A]]
        assert labels == ["Bank Accounts", "Investment Accounts"]

    def test_an_unknown_account_counts_as_uncategorized(self):
        totals = latest_category_totals([rec(LATEST, 99, "5")], [])
        assert [c.label for c in totals[A]] == ["Uncategorized"]

    def test_no_records(self):
        assert latest_category_totals([], [account(1)]) == {A: [], L: []}


class TestRampColor:
    def test_ramps_start_with_the_tokens_in_order(self):
        assert [ramp_color(A, i) for i in range(2)] == [
            "var(--asset)",
            "var(--asset-2)",
        ]
        assert [ramp_color(L, i) for i in range(4)] == [
            "var(--liability)",
            "var(--liability-2)",
            "var(--liability-3)",
            "var(--liability-4)",
        ]

    def test_past_the_end_the_last_token_fades_toward_the_surface(self):
        third, fourth = ramp_color(A, 2), ramp_color(A, 3)
        assert third.startswith("color-mix(in srgb, var(--asset-2) ")
        assert third.endswith("var(--surface))")
        assert third != fourth
        assert "#" not in third
        assert ramp_color(L, 4).startswith("color-mix(in srgb, var(--liability-4) ")

    def test_each_extra_color_is_fainter(self):
        def share(css):
            return int(css.split(") ")[1].split("%")[0])

        shares = [share(ramp_color(A, i)) for i in range(2, 8)]
        assert shares == sorted(shares, reverse=True)
        assert all(s > 0 for s in shares)


class TestAccountCards:
    def test_lists_active_accounts_by_category_with_totals(self):
        accounts = [
            account(1, A, INVEST, "Schwab"),
            account(2, A, BANK, "Checking"),
            account(3, A, None, "House"),
            account(4, A, BANK, "Savings"),
            account(5, A, BANK, "Old", retired_at=date(2026, 1, 1)),
            account(6, L, CARDS, "Visa"),
        ]
        records = [
            rec(days_ago(30), 5, "1000"),
            rec(LATEST, 1, "300"),
            rec(LATEST, 2, "10"),
            rec(LATEST, 3, "500"),
            rec(LATEST, 4, "20"),
            rec(LATEST, 6, "40", L),
        ]
        cards = account_cards(records, accounts)
        assets = cards[A]
        assert [
            (g["label"], g["total"], [(r["name"], r["amount"]) for r in g["rows"]])
            for g in assets["groups"]
        ] == [
            (
                "Bank Accounts",
                Decimal("30"),
                [("Checking", Decimal("10")), ("Savings", Decimal("20"))],
            ),
            ("Investment Accounts", Decimal("300"), [("Schwab", Decimal("300"))]),
            ("Uncategorized", Decimal("500"), [("House", Decimal("500"))]),
        ]
        assert assets["total"] == Decimal("830")
        assert cards[L]["total"] == Decimal("40")
        assert [g["label"] for g in cards[L]["groups"]] == ["Credit Cards"]

    def test_retired_accounts_are_excluded_even_with_a_latest_row(self):
        accounts = [
            account(1, A, BANK, "Live"),
            account(2, A, BANK, "Gone", retired_at=LATEST),
        ]
        records = [rec(LATEST, 1, "5"), rec(LATEST, 2, "7")]
        cards = account_cards(records, accounts)
        [group] = cards[A]["groups"]
        assert [r["name"] for r in group["rows"]] == ["Live"]
        assert cards[A]["total"] == Decimal("5")

    def test_an_account_with_no_latest_row_shows_none_and_adds_nothing(self):
        accounts = [account(1, A, BANK, "Saved"), account(2, A, BANK, "New")]
        records = [rec(days_ago(40), 2, "999"), rec(LATEST, 1, "5")]
        cards = account_cards(records, accounts)
        [group] = cards[A]["groups"]
        assert [(r["name"], r["amount"]) for r in group["rows"]] == [
            ("Saved", Decimal("5")),
            ("New", None),
        ]
        assert group["total"] == Decimal("5")

    def test_computed_accounts_carry_a_label(self):
        formula = ProportionalFormula(rate=Decimal("0.15"), cost_basis=Decimal("1"))
        accounts = [account(1, L, TAX, "Tax", formula=formula, input_ids=[2])]
        cards = account_cards([rec(LATEST, 1, "3", L)], accounts)
        assert cards[L]["groups"][0]["rows"][0]["computed"] == "15% of gains, computed"

    def test_no_accounts_or_no_records(self):
        assert account_cards([], []) == {
            A: {"total": Decimal(0), "groups": []},
            L: {"total": Decimal(0), "groups": []},
        }
        cards = account_cards([], [account(1, A, BANK, "Cash")])
        assert cards[A]["groups"][0]["rows"][0]["amount"] is None


class TestFormatting:
    @pytest.mark.parametrize(
        "rate, expected",
        [("0.15", "15"), ("0.325", "32.5"), ("0", "0"), ("1", "100"), ("0.2", "20")],
    )
    def test_computed_label(self, rate, expected):
        formula = ProportionalFormula(rate=Decimal(rate))
        label = computed_label(account(1, L, formula=formula))
        assert label == f"{expected}% of gains, computed"
        assert computed_label(account(2)) is None

    @pytest.mark.parametrize(
        "amount, expected",
        [
            ("412380", "$412,380"),
            ("412380.49", "$412,380"),
            ("412380.50", "$412,381"),
            ("0", "$0"),
            ("-0.4", "$0"),
            ("-1200", "−$1,200"),
            ("1234567.89", "$1,234,568"),
        ],
    )
    def test_money(self, amount, expected):
        assert money(Decimal(amount)) == expected

    @pytest.mark.parametrize(
        "amount, expected",
        [
            ("6140", "+$6,140"),
            ("-1200", "−$1,200"),
            ("0", "$0"),
            ("0.4", "$0"),
            ("-0.4", "$0"),
        ],
    )
    def test_signed_money(self, amount, expected):
        assert signed_money(Decimal(amount)) == expected

    @pytest.mark.parametrize(
        "percent, expected",
        [
            ("1.5", "+1.5%"),
            ("1.46", "+1.5%"),
            ("-0.3", "−0.3%"),
            ("0", "0.0%"),
            ("0.04", "0.0%"),
            ("-0.04", "0.0%"),
            ("12", "+12.0%"),
        ],
    )
    def test_signed_percent(self, percent, expected):
        assert signed_percent(Decimal(percent)) == expected

    def test_dates(self):
        assert short_date(date(2026, 9, 4), LATEST) == "Sep 4"
        assert short_date(date(2025, 9, 24), LATEST) == "Sep 24, 2025"
        assert long_date(date(2026, 10, 4)) == "Oct 4, 2026"


class TestFigure:
    def figure(self, points=None, categories=None):
        points = points or [pt(days_ago(30), "90", "10"), pt(LATEST, "100", "20")]
        accounts = [account(1, A, BANK), account(2, A, INVEST), account(3, L, CARDS)]
        records = [
            rec(LATEST, 1, "40"),
            rec(LATEST, 2, "80"),
            rec(LATEST, 3, "20", L),
        ]
        if categories is None:
            categories = latest_category_totals(records, accounts)
        return build_figure(points, categories)

    def test_three_lines_on_the_first_x_axis(self):
        fig = self.figure()
        lines = [t for t in fig["data"] if t["type"] == "scatter"]
        assert [(t["name"], t["meta"]["color"]) for t in lines] == [
            ("Assets", "var(--asset)"),
            ("Net worth", "var(--ink)"),
            ("Liabilities", "var(--liability)"),
        ]
        assert all(t["xaxis"] == "x" and t["yaxis"] == "y" for t in lines)
        assert lines[0]["y"] == [100.0, 120.0]
        assert lines[1]["y"] == [90.0, 100.0]
        assert lines[2]["y"] == [10.0, 20.0]
        assert lines[0]["x"] == [days_ago(30).isoformat(), LATEST.isoformat()]
        assert lines[1]["line"]["width"] > lines[0]["line"]["width"]
        assert lines[1]["line"]["width"] > lines[2]["line"]["width"]

    def test_columns_share_the_y_axis_on_a_second_x_axis(self):
        fig = self.figure()
        bars = [t for t in fig["data"] if t["type"] == "bar"]
        assert [(t["x"], t["name"], t["y"], t["meta"]["color"]) for t in bars] == [
            (["Assets"], "Investment Accounts", [80.0], "var(--asset)"),
            (["Assets"], "Bank Accounts", [40.0], "var(--asset-2)"),
            (["Liabilities"], "Credit Cards", [20.0], "var(--liability)"),
        ]
        assert all(t["xaxis"] == "x2" and t["yaxis"] == "y" for t in bars)
        assert all(t["meta"]["gap"] == "var(--surface)" for t in bars)
        layout = fig["layout"]
        assert layout["barmode"] == "stack"
        assert layout["xaxis2"]["anchor"] == "y"
        assert "yaxis2" not in layout

    def test_the_domains_do_not_overlap_and_the_divider_sits_between(self):
        layout = self.figure()["layout"]
        lines, columns = layout["xaxis"]["domain"], layout["xaxis2"]["domain"]
        [divider] = layout["shapes"]
        assert lines[0] == 0 and columns[1] == 1
        assert lines[1] < divider["x0"] == divider["x1"] < columns[0]
        assert divider["line"]["dash"] == "dash"
        narrow = layout["meta"]["narrow"]
        assert narrow["lines"][1] < narrow["divider"] < narrow["columns"][0]

    def test_the_y_axis_includes_zero(self):
        assert self.figure()["layout"]["yaxis"]["rangemode"] == "tozero"

    def test_a_single_point_gets_a_marker(self):
        fig = self.figure(points=[pt(LATEST, "1")])
        modes = {t["mode"] for t in fig["data"] if t["type"] == "scatter"}
        assert modes == {"lines+markers"}
        assert {t["mode"] for t in self.figure()["data"] if t["type"] == "scatter"} == {
            "lines"
        }

    def test_no_categories_means_no_columns(self):
        fig = self.figure(categories={A: [], L: []})
        assert [t["type"] for t in fig["data"]] == ["scatter"] * 3

    def test_every_color_is_named_by_a_token(self):
        fig = self.figure()
        for trace in fig["data"]:
            assert trace["meta"]["color"].startswith(("var(--", "color-mix("))
        for value in fig["layout"]["meta"].values():
            if isinstance(value, str):
                assert value.startswith("var(--")
