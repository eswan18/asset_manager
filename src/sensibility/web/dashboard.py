"""The dashboard's numbers: daily totals, the change line, ranges, categories.

Everything here is pure: it takes the workspace's records and accounts (from
`get_all_records` and `get_accounts`) and returns plain values for the
template and the chart. The latest snapshot date is the latest date among
the records passed in, so it is always the workspace's own.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sensibility.models import Account, AccountCategory, Record, RecordType

MINUS = "−"
UNCATEGORIZED = "Uncategorized"

# Category colors, strongest first: the largest category takes the first.
# They name tokens; the browser resolves them for the current theme.
RAMPS: dict[RecordType, list[str]] = {
    RecordType.ASSET: ["var(--asset)", "var(--asset-2)"],
    RecordType.LIABILITY: [
        "var(--liability)",
        "var(--liability-2)",
        "var(--liability-3)",
        "var(--liability-4)",
    ],
}

# The chart's range toggle: ?range= value -> (label, months back, or None for all).
RANGES: dict[str, tuple[str, int | None]] = {
    "6m": ("6M", 6),
    "1y": ("1Y", 12),
    "all": ("All", None),
}
DEFAULT_RANGE = "1y"
CHANGE_DAYS = 30


@dataclass(frozen=True)
class Point:
    """One snapshot date's totals."""

    date: date
    assets: Decimal
    liabilities: Decimal

    @property
    def net_worth(self) -> Decimal:
        return self.assets - self.liabilities


@dataclass(frozen=True)
class Change:
    """Net worth now minus net worth on `since`."""

    since: date
    amount: Decimal
    # None when the earlier net worth was zero, so no percentage exists.
    percent: Decimal | None


@dataclass(frozen=True)
class CategoryTotal:
    label: str
    amount: Decimal
    color: str  # a CSS color naming tokens, e.g. "var(--asset)"


def daily_totals(records: list[Record]) -> list[Point]:
    """Assets and liabilities summed per snapshot date, oldest first."""
    sums: dict[date, dict[RecordType, Decimal]] = defaultdict(
        lambda: {RecordType.ASSET: Decimal(0), RecordType.LIABILITY: Decimal(0)}
    )
    for record in records:
        sums[record.date][record.type] += record.amount
    return [
        Point(d, s[RecordType.ASSET], s[RecordType.LIABILITY])
        for d, s in sorted(sums.items())
    ]


def change_since(points: list[Point], days: int = CHANGE_DAYS) -> Change | None:
    """The change from the snapshot closest to `days` before the latest one.

    Only earlier snapshots count, so with none there is no change (None). If
    none is that far back, the closest is simply the earliest. A tie goes to
    the older snapshot. `points` must be sorted by date.
    """
    if len(points) < 2:
        return None
    latest = points[-1]
    target = latest.date - timedelta(days=days)
    base = min(points[:-1], key=lambda p: (abs((p.date - target).days), p.date))
    amount = latest.net_worth - base.net_worth
    percent = None if base.net_worth == 0 else amount / abs(base.net_worth) * 100
    return Change(since=base.date, amount=amount, percent=percent)


def parse_range(value: str | None) -> str:
    """A valid ?range= key; anything else is the default."""
    return value if value in RANGES else DEFAULT_RANGE


def months_before(day: date, months: int) -> date:
    """The same day `months` earlier, clamped to the end of a shorter month."""
    index = day.year * 12 + day.month - 1 - months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def filter_range(points: list[Point], range_key: str) -> list[Point]:
    """The points within the range, counted back from the latest snapshot.

    Counting from the latest snapshot (not today) means the latest snapshot is
    always shown, however long ago it was. `points` must be sorted by date.
    """
    months = RANGES[range_key][1]
    if months is None or not points:
        return list(points)
    start = months_before(points[-1].date, months)
    return [p for p in points if p.date >= start]


def _category_label(category: AccountCategory | None) -> str:
    return category.label if category is not None else UNCATEGORIZED


