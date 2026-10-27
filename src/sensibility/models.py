from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class RecordType(str, Enum):
    ASSET = "asset"
    LIABILITY = "liability"


class AccountCategory(str, Enum):
    """Grouping on the accounts page. Declaration order is display order.

    Values must match the CHECK constraint on accounts.category.
    """

    BANK_ACCOUNTS = "bank_accounts"
    INVESTMENT_ACCOUNTS = "investment_accounts"
    CREDIT_CARDS = "credit_cards"
    TAX_LIABILITY = "tax_liability"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()


class ProportionalFormula(BaseModel):
    """rate × (sum of inputs − cost_basis)."""

    kind: Literal["proportional"] = "proportional"
    rate: Decimal = Field(ge=0, decimal_places=6)
    cost_basis: Decimal = Decimal("0")


# When a second kind exists this becomes
# Annotated[ProportionalFormula | OtherFormula, Field(discriminator="kind")].
Formula = ProportionalFormula


class Account(BaseModel):
    id: int | None = None
    workspace_id: int | None = None
    name: str
    type: RecordType
    category: AccountCategory | None = None
    formula: Formula | None = None
    input_ids: list[int] = []
    retired_at: date | None = None
    created_at: datetime | None = None

    @property
    def is_computed(self) -> bool:
        return self.formula is not None

    @property
    def is_active(self) -> bool:
        return self.retired_at is None


class Record(BaseModel):
    id: int | None = None
    date: date
    account_id: int | None = None
    type: RecordType
    description: str
    amount: Decimal
    created_at: datetime | None = None


class DailySummary(BaseModel):
    date: date
    type: RecordType
    total_amount: Decimal


class Role(str, Enum):
    """A member's role in a workspace. Each role can do everything the ones
    after it can: owners manage members, editors change data, viewers read."""

    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"

    def allows(self, needed: "Role") -> bool:
        order = [Role.VIEWER, Role.EDITOR, Role.OWNER]
        return order.index(self) >= order.index(needed)


class User(BaseModel):
    id: int
    idp_sub: str | None
    email: str
    name: str | None = None
    is_admin: bool = False
    created_at: datetime | None = None
    last_login_at: datetime | None = None


class Workspace(BaseModel):
    id: int
    name: str
    created_at: datetime | None = None
    deleted_at: datetime | None = None


class Member(BaseModel):
    """A user as seen from one workspace."""

    user_id: int
    email: str
    name: str | None
    role: Role
    joined_at: datetime


class Invite(BaseModel):
    id: int
    workspace_id: int
    email: str
    role: Role
    invited_by: int
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None = None
    declined_at: datetime | None = None
    revoked_at: datetime | None = None

    @property
    def is_open(self) -> bool:
        """Not yet accepted, declined or revoked. May still have expired."""
        return (
            self.accepted_at is None
            and self.declined_at is None
            and self.revoked_at is None
        )

    def is_pending(self, now: datetime) -> bool:
        """Open and unexpired: the only state that can be accepted."""
        return self.is_open and now < self.expires_at


class CashFlowDirection(str, Enum):
    INCOME = "income"
    EXPENSE = "expense"


class FrequencyUnit(str, Enum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


class CashFlowCategory(BaseModel):
    id: int
    workspace_id: int
    name: str
    position: int


class CashFlow(BaseModel):
    """`amount` (never negative) every `every` `unit`s; `direction` says which way."""

    id: int | None = None
    workspace_id: int | None = None
    name: str
    direction: CashFlowDirection
    amount: Decimal
    every: int = 1
    unit: FrequencyUnit
    category_id: int | None = None
    description: str | None = None
    is_estimate: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
