"""What the MCP tools return: structured results (each tool's output
schema) and the short text summary that goes beside them.

Money is a decimal string with two places ("12400.00", "-17.44"); dates are
ISO dates. A write returns its outcome in the matching read tool's shape, so
an agent needs no follow-up read.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

Money = str
Source = Literal["updated", "carried_forward", "computed"]


class ToolResult(BaseModel):
    """A tool's structured result, with a one-line summary for the text
    content beside it."""

    def summary(self) -> str:
        raise NotImplementedError


def dollars(amount: Money | Decimal) -> str:
    """ "$12,400.00", or "-$17.44" (never "$-17.44"), for summaries."""
    value = Decimal(amount)
    return f"-${-value:,.2f}" if value < 0 else f"${value:,.2f}"


def signed_dollars(amount: Money | Decimal) -> str:
    value = Decimal(amount)
    return ("+" if value > 0 else "") + dollars(value)


# --- workspaces --------------------------------------------------------------


class WorkspaceSummary(BaseModel):
    name: str
    role: Literal["owner", "editor", "viewer"]
    latest_snapshot: dt.date | None = Field(
        description="Date of the latest saved snapshot; null if none yet"
    )
    net_worth: Money | None = Field(description="Net worth on that snapshot")


class WorkspacesResult(ToolResult):
    workspaces: list[WorkspaceSummary]

    def summary(self) -> str:
        if not self.workspaces:
            return "You are not in any workspace yet."
        parts = []
        for w in self.workspaces:
            worth = (
                f"net worth {dollars(w.net_worth)} on {w.latest_snapshot}"
                if w.net_worth is not None
                else "no snapshot yet"
            )
            parts.append(f"{w.name} ({w.role}; {worth})")
        noun = "workspace" if len(parts) == 1 else "workspaces"
        return f"{len(parts)} {noun}: " + "; ".join(parts) + "."


# --- balances ----------------------------------------------------------------


class FormulaView(BaseModel):
    """A computed account: rate × (sum of inputs − cost basis)."""

    kind: Literal["proportional"] = "proportional"
    rate_percent: str = Field(description='The rate in percent: "15" is 15%')
    cost_basis: Money
    inputs: list[str] = Field(description="Names of the accounts it sums")
    text: str = Field(description='e.g. "15% × (Schwab + Fidelity − basis)"')


class AccountView(BaseModel):
    name: str
    type: Literal["asset", "liability"]
    category: str | None = Field(
        description='"Bank Accounts", "Investment Accounts", "Credit Cards", '
        '"Tax Liability", or null for Uncategorized'
    )
    amount: Money | None = Field(
        description="Amount on the latest snapshot; null if it has no row there "
        "(added or unretired since)"
    )
    computed: bool
    formula: FormulaView | None = None
    retired_on: dt.date | None = None
    source: Source | None = Field(
        default=None,
        description="update_balances only: whether the amount was sent, "
        "carried forward from the latest snapshot, or computed",
    )


class CategoryGroup(BaseModel):
    category: str = Field(description='A category label, or "Uncategorized"')
    total: Money
    accounts: list[AccountView]


class Side(BaseModel):
    total: Money
    categories: list[CategoryGroup]


class ChangeView(BaseModel):
    """Net worth change since the snapshot closest to 30 days before the
    latest one, as the dashboard shows it."""

    since: dt.date
    amount: Money
    percent: str | None = Field(
        description='One decimal place, e.g. "1.5" or "-0.3"; null when the '
        "earlier net worth was zero"
    )


class BalancesResult(ToolResult):
    workspace: str
    as_of: dt.date | None = Field(description="Latest snapshot date; null if none")
    days_since: int | None = Field(description="Days from that snapshot to today")
    net_worth: Money | None
    change: ChangeView | None
    assets: Side
    liabilities: Side

    def summary(self) -> str:
        if self.as_of is None or self.net_worth is None:
            count = sum(
                len(g.accounts)
                for side in (self.assets, self.liabilities)
                for g in side.categories
            )
            return (
                f"{self.workspace} has no snapshot yet ({count} active accounts). "
                "Save one with update_balances."
            )
        ago = (
            "today"
            if self.days_since == 0
            else "1 day ago"
            if self.days_since == 1
            else f"{self.days_since} days ago"
        )
        text = (
            f"{self.workspace}: net worth {dollars(self.net_worth)} on "
            f"{self.as_of} ({ago}); assets {dollars(self.assets.total)}, "
            f"liabilities {dollars(self.liabilities.total)}."
        )
        if self.change is not None:
            percent = (
                f" ({'+' if not self.change.percent.startswith('-') else ''}"
                f"{self.change.percent}%)"
                if self.change.percent is not None
                else ""
            )
            text += (
                f" {signed_dollars(self.change.amount)}{percent} since "
                f"{self.change.since}."
            )
        return text


class Before(BaseModel):
    date: dt.date
    net_worth: Money


class UpdateBalancesResult(ToolResult):
    saved: bool = Field(description="False for a preview")
    date: dt.date = Field(description="The snapshot's date: today in the timezone")
    replaced: bool = Field(
        description="True if the save replaced (or would replace) an earlier "
        "save on the same date"
    )
    before: Before | None = Field(
        description="The latest snapshot before this save; null if none"
    )
    balances: BalancesResult = Field(
        description="get_balances after the save (or as it would be)"
    )

    def summary(self) -> str:
        worth = self.balances.net_worth or "0"
        accounts = [
            a
            for side in (self.balances.assets, self.balances.liabilities)
            for g in side.categories
            for a in g.accounts
        ]
        counts = {
            source: sum(1 for a in accounts if a.source == source)
            for source in ("updated", "carried_forward", "computed")
        }
        sources = (
            f"{counts['updated']} updated, {counts['carried_forward']} carried "
            f"forward, {counts['computed']} computed"
        )
        was = (
            f" from {dollars(self.before.net_worth)} ({self.before.date})"
            if self.before
            else ""
        )
        replacing = " It replaces the earlier save today." if self.replaced else ""
        if self.saved:
            return (
                f"Saved the snapshot for {self.date}: net worth went{was} to "
                f"{dollars(worth)} ({sources}).{replacing}"
            )
        return (
            f"Preview, nothing saved: net worth would go{was} to {dollars(worth)} "
            f"on {self.date} ({sources}).{replacing}"
        )


class SaveAccountResult(ToolResult):
    actions: list[Literal["created", "updated", "retired", "unretired"]]
    account: AccountView
    warnings: list[str] = Field(
        description="Things to tell the user, e.g. a retired account's last "
        "non-zero value"
    )

    def summary(self) -> str:
        what = " and ".join(self.actions).capitalize()
        text = f"{what} the {self.account.type} {self.account.name!r}."
        if self.warnings:
            text += " " + " ".join(self.warnings)
        return text


# --- history -----------------------------------------------------------------


class HistoryRow(BaseModel):
    period: str = Field(
        description='"2026-09-30" (snapshot), "2026-09" (month), "2026-Q3" '
        '(quarter) or "2026" (year)'
    )
    date: dt.date = Field(description="The snapshot used: the last one in the period")
    net_worth: Money
    assets: Money
    liabilities: Money
    accounts: dict[str, Money | None] = Field(
        description="Each named account's amount on that snapshot; null if it "
        "had no row (not yet added, or retired)"
    )


class HistoryResult(ToolResult):
    workspace: str
    interval: Literal["snapshot", "month", "quarter", "year"]
    start: dt.date | None
    end: dt.date | None
    rows: list[HistoryRow]

    def summary(self) -> str:
        if not self.rows:
            if self.start is None:
                return f"{self.workspace} has no snapshots yet."
            return f"No snapshots in {self.workspace} from {self.start} to {self.end}."
        first, last = self.rows[0], self.rows[-1]
        noun = "row" if len(self.rows) == 1 else "rows"
        return (
            f"{len(self.rows)} {noun} by {self.interval}, {first.period} to "
            f"{last.period}: net worth {dollars(first.net_worth)} to "
            f"{dollars(last.net_worth)}."
        )


# --- cash flows --------------------------------------------------------------


class FlowView(BaseModel):
    name: str
    direction: Literal["income", "expense"]
    amount: Money = Field(description="Each occurrence; never negative")
    every: int
    unit: Literal["day", "week", "month", "year"]
    every_text: str = Field(description='"every month", "every 2 weeks"')
    per_period: Money = Field(description="What it comes to per the chosen period")
    category: str | None = Field(description="Category name; null if uncategorized")
    note: str | None
    estimate: bool


class ExpenseCategory(BaseModel):
    name: str = Field(description='A category, or "Uncategorized"')
    total: Money
    share_of_income: str | None = Field(
        description='e.g. "28%" or "<1%"; null when there is no income'
    )
    flows: list[FlowView]


class CashFlowsResult(ToolResult):
    workspace: str
    per: Literal["day", "month", "year"]
    income: Money
    expenses: Money
    left_over: Money = Field(description="Income minus expenses; negative if short")
    expenses_share: str | None = Field(description="Expenses as a share of income")
    left_over_share: str | None = Field(
        description="What is left over (or short) as a share of income"
    )
    estimates: int = Field(description="How many flows are marked as estimates")
    income_flows: list[FlowView]
    expense_categories: list[ExpenseCategory] = Field(
        description="Categories with expenses, in their display order; "
        "Uncategorized last"
    )

    def summary(self) -> str:
        if not self.income_flows and not self.expense_categories:
            return f"{self.workspace} has no cash flows yet."
        left = Decimal(self.left_over)
        net = (
            f"{dollars(left)} left over" if left >= 0 else f"short by {dollars(-left)}"
        )
        share = f" ({self.expenses_share} of income)" if self.expenses_share else ""
        return (
            f"Per {self.per}: income {dollars(self.income)}, expenses "
            f"{dollars(self.expenses)}{share}, {net}."
        )


class SaveCashFlowResult(ToolResult):
    action: Literal["created", "updated"]
    flow: FlowView = Field(description="The flow, per month")
    created_category: str | None = Field(
        description="A category that did not exist and was created for this flow"
    )
    cash_flows: CashFlowsResult = Field(description="get_cash_flows per month, after")

    def summary(self) -> str:
        text = (
            f"{self.action.capitalize()} {self.flow.direction} {self.flow.name!r}: "
            f"{dollars(self.flow.amount)} {self.flow.every_text} "
            f"({dollars(self.flow.per_period)} a month)."
        )
        if self.created_category:
            text += f" Created the category {self.created_category!r}."
        return text + " " + self.cash_flows.summary()


class DeleteCashFlowResult(ToolResult):
    deleted: str
    cash_flows: CashFlowsResult = Field(description="get_cash_flows per month, after")

    def summary(self) -> str:
        return f"Deleted {self.deleted!r}. " + self.cash_flows.summary()