def ramp_color(type: RecordType, index: int) -> str:
    """The `index`th color of a ramp. Past its end, the last token fades
    toward the surface, so extra categories stay told apart."""
    ramp = RAMPS[type]
    if index < len(ramp):
        return ramp[index]
    fade = max(15, 100 - 40 * (index - len(ramp) + 1))
    return f"color-mix(in srgb, {ramp[-1]} {fade}%, var(--surface))"


def latest_category_totals(
    records: list[Record], accounts: list[Account]
) -> dict[RecordType, list[CategoryTotal]]:
    """Each type's latest snapshot split by category, largest first.

    Read from the latest snapshot's rows, so the columns add up to where the
    lines end. Categories totalling zero are left out; equal totals keep the
    order of their names.
    """
    by_type: dict[RecordType, list[CategoryTotal]] = {t: [] for t in RecordType}
    if not records:
        return by_type
    latest = max(r.date for r in records)
    category = {a.id: a.category for a in accounts}
    sums: dict[tuple[RecordType, str], Decimal] = defaultdict(Decimal)
    for record in records:
        if record.date == latest:
            label = _category_label(category.get(record.account_id))
            sums[(record.type, label)] += record.amount
    for type in RecordType:
        ranked = sorted(
            ((label, amount) for (t, label), amount in sums.items() if t == type),
            key=lambda item: (-item[1], item[0]),
        )
        ranked = [(label, amount) for label, amount in ranked if amount != 0]
        by_type[type] = [
            CategoryTotal(label, amount, ramp_color(type, i))
            for i, (label, amount) in enumerate(ranked)
        ]
    return by_type


@dataclass(frozen=True)
class BarSegment:
    label: str
    color: str
    share: Decimal  # percent of the bar's track, 0..100, to two places


def category_bars(
    categories: dict[RecordType, list[CategoryTotal]],
) -> dict[RecordType, list[BarSegment]]:
    """The phone's stacked bars: the chart's columns laid on their side.

    Like the columns, both bars share one scale: the larger total fills the
    track and the other is as long as it is in proportion. Segments keep the
    columns' order and colors. A negative category draws nothing (a bar has
    no below-zero side); a type with no categories gets no segments.
    """
    positive = {
        type: [c for c in categories.get(type, []) if c.amount > 0]
        for type in RecordType
    }
    scale = max(sum((c.amount for c in cs), Decimal(0)) for cs in positive.values())
    if scale == 0:
        return {type: [] for type in RecordType}
    return {
        type: [
            BarSegment(
                c.label,
                c.color,
                (c.amount / scale * 100).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                ),
            )
            for c in cs
        ]
        for type, cs in positive.items()
    }


def account_cards(
    records: list[Record], accounts: list[Account]
) -> dict[RecordType, dict[str, Any]]:
    """The Assets and Liabilities cards: every active account under its category.

    An account's amount is its row on the latest snapshot date, or None if it
    has none (one added or unretired since). Categories come in
    AccountCategory order with Uncategorized last; only those with accounts
    appear.
    """
    latest = max((r.date for r in records), default=None)
    amounts = {r.account_id: r.amount for r in records if r.date == latest}
    order: list[AccountCategory | None] = [*AccountCategory, None]
    cards: dict[RecordType, dict[str, Any]] = {}
    for type in RecordType:
        active = [a for a in accounts if a.type == type and a.is_active]
        groups = []
        for category in order:
            rows = [
                {
                    "name": a.name,
                    "amount": amounts.get(a.id),
                    "computed": computed_label(a),
                }
                for a in active
                if a.category == category
            ]
            if rows:
                groups.append(
                    {
                        "label": _category_label(category),
                        "total": _sum(r["amount"] for r in rows),
                        "rows": rows,
                    }
                )
        cards[type] = {"total": _sum(g["total"] for g in groups), "groups": groups}
    return cards


def _sum(amounts) -> Decimal:
    return sum((a for a in amounts if a is not None), Decimal(0))


def computed_label(account: Account) -> str | None:
    """ "15% of gains, computed" for a computed account, else None."""
    if account.formula is None:
        return None
    text = f"{account.formula.rate * 100:f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"{text}% of gains, computed"


