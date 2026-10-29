"""GET /api/workspaces/{id}/dashboard: the dashboard page as data.

Computed by the helpers in web/dashboard.py, which the MCP tools share.
Amounts are exact two-place strings; the page shows whole dollars, rounded
half up, and the client does that rounding.
"""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from sensibility.db import get_connection_context
from sensibility.models import Account, Record, RecordType, Role
from sensibility.repository import get_accounts, get_all_records

from .access import ViewerAccess
from .api_models import Money, key_for_label, maybe_money, money, responses
from .dashboard import (
    CARD_TITLES,
    EMPTY_CARDS,
    RANGES,
    account_cards,
    category_bars,
    change_since,
    daily_totals,
    filter_range,
    getting_started,
    latest_category_totals,
    parse_range,
)

router = APIRouter(prefix="/api/workspaces/{workspace_id}")

RangeKey = Literal["6m", "1y", "all"]


class RangeOption(BaseModel):
    key: RangeKey
    label: str = Field(description='"6M", "1Y" or "All"')


class ChangeOut(BaseModel):
    """Net worth now minus net worth at the snapshot closest to 30 days
    before the latest one (ties to the older)."""

    since: dt.date = Field(description="The snapshot compared with")
    amount: Money
    percent: str | None = Field(
        description="Of the earlier net worth, one decimal place rounded half "
        'up: "1.5", "-0.3", "0.0". Null when the earlier net worth was zero'
    )


class PointOut(BaseModel):
    """One snapshot date's totals."""

    date: dt.date
    assets: Money
    liabilities: Money
    net_worth: Money


class CategoryTotalOut(BaseModel):
    """One category's share of the latest snapshot, for the chart's columns
    and the key under it."""

    key: str = Field(description='The category\'s key, or "uncategorized"')
    label: str
    amount: Money
    color: str = Field(
        description='A CSS color naming design tokens: "var(--asset)", or past '
        'the end of a ramp "color-mix(in srgb, var(--liability-4) 60%, '
        'var(--surface))". Resolve it in the page, for the current theme'
    )


class BarSegmentOut(BaseModel):
    """A phone's stacked bar segment: the columns laid on their side."""

    key: str
    label: str
    color: str
    share: str = Field(
        description="Percent of the bar's track, two places. Both bars share "
        "one scale: the larger total fills the track"
    )


class CategoriesOut(BaseModel):
    """Per side, largest first; categories totalling zero are left out."""

    asset: list[CategoryTotalOut]
    liability: list[CategoryTotalOut]


class BarsOut(BaseModel):
    """Per side; a negative category draws nothing."""

    asset: list[BarSegmentOut]
    liability: list[BarSegmentOut]


class CardAccount(BaseModel):
    id: int
    name: str
    amount: Money | None = Field(
        description="On the latest snapshot; null (shown as —) if it has no "
        "row there, or there is no snapshot yet"
    )
    computed: str | None = Field(
        description='"15% of gains, computed" for a computed account, else null'
    )


class CardGroup(BaseModel):
    key: str = Field(description='The category\'s key, or "uncategorized"')
    label: str
    total: Money = Field(description="Sum of the amounts that are not null")
    accounts: list[CardAccount]


class Action(BaseModel):
    """A button, shown to editors only."""

    label: str
    path: str = Field(
        description='Relative to the workspace\'s pages: "/accounts" or '
        '"/accounts/new?type=asset"'
    )


class Card(BaseModel):
    """The Assets or Liabilities card: every active account under its
    category (AccountCategory order, Uncategorized last, empty ones left
    out)."""

    kind: RecordType
    title: str = Field(description='"Assets" or "Liabilities"')
    total: Money | None = Field(
        description="Sum of the groups. Null (shown as —) only before the first "
        "snapshot when the card lists accounts"
    )
    groups: list[CardGroup]
    empty: str | None = Field(
        default=None,
        description="Before the first snapshot: the text for a card with no accounts",
    )
    add: Action | None = Field(
        default=None,
        description="Before the first snapshot: the empty card's add button",
    )


class Step(BaseModel):
    title: str
    text: str
    done: bool
    action: Action | None


class Onboarding(BaseModel):
    """The getting-started state (board Y), for a workspace with no
    snapshot yet."""

    steps: list[Step]
    has_accounts: bool = Field(
        description="Any active account. A viewer's note reads \"An editor "
        'hasn\'t entered any balances yet" if so, else "... added any '
        'accounts yet"'
    )


