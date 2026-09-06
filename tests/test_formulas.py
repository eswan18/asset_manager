"""Tests for formula evaluation."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from asset_manager.formulas import MissingValueError, compute_snapshot, quantize_cents
from asset_manager.models import Account, ProportionalFormula, RecordType

AS_OF = date(2026, 9, 6)


def _asset(id: int, name: str) -> Account:
    return Account(id=id, name=name, type=RecordType.ASSET)


def _computed(
    id: int, name: str, rate: Decimal, basis: Decimal, input_ids: list[int]
) -> Account:
    return Account(
        id=id,
        name=name,
        type=RecordType.LIABILITY,
        formula=ProportionalFormula(rate=rate, cost_basis=basis),
        input_ids=input_ids,
    )


def test_quantize_cents_rounds_half_up():
    assert quantize_cents(Decimal("10.005")) == Decimal("10.01")
    assert quantize_cents(Decimal("-17.436")) == Decimal("-17.44")


def test_plain_values_pass_through_quantized():
    result = compute_snapshot([_asset(1, "Savings")], {1: Decimal("10.005")}, AS_OF)
    assert result == {1: Decimal("10.01")}


def test_proportional_with_basis_matches_the_sheet():
    accounts = [
        _asset(1, "Schwab"),
        _computed(2, "Cap Gains Tax", Decimal("0.15"), Decimal("70634.00"), [1]),
    ]
    result = compute_snapshot(accounts, {1: Decimal("163202.77")}, AS_OF)
    assert result == {1: Decimal("163202.77"), 2: Decimal("13885.32")}


def test_proportional_sums_multiple_inputs():
    accounts = [
        _asset(1, "401k A"),
        _asset(2, "401k B"),
        _computed(3, "Deferred Tax", Decimal("0.32"), Decimal("0"), [1, 2]),
    ]
    result = compute_snapshot(accounts, {1: Decimal("100"), 2: Decimal("50")}, AS_OF)
    assert result[3] == Decimal("48.00")


def test_negative_result_is_allowed():
    accounts = [
        _asset(1, "Fidelity"),
        _computed(2, "Cap Gains Tax", Decimal("0.15"), Decimal("1472.00"), [1]),
    ]
    result = compute_snapshot(accounts, {1: Decimal("1355.76")}, AS_OF)
    assert result[2] == Decimal("-17.44")


def test_missing_plain_value_raises():
    with pytest.raises(MissingValueError, match="Savings") as info:
        compute_snapshot([_asset(1, "Savings")], {}, AS_OF)
    assert info.value.account_name == "Savings"


def test_missing_input_value_raises_naming_the_input():
    accounts = [
        _asset(1, "Schwab"),
        _computed(2, "Cap Gains Tax", Decimal("0.15"), Decimal("0"), [1]),
    ]
    with pytest.raises(MissingValueError, match="Schwab"):
        compute_snapshot(accounts, {}, AS_OF)


def test_extra_values_are_ignored():
    result = compute_snapshot(
        [_asset(1, "Savings")], {1: Decimal("5"), 9: Decimal("1")}, AS_OF
    )
    assert result == {1: Decimal("5.00")}


amounts = st.decimals(
    min_value=Decimal("-1000000"), max_value=Decimal("1000000"), places=2
)
rates = st.decimals(min_value=Decimal("0"), max_value=Decimal("1"), places=6)


@given(rate=rates, basis=amounts, inputs=st.lists(amounts, min_size=1, max_size=5))
def test_proportional_matches_definition(rate, basis, inputs):
    assets = [_asset(i + 1, f"A{i}") for i in range(len(inputs))]
    computed = _computed(99, "L", rate, basis, [i + 1 for i in range(len(inputs))])
    values = {i + 1: v for i, v in enumerate(inputs)}
    result = compute_snapshot(assets + [computed], values, AS_OF)
    expected = (rate * (sum(inputs) - basis)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    assert result[99] == expected