def money(amount: Decimal) -> str:
    """Whole dollars: $412,380, or −$1,200."""
    whole = amount.quantize(Decimal(1), rounding=ROUND_HALF_UP)
    sign = MINUS if whole < 0 else ""
    return f"{sign}${abs(whole):,.0f}"


def signed_money(amount: Decimal) -> str:
    """+$6,140, −$1,200, or $0."""
    whole = amount.quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return ("+" if whole > 0 else "") + money(whole)


def signed_percent(percent: Decimal) -> str:
    """+1.5%, −0.3%, or 0.0%, to one decimal place."""
    rounded = percent.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if rounded > 0:
        return f"+{rounded}%"
    if rounded < 0:
        return f"{MINUS}{abs(rounded)}%"
    return "0.0%"


def short_date(day: date, reference: date) -> str:
    """ "Sep 24", with the year only when it differs from `reference`'s."""
    text = f"{day:%b} {day.day}"
    return text if day.year == reference.year else f"{text}, {day.year}"


def long_date(day: date) -> str:
    """ "Oct 24, 2026"."""
    return f"{day:%b} {day.day}, {day.year}"


def getting_started(active_accounts: int, base: str) -> list[dict[str, Any]]:
    """A new workspace's three steps (board Y), until its first snapshot.

    With no active accounts, step 1 carries the button; once there are some,
    step 1 is done and step 2's button goes to Accounts to enter balances.
    `action` is a (label, href) pair, shown only to editors.
    """
    has_accounts = active_accounts > 0
    noun = "account" if active_accounts == 1 else "accounts"
    return [
        {
            "title": "Add your accounts",
            "text": f"Done: {active_accounts} {noun} added. Add more any time."
            if has_accounts
            else "Checking, savings, retirement, your home, loans, cards. "
            "Anything with a balance.",
            "done": has_accounts,
            "action": None
            if has_accounts
            else ("+ Add an account", f"{base}/accounts/new?type=asset"),
        },
        {
            "title": "Enter today's balances",
            "text": "Type each balance on Accounts and save. "
            "That's your first snapshot.",
            "done": False,
            "action": ("Enter balances", f"{base}/accounts") if has_accounts else None,
        },
        {
            "title": "Come back now and then",
            "text": "Save again every week or month. "
            "The chart grows with each snapshot.",
            "done": False,
            "action": None,
        },
    ]


CARD_TITLES = {RecordType.ASSET: "Assets", RecordType.LIABILITY: "Liabilities"}


def cards_view(records: list[Record], accounts: list[Account]) -> list[dict[str, Any]]:
    """The Assets and Liabilities cards: each active account under its
    category, with the latest snapshot's amount ("—" if it has none)."""
    cards = account_cards(records, accounts)
    return [
        {
            "title": title,
            "kind": type.value,
            "total": money(cards[type]["total"]),
            "groups": [
                {
                    "label": g["label"],
                    "total": money(g["total"]),
                    "rows": [
                        {
                            "name": r["name"],
                            "amount": "—"
                            if r["amount"] is None
                            else money(r["amount"]),
                            "computed": r["computed"],
                        }
                        for r in g["rows"]
                    ],
                }
                for g in cards[type]["groups"]
            ],
        }
        for type, title in CARD_TITLES.items()
    ]


# A new workspace's empty cards (board Y): what goes there, and its button.
EMPTY_CARDS = {
    "asset": ("No assets yet.", "+ Add an asset"),
    "liability": (
        "No liabilities yet. That's fine; plenty of people have none.",
        "+ Add a liability",
    ),
}


def onboarding_context(accounts: list[Account], base: str) -> dict[str, Any]:
    """Template values for a workspace with no snapshot yet: the steps, and
    the cards listing any accounts already added, with no amounts."""
    active = sum(1 for a in accounts if a.is_active)
    cards = cards_view([], accounts)
    for card in cards:
        empty, add = EMPTY_CARDS[card["kind"]]
        card["total"] = "—" if card["groups"] else money(Decimal(0))
        card["empty"] = empty
        card["add"] = (add, f"{base}/accounts/new?type={card['kind']}")
    return {
        "steps": getting_started(active, base),
        "has_accounts": active > 0,
        "cards": cards,
    }