class DashboardOut(BaseModel):
    has_data: bool = Field(description="At least one snapshot exists")
    can_edit: bool = Field(description="Editor or owner: show the add buttons")
    range: RangeKey = Field(description="The range applied (an unknown ?range= is 1y)")
    ranges: list[RangeOption]
    net_worth: Money | None = Field(description="On the latest snapshot")
    last_snapshot: dt.date | None
    change: ChangeOut | None = Field(description="Null with fewer than two snapshots")
    history: list[PointOut] = Field(
        description="Oldest first, within the range counted back from the "
        "latest snapshot (not today)"
    )
    categories: CategoriesOut
    bars: BarsOut
    cards: list[Card] = Field(description="Assets, then Liabilities")
    onboarding: Onboarding | None = Field(description="Only when has_data is false")


def _percent(percent: Decimal | None) -> str | None:
    if percent is None:
        return None
    return str(percent.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _cards(
    records: list[Record], accounts: list[Account], has_data: bool
) -> list[Card]:
    cards = account_cards(records, accounts)
    out = []
    for type, title in CARD_TITLES.items():
        card = cards[type]
        groups = [
            CardGroup(
                key=key_for_label(g["label"]),
                label=g["label"],
                total=money(g["total"]),
                accounts=[
                    CardAccount(
                        id=r["id"],
                        name=r["name"],
                        amount=maybe_money(r["amount"]),
                        computed=r["computed"],
                    )
                    for r in g["rows"]
                ],
            )
            for g in card["groups"]
        ]
        if has_data:
            out.append(
                Card(kind=type, title=title, total=money(card["total"]), groups=groups)
            )
        else:
            # No snapshot yet: "—" over listed accounts, else $0 and the
            # empty card's text and add button.
            empty, add = EMPTY_CARDS[type.value]
            out.append(
                Card(
                    kind=type,
                    title=title,
                    total=None if groups else money(Decimal(0)),
                    groups=groups,
                    empty=empty,
                    add=Action(label=add, path=f"/accounts/new?type={type.value}"),
                )
            )
    return out


def dashboard_view(
    records: list[Record],
    accounts: list[Account],
    range_key: str | None,
    can_edit: bool,
) -> DashboardOut:
    """The dashboard for these records and accounts (get_all_records and
    get_accounts of one workspace)."""
    selected = parse_range(range_key)
    points = daily_totals(records)
    latest = points[-1] if points else None
    categories = latest_category_totals(records, accounts)
    bars = category_bars(categories)
    change = change_since(points)
    onboarding = None
    if latest is None:
        active = sum(1 for a in accounts if a.is_active)
        onboarding = Onboarding(
            steps=[
                Step(
                    title=s["title"],
                    text=s["text"],
                    done=s["done"],
                    action=None
                    if s["action"] is None
                    else Action(label=s["action"][0], path=s["action"][1]),
                )
                for s in getting_started(active)
            ],
            has_accounts=active > 0,
        )
    return DashboardOut(
        has_data=latest is not None,
        can_edit=can_edit,
        range=cast(RangeKey, selected),
        ranges=[
            RangeOption(key=cast(RangeKey, key), label=label)
            for key, (label, _) in RANGES.items()
        ],
        net_worth=None if latest is None else money(latest.net_worth),
        last_snapshot=None if latest is None else latest.date,
        change=None
        if change is None
        else ChangeOut(
            since=change.since,
            amount=money(change.amount),
            percent=_percent(change.percent),
        ),
        history=[
            PointOut(
                date=p.date,
                assets=money(p.assets),
                liabilities=money(p.liabilities),
                net_worth=money(p.net_worth),
            )
            for p in filter_range(points, selected)
        ],
        categories=CategoriesOut(
            **{
                type.value: [
                    CategoryTotalOut(
                        key=key_for_label(c.label),
                        label=c.label,
                        amount=money(c.amount),
                        color=c.color,
                    )
                    for c in categories[type]
                ]
                for type in RecordType
            }
        ),
        bars=BarsOut(
            **{
                type.value: [
                    BarSegmentOut(
                        key=key_for_label(s.label),
                        label=s.label,
                        color=s.color,
                        share=str(s.share),
                    )
                    for s in bars[type]
                ]
                for type in RecordType
            }
        ),
        cards=_cards(records, accounts, latest is not None),
        onboarding=onboarding,
    )


@router.get("/dashboard", responses=responses(404))
async def get_dashboard(
    access: ViewerAccess,
    range_key: Annotated[
        str | None,
        Query(alias="range", description="6m, 1y (the default) or all"),
    ] = None,
) -> DashboardOut:
    """The dashboard page's model: net worth, its change, the history series
    for the range, the latest snapshot by category, the account cards, and
    the getting-started state when there is no snapshot yet."""
    workspace_id = access.workspace.id
    with get_connection_context() as conn:
        records = get_all_records(conn, workspace_id)
        accounts = get_accounts(conn, workspace_id)
    return dashboard_view(records, accounts, range_key, access.role.allows(Role.EDITOR))
