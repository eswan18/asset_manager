from datetime import date
from decimal import Decimal

import pytest

from asset_manager.models import Record, RecordType
from asset_manager.repository import (
    get_all_records,
    get_inaccessible_assets_by_date,
    get_records_by_date_range,
    get_summary_by_date,
    insert_records,
)


@pytest.mark.db
class TestRepository:
    def test_insert_and_fetch_records(self, db_connection):
        records = [
            Record(
                date=date(2024, 1, 15),
                type=RecordType.ASSET,
                description="Savings Account",
                amount=Decimal("10000.00"),
                accessible=True,
            ),
            Record(
                date=date(2024, 1, 15),
                type=RecordType.LIABILITY,
                description="Credit Card",
                amount=Decimal("500.00"),
                accessible=True,
            ),
        ]

        inserted = insert_records(db_connection, records)
        assert inserted == 2

        fetched = get_all_records(db_connection)
        assert len(fetched) == 2
        # Ordered by type (asset before liability alphabetically), then description
        assert fetched[0].description == "Savings Account"
        assert fetched[1].description == "Credit Card"

    def test_insert_records_upsert(self, db_connection):
        # Insert initial record
        records = [
            Record(
                date=date(2024, 1, 15),
                type=RecordType.ASSET,
                description="Savings Account",
                amount=Decimal("10000.00"),
                accessible=True,
            ),
        ]
        insert_records(db_connection, records)

        # Update with new amount
        updated_records = [
            Record(
                date=date(2024, 1, 15),
                type=RecordType.ASSET,
                description="Savings Account",
                amount=Decimal("15000.00"),
                accessible=True,
            ),
        ]
        insert_records(db_connection, updated_records)

        fetched = get_all_records(db_connection)
        assert len(fetched) == 1
        assert fetched[0].amount == Decimal("15000.00")

    def test_get_records_by_date_range(self, db_connection):
        records = [
            Record(
                date=date(2024, 1, 10),
                type=RecordType.ASSET,
                description="Account 1",
                amount=Decimal("1000.00"),
            ),
            Record(
                date=date(2024, 1, 15),
                type=RecordType.ASSET,
                description="Account 2",
                amount=Decimal("2000.00"),
            ),
            Record(
                date=date(2024, 1, 20),
                type=RecordType.ASSET,
                description="Account 3",
                amount=Decimal("3000.00"),
            ),
        ]
        insert_records(db_connection, records)

        fetched = get_records_by_date_range(
            db_connection, date(2024, 1, 12), date(2024, 1, 18)
        )
        assert len(fetched) == 1
        assert fetched[0].description == "Account 2"

    def test_get_summary_by_date(self, db_connection):
        records = [
            Record(
                date=date(2024, 1, 15),
                type=RecordType.ASSET,
                description="Asset 1",
                amount=Decimal("1000.00"),
            ),
            Record(
                date=date(2024, 1, 15),
                type=RecordType.ASSET,
                description="Asset 2",
                amount=Decimal("2000.00"),
            ),
            Record(
                date=date(2024, 1, 15),
                type=RecordType.LIABILITY,
                description="Liability 1",
                amount=Decimal("500.00"),
            ),
        ]
        insert_records(db_connection, records)

        summaries = get_summary_by_date(db_connection)
        assert len(summaries) == 2

        asset_summary = next(s for s in summaries if s.type == RecordType.ASSET)
        liability_summary = next(s for s in summaries if s.type == RecordType.LIABILITY)

        assert asset_summary.total_amount == Decimal("3000.00")
        assert liability_summary.total_amount == Decimal("500.00")

    def test_get_inaccessible_assets_by_date(self, db_connection):
        records = [
            Record(
                date=date(2024, 1, 15),
                type=RecordType.ASSET,
                description="Accessible Asset",
                amount=Decimal("1000.00"),
                accessible=True,
            ),
            Record(
                date=date(2024, 1, 15),
                type=RecordType.ASSET,
                description="Inaccessible Asset",
                amount=Decimal("5000.00"),
                accessible=False,
            ),
        ]
        insert_records(db_connection, records)

        summaries = get_inaccessible_assets_by_date(db_connection)
        assert len(summaries) == 1
        assert summaries[0].total_amount == Decimal("5000.00")

    def test_insert_empty_list(self, db_connection):
        inserted = insert_records(db_connection, [])
        assert inserted == 0
        assert get_all_records(db_connection) == []
