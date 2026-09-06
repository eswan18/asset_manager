"""Tests for the Pydantic models."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from asset_manager.models import Account, ProportionalFormula, Record, RecordType


def test_proportional_formula_defaults_and_json_round_trip():
    formula = ProportionalFormula(rate=Decimal("0.15"))
    assert formula.kind == "proportional"
    assert formula.cost_basis == Decimal("0")
    dumped = formula.model_dump(mode="json")
    assert dumped == {"kind": "proportional", "rate": "0.15", "cost_basis": "0"}
    assert ProportionalFormula.model_validate(dumped) == formula


def test_proportional_formula_rejects_negative_rate():
    with pytest.raises(ValidationError):
        ProportionalFormula(rate=Decimal("-0.1"))


def test_account_parses_formula_document():
    account = Account.model_validate(
        {
            "id": 7,
            "name": "Cap Gains Tax",
            "type": "liability",
            "formula": {
                "kind": "proportional",
                "rate": "0.15",
                "cost_basis": "70634.00",
            },
            "input_ids": [3],
        }
    )
    assert account.is_computed
    assert account.is_active
    assert account.formula == ProportionalFormula(
        rate=Decimal("0.15"), cost_basis=Decimal("70634.00")
    )
    assert account.input_ids == [3]


def test_account_rejects_unknown_formula_kind():
    with pytest.raises(ValidationError):
        Account.model_validate(
            {"name": "X", "type": "asset", "formula": {"kind": "drift"}}
        )


def test_plain_account_defaults():
    account = Account(name="Savings", type=RecordType.ASSET)
    assert not account.is_computed
    assert account.input_ids == []
    assert account.is_active


def test_retired_account_is_not_active():
    account = Account(
        name="Old 401k", type=RecordType.ASSET, retired_at=date(2026, 9, 1)
    )
    assert not account.is_active


def test_record_carries_account_id():
    record = Record(
        date=date(2026, 9, 6),
        account_id=3,
        type=RecordType.ASSET,
        description="Savings",
        amount=Decimal("10"),
    )
    assert record.account_id == 3
