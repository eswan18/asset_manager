from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel


class RecordType(str, Enum):
    ASSET = "asset"
    LIABILITY = "liability"


class Record(BaseModel):
    id: int | None = None
    date: date
    type: RecordType
    description: str
    amount: Decimal
    created_at: datetime | None = None


class DailySummary(BaseModel):
    date: date
    type: RecordType
    total_amount: Decimal
