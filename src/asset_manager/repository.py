"""Thin SQL layer. Functions here never commit; callers own the transaction."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, LiteralString, cast

from psycopg import Connection, Cursor
from psycopg.types.json import Jsonb

from asset_manager.models import Account, DailySummary, Formula, Record, RecordType

_RECORD_SELECT = """
    SELECT s.id, s.date, s.account_id, a.type, a.name, s.amount, s.created_at
    FROM snapshots s
    JOIN accounts a ON a.id = s.account_id
"""

_ACCOUNT_SELECT = """
    SELECT a.id, a.name, a.type, a.formula, a.retired_at, a.created_at,
           COALESCE(
               array_agg(fi.input_id ORDER BY fi.input_id)
                   FILTER (WHERE fi.input_id IS NOT NULL),
               '{}'
           ) AS input_ids
    FROM accounts a
    LEFT JOIN formula_inputs fi ON fi.account_id = a.id
"""


# --- snapshots -------------------------------------------------------------


def _record_from_row(row: tuple[Any, ...]) -> Record:
    return Record(
        id=row[0],
        date=row[1],
        account_id=row[2],
        type=RecordType(row[3]),
        description=row[4],
        amount=Decimal(row[5]),
        created_at=row[6],
    )


def _select_records(
    conn: Connection,
    where: str = "",
    params: tuple[Any, ...] = (),
    order: str = "s.date, a.type, a.name",
) -> list[Record]:
    # where/order are always internal literals, never user input; the cast tells the
    # type checker what's already true at runtime, since f-strings aren't LiteralString.
    query = cast(LiteralString, f"{_RECORD_SELECT} {where} ORDER BY {order}")
    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
    return [_record_from_row(row) for row in rows]


def get_all_records(conn: Connection) -> list[Record]:
    """Fetch all snapshot records, joined to their account."""
    return _select_records(conn)


def get_records_by_date_range(
    conn: Connection, start_date: date, end_date: date
) -> list[Record]:
    """Fetch records within a date range."""
    return _select_records(
        conn, "WHERE s.date >= %s AND s.date <= %s", (start_date, end_date)
    )


def get_latest_snapshot_records(conn: Connection) -> list[Record]:
    """Fetch records for the most recent snapshot date."""
    return _select_records(
        conn, "WHERE s.date = (SELECT MAX(date) FROM snapshots)", order="a.type, a.name"
    )


def get_summary_by_date(conn: Connection) -> list[DailySummary]:
    """Get aggregated totals by date and type."""
    query = """
        SELECT s.date, a.type, SUM(s.amount) AS total_amount
        FROM snapshots s
        JOIN accounts a ON a.id = s.account_id
        GROUP BY s.date, a.type
        ORDER BY s.date, a.type
    """
    with conn.cursor() as cur:
        cur.execute(query)
        rows = cur.fetchall()
    return [
        DailySummary(date=row[0], type=RecordType(row[1]), total_amount=Decimal(row[2]))
        for row in rows
    ]


def upsert_amounts(conn: Connection, as_of: date, amounts: dict[int, Decimal]) -> int:
    """Write one row per account for `as_of`, replacing any existing row for that date."""
    if not amounts:
        return 0
    query = """
        INSERT INTO snapshots (date, account_id, amount)
        VALUES (%s, %s, %s)
        ON CONFLICT (date, account_id) DO UPDATE SET amount = EXCLUDED.amount
    """
    with conn.cursor() as cur:
        cur.executemany(
            query, [(as_of, aid, amount) for aid, amount in amounts.items()]
        )
    return len(amounts)


def insert_records(conn: Connection, records: list[Record]) -> int:
    """Temporary bridge for the Sheets fetch: resolve accounts by (type, description),
    creating unknown ones, then upsert. Commits. Replaced by sheets.save_rows in Task 6."""
    if not records:
        return 0
    by_date: dict[date, dict[int, Decimal]] = {}
    for record in records:
        account = get_account_by_name(conn, record.type, record.description)
        if account is None:
            account = insert_account(
                conn, Account(name=record.description, type=record.type)
            )
        if account.id is None:
            raise ValueError("insert_account returned no id")
        by_date.setdefault(record.date, {})[account.id] = record.amount
    count = sum(upsert_amounts(conn, d, amounts) for d, amounts in by_date.items())
    conn.commit()
    return count


# --- accounts --------------------------------------------------------------


def _account_from_row(row: tuple[Any, ...]) -> Account:
    return Account.model_validate(
        {
            "id": row[0],
            "name": row[1],
            "type": row[2],
            "formula": row[3],
            "retired_at": row[4],
            "created_at": row[5],
            "input_ids": list(row[6]),
        }
    )


def _select_accounts(
    conn: Connection, where: str = "", params: tuple[Any, ...] = ()
) -> list[Account]:
    query = cast(
        LiteralString, f"{_ACCOUNT_SELECT} {where} GROUP BY a.id ORDER BY a.id"
    )
    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
    return [_account_from_row(row) for row in rows]


def _formula_param(formula: Formula | None) -> Jsonb | None:
    return Jsonb(formula.model_dump(mode="json")) if formula is not None else None


def _replace_inputs(cur: Cursor, account_id: int, input_ids: list[int]) -> None:
    cur.execute("DELETE FROM formula_inputs WHERE account_id = %s", (account_id,))
    if input_ids:
        cur.executemany(
            "INSERT INTO formula_inputs (account_id, input_id) VALUES (%s, %s)",
            [(account_id, input_id) for input_id in input_ids],
        )


def get_accounts(conn: Connection, *, include_retired: bool = True) -> list[Account]:
    """All accounts in id order, with their formula inputs."""
    where = "" if include_retired else "WHERE a.retired_at IS NULL"
    return _select_accounts(conn, where)


def get_account_by_name(
    conn: Connection, type: RecordType, name: str
) -> Account | None:
    accounts = _select_accounts(
        conn, "WHERE a.type = %s AND a.name = %s", (type.value, name)
    )
    return accounts[0] if accounts else None


def insert_account(conn: Connection, account: Account) -> Account:
    """Insert an account and its inputs. Returns the account with id and created_at set."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO accounts (name, type, formula, retired_at)
            VALUES (%s, %s, %s, %s)
            RETURNING id, created_at
            """,
            (
                account.name,
                account.type.value,
                _formula_param(account.formula),
                account.retired_at,
            ),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("INSERT returned no row")
        account_id, created_at = row
        _replace_inputs(cur, account_id, account.input_ids)
    return account.model_copy(update={"id": account_id, "created_at": created_at})
