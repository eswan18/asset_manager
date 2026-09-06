from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class RecordType(str, Enum):
    ASSET = "asset"
    LIABILITY = "liability"


class ProportionalFormula(BaseModel):
    """rate × (sum of inputs − cost_basis)."""

    kind: Literal["proportional"] = "proportional"
    rate: Decimal = Field(ge=0)
    cost_basis: Decimal = Decimal("0")


# When a second kind exists this becomes
# Annotated[ProportionalFormula | OtherFormula, Field(discriminator="kind")].
Formula = ProportionalFormula


class Account(BaseModel):
    id: int | None = None
    name: str
    type: RecordType
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
