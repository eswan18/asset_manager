from datetime import date
from decimal import Decimal

from psycopg import Connection

from asset_manager.models import DailySummary, Record, RecordType


def insert_records(conn: Connection, records: list[Record]) -> int:
    """Insert records into the database. Returns the number of records inserted."""
    if not records:
        return 0

    query = """
        INSERT INTO snapshots (date, type, description, amount)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (date, type, description) DO UPDATE SET
            amount = EXCLUDED.amount
    """

    with conn.cursor() as cur:
        cur.executemany(
            query,
            [
                (r.date, r.type.value, r.description, r.amount)
                for r in records
            ],
        )
    conn.commit()
    return len(records)


def get_all_records(conn: Connection) -> list[Record]:
    """Fetch all records from the database."""
    query = """
        SELECT id, date, type, description, amount, created_at
        FROM snapshots
        ORDER BY date, type, description
    """

    with conn.cursor() as cur:
        cur.execute(query)
        rows = cur.fetchall()

    return [
        Record(
            id=row[0],
            date=row[1],
            type=RecordType(row[2]),
            description=row[3],
            amount=Decimal(str(row[4])),
            created_at=row[5],
        )
        for row in rows
    ]


def get_records_by_date_range(
    conn: Connection, start_date: date, end_date: date
) -> list[Record]:
    """Fetch records within a date range."""
    query = """
        SELECT id, date, type, description, amount, created_at
        FROM snapshots
        WHERE date >= %s AND date <= %s
        ORDER BY date, type, description
    """

    with conn.cursor() as cur:
        cur.execute(query, (start_date, end_date))
        rows = cur.fetchall()

    return [
        Record(
            id=row[0],
            date=row[1],
            type=RecordType(row[2]),
            description=row[3],
            amount=Decimal(str(row[4])),
            created_at=row[5],
        )
        for row in rows
    ]


def get_summary_by_date(conn: Connection) -> list[DailySummary]:
    """Get aggregated totals by date and type."""
    query = """
        SELECT date, type, SUM(amount) as total_amount
        FROM snapshots
        GROUP BY date, type
        ORDER BY date, type
    """

    with conn.cursor() as cur:
        cur.execute(query)
        rows = cur.fetchall()

    return [
        DailySummary(
            date=row[0],
            type=RecordType(row[1]),
            total_amount=Decimal(str(row[2])),
        )
        for row in rows
    ]
