"""Tests for the report module."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from asset_manager.models import Record, RecordType
from asset_manager.report import _transform_data, generate_report


def _make_record(
    record_date: date,
    record_type: RecordType,
    description: str,
    amount: Decimal,
) -> Record:
    return Record(
        date=record_date,
        type=record_type,
        description=description,
        amount=amount,
    )


def test_transform_data_empty():
    assets, liabilities, summary = _transform_data([])
    assert assets == {}
    assert liabilities == {}
    assert summary == []


def test_transform_data_single_asset():
    records = [
        _make_record(date(2024, 1, 1), RecordType.ASSET, "Savings", Decimal("1000")),
    ]
    assets, liabilities, summary = _transform_data(records)

    assert "Savings" in assets
    assert len(assets["Savings"]) == 1
    assert assets["Savings"][0] == (date(2024, 1, 1), Decimal("1000"))

    assert liabilities == {}

    assert len(summary) == 1
    assert summary[0] == (
        date(2024, 1, 1),
        Decimal("1000"),
        Decimal("0"),
        Decimal("1000"),
    )


def test_transform_data_multiple_records():
    records = [
        _make_record(date(2024, 1, 1), RecordType.ASSET, "Savings", Decimal("1000")),
        _make_record(date(2024, 1, 1), RecordType.ASSET, "401k", Decimal("5000")),
        _make_record(
            date(2024, 1, 1), RecordType.LIABILITY, "Credit Card", Decimal("500")
        ),
        _make_record(date(2024, 1, 15), RecordType.ASSET, "Savings", Decimal("1200")),
        _make_record(
            date(2024, 1, 15), RecordType.LIABILITY, "Credit Card", Decimal("600")
        ),
    ]
    assets, liabilities, summary = _transform_data(records)

    assert set(assets.keys()) == {"Savings", "401k"}
    assert set(liabilities.keys()) == {"Credit Card"}

    # Check summary calculations
    assert len(summary) == 2

    # Day 1: assets = 6000, liabilities = 500, net = 5500
    assert summary[0][0] == date(2024, 1, 1)
    assert summary[0][1] == Decimal("6000")
    assert summary[0][2] == Decimal("500")
    assert summary[0][3] == Decimal("5500")

    # Day 2: assets = 1200, liabilities = 600, net = 600
    assert summary[1][0] == date(2024, 1, 15)
    assert summary[1][1] == Decimal("1200")
    assert summary[1][2] == Decimal("600")
    assert summary[1][3] == Decimal("600")


def test_transform_data_sorts_by_date():
    records = [
        _make_record(date(2024, 1, 15), RecordType.ASSET, "Savings", Decimal("1200")),
        _make_record(date(2024, 1, 1), RecordType.ASSET, "Savings", Decimal("1000")),
    ]
    assets, _, _ = _transform_data(records)

    # Should be sorted by date
    assert assets["Savings"][0][0] == date(2024, 1, 1)
    assert assets["Savings"][1][0] == date(2024, 1, 15)


def test_generate_report_creates_file(tmp_path: Path):
    records = [
        _make_record(date(2024, 1, 1), RecordType.ASSET, "Savings", Decimal("1000")),
        _make_record(
            date(2024, 1, 1), RecordType.LIABILITY, "Credit Card", Decimal("500")
        ),
    ]
    output_path = tmp_path / "report.html"

    result = generate_report(records, output_path=output_path, open_browser=False)

    assert result == output_path
    assert output_path.exists()
    content = output_path.read_text()
    assert "plotly" in content.lower()
    assert "Financial Report" in content


def test_generate_report_empty_records(tmp_path: Path):
    output_path = tmp_path / "report.html"
    result = generate_report([], output_path=output_path, open_browser=False)

    assert result == output_path
    assert output_path.exists()
