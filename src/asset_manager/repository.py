"""Thin SQL layer. Functions here never commit; callers own the transaction.

Every account and snapshot function takes the workspace it acts in and
filters on it, so an id from another workspace behaves as if it did not
exist. The composite foreign keys in the schema back this up.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, LiteralString

from psycopg import Connection, Cursor
from psycopg.types.json import Jsonb

from asset_manager.models import (
    Account,
    DailySummary,
    Formula,
    Member,
    Record,
    RecordType,
    Role,
    User,
    Workspace,
)

_RECORD_SELECT = """
    SELECT s.id, s.date, s.account_id, a.type, a.name, s.amount, s.created_at
    FROM snapshots s
    JOIN accounts a ON a.workspace_id = s.workspace_id AND a.id = s.account_id
    WHERE s.workspace_id = %s
"""

_ACCOUNT_SELECT = """
    SELECT a.id, a.workspace_id, a.name, a.type, a.formula, a.retired_at,
           a.created_at, a.category,
           COALESCE(
               array_agg(fi.input_id ORDER BY fi.input_id)
                   FILTER (WHERE fi.input_id IS NOT NULL),
               '{}'
           ) AS input_ids
    FROM accounts a
    LEFT JOIN formula_inputs fi ON fi.account_id = a.id
    WHERE a.workspace_id = %s
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
    workspace_id: int,
    where: LiteralString = "",
    params: tuple[Any, ...] = (),
    order: LiteralString = "s.date, a.type, a.name",
) -> list[Record]:
    with conn.cursor() as cur:
        cur.execute(
            f"{_RECORD_SELECT} {where} ORDER BY {order}", (workspace_id, *params)
        )
        rows = cur.fetchall()
    return [_record_from_row(row) for row in rows]


def get_all_records(conn: Connection, workspace_id: int) -> list[Record]:
    """Fetch all snapshot records, joined to their account."""
    return _select_records(conn, workspace_id)


def get_records_by_date_range(
    conn: Connection, workspace_id: int, start_date: date, end_date: date
) -> list[Record]:
    """Fetch records within a date range."""
    return _select_records(
        conn,
        workspace_id,
        "AND s.date >= %s AND s.date <= %s",
        (start_date, end_date),
    )


def get_latest_snapshot_records(conn: Connection, workspace_id: int) -> list[Record]:
    """Fetch records for this workspace's most recent snapshot date."""
    return _select_records(
        conn,
        workspace_id,
        "AND s.date = (SELECT MAX(date) FROM snapshots WHERE workspace_id = %s)",
        (workspace_id,),
        order="a.type, a.name",
    )


def get_account_history(
    conn: Connection, workspace_id: int, account_id: int
) -> list[Record]:
    """Every snapshot row for one account, newest first."""
    return _select_records(
        conn, workspace_id, "AND s.account_id = %s", (account_id,), order="s.date DESC"
    )


def get_summary_by_date(conn: Connection, workspace_id: int) -> list[DailySummary]:
    """Get aggregated totals by date and type."""
    query = """
        SELECT s.date, a.type, SUM(s.amount) AS total_amount
        FROM snapshots s
        JOIN accounts a ON a.workspace_id = s.workspace_id AND a.id = s.account_id
        WHERE s.workspace_id = %s
        GROUP BY s.date, a.type
        ORDER BY s.date, a.type
    """
    with conn.cursor() as cur:
        cur.execute(query, (workspace_id,))
        rows = cur.fetchall()
    return [
        DailySummary(date=row[0], type=RecordType(row[1]), total_amount=Decimal(row[2]))
        for row in rows
    ]


def upsert_amounts(
    conn: Connection, workspace_id: int, as_of: date, amounts: dict[int, Decimal]
) -> int:
    """Write one row per account for `as_of`, replacing any existing row for that date.

    An account id from another workspace violates the composite foreign key.
    """
    if not amounts:
        return 0
    query = """
        INSERT INTO snapshots (workspace_id, date, account_id, amount)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (date, account_id) DO UPDATE SET amount = EXCLUDED.amount
    """
    with conn.cursor() as cur:
        cur.executemany(
            query,
            [(workspace_id, as_of, aid, amount) for aid, amount in amounts.items()],
        )
    return len(amounts)


# --- accounts --------------------------------------------------------------


def _account_from_row(row: tuple[Any, ...]) -> Account:
    return Account.model_validate(
        {
            "id": row[0],
            "workspace_id": row[1],
            "name": row[2],
            "type": row[3],
            "formula": row[4],
            "retired_at": row[5],
            "created_at": row[6],
            "category": row[7],
            "input_ids": list(row[8]),
        }
    )


def _select_accounts(
    conn: Connection,
    workspace_id: int,
    where: LiteralString = "",
    params: tuple[Any, ...] = (),
) -> list[Account]:
    with conn.cursor() as cur:
        cur.execute(
            f"{_ACCOUNT_SELECT} {where} GROUP BY a.id ORDER BY lower(a.name), a.id",
            (workspace_id, *params),
        )
        rows = cur.fetchall()
    return [_account_from_row(row) for row in rows]


def _formula_param(formula: Formula | None) -> Jsonb | None:
    return Jsonb(formula.model_dump(mode="json")) if formula is not None else None


def _category_param(account: Account) -> str | None:
    return account.category.value if account.category is not None else None


def _replace_inputs(
    cur: Cursor, workspace_id: int, account_id: int, input_ids: list[int]
) -> None:
    cur.execute(
        "DELETE FROM formula_inputs WHERE workspace_id = %s AND account_id = %s",
        (workspace_id, account_id),
    )
    if input_ids:
        cur.executemany(
            """
            INSERT INTO formula_inputs (workspace_id, account_id, input_id)
            VALUES (%s, %s, %s)
            """,
            [(workspace_id, account_id, input_id) for input_id in input_ids],
        )


def get_accounts(
    conn: Connection, workspace_id: int, *, include_retired: bool = True
) -> list[Account]:
    """All accounts in case-insensitive name order, with their formula inputs."""
    where = "" if include_retired else "AND a.retired_at IS NULL"
    return _select_accounts(conn, workspace_id, where)


def get_account_by_name(
    conn: Connection, workspace_id: int, type: RecordType, name: str
) -> Account | None:
    accounts = _select_accounts(
        conn, workspace_id, "AND a.type = %s AND a.name = %s", (type.value, name)
    )
    return accounts[0] if accounts else None


def insert_account(conn: Connection, workspace_id: int, account: Account) -> Account:
    """Insert an account and its inputs. Returns the account with id and created_at set."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO accounts (workspace_id, name, type, category, formula, retired_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, created_at
            """,
            (
                workspace_id,
                account.name,
                account.type.value,
                _category_param(account),
                _formula_param(account.formula),
                account.retired_at,
            ),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("INSERT returned no row")
        account_id, created_at = row
        _replace_inputs(cur, workspace_id, account_id, account.input_ids)
    return account.model_copy(
        update={
            "id": account_id,
            "workspace_id": workspace_id,
            "created_at": created_at,
        }
    )


def get_account(conn: Connection, workspace_id: int, account_id: int) -> Account | None:
    accounts = _select_accounts(conn, workspace_id, "AND a.id = %s", (account_id,))
    return accounts[0] if accounts else None


def update_account(conn: Connection, workspace_id: int, account: Account) -> None:
    """Replace name, category, formula document, and inputs.

    Type and retirement are untouched.
    """
    if account.id is None:
        raise ValueError("Cannot update an account without an id")
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE accounts SET name = %s, category = %s, formula = %s
            WHERE workspace_id = %s AND id = %s
            """,
            (
                account.name,
                _category_param(account),
                _formula_param(account.formula),
                workspace_id,
                account.id,
            ),
        )
        if cur.rowcount != 1:
            raise ValueError(f"Account {account.id} is not in workspace {workspace_id}")
        _replace_inputs(cur, workspace_id, account.id, account.input_ids)


def set_formula(
    conn: Connection, workspace_id: int, account_id: int, formula: Formula | None
) -> None:
    """Replace only the formula document, leaving inputs alone."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE accounts SET formula = %s WHERE workspace_id = %s AND id = %s",
            (_formula_param(formula), workspace_id, account_id),
        )


def set_retired_at(
    conn: Connection, workspace_id: int, account_id: int, retired_at: date | None
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE accounts SET retired_at = %s WHERE workspace_id = %s AND id = %s",
            (retired_at, workspace_id, account_id),
        )


def get_dependents(
    conn: Connection, workspace_id: int, account_id: int
) -> list[Account]:
    """Active computed accounts that list `account_id` as an input."""
    return _select_accounts(
        conn,
        workspace_id,
        """
        AND a.retired_at IS NULL
        AND a.id IN (
            SELECT account_id FROM formula_inputs
            WHERE workspace_id = %s AND input_id = %s
        )
        """,
        (workspace_id, account_id),
    )


def get_latest_entry(
    conn: Connection, workspace_id: int, account_id: int
) -> tuple[date, Decimal] | None:
    """The (date, amount) of this account's own most recent snapshot row, if any."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT date, amount FROM snapshots
            WHERE workspace_id = %s AND account_id = %s
            ORDER BY date DESC LIMIT 1
            """,
            (workspace_id, account_id),
        )
        row = cur.fetchone()
    return (row[0], Decimal(row[1])) if row else None


def get_latest_amount(
    conn: Connection, workspace_id: int, account_id: int
) -> Decimal | None:
    """The amount in this account's own most recent snapshot row, if any."""
    entry = get_latest_entry(conn, workspace_id, account_id)
    return entry[1] if entry else None


# --- users -----------------------------------------------------------------

_USER_COLUMNS = "id, idp_sub, email, name, is_admin, created_at, last_login_at"


def _user_from_row(row: tuple[Any, ...]) -> User:
    return User(
        id=row[0],
        idp_sub=row[1],
        email=row[2],
        name=row[3],
        is_admin=row[4],
        created_at=row[5],
        last_login_at=row[6],
    )


def _one_user(cur: Cursor) -> User | None:
    row = cur.fetchone()
    return _user_from_row(row) if row else None


def get_user(conn: Connection, user_id: int) -> User | None:
    with conn.cursor() as cur:
        cur.execute(f"SELECT {_USER_COLUMNS} FROM users WHERE id = %s", (user_id,))
        return _one_user(cur)


def update_login_by_sub(
    conn: Connection, idp_sub: str, email: str, name: str | None
) -> User | None:
    """Refresh a known user's email and name and stamp the login."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE users SET email = %s, name = %s, last_login_at = now()
            WHERE idp_sub = %s
            RETURNING {_USER_COLUMNS}
            """,
            (email, name, idp_sub),
        )
        return _one_user(cur)


def claim_unclaimed_user(
    conn: Connection, idp_sub: str, email: str, name: str | None
) -> User | None:
    """Attach a sub to the pre-provisioned row for this email, if one exists."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE users SET idp_sub = %s, name = COALESCE(%s, name),
                             last_login_at = now()
            WHERE email = %s AND idp_sub IS NULL
            RETURNING {_USER_COLUMNS}
            """,
            (idp_sub, name, email),
        )
        return _one_user(cur)


def insert_user(conn: Connection, idp_sub: str, email: str, name: str | None) -> User:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO users (idp_sub, email, name, last_login_at)
            VALUES (%s, %s, %s, now())
            RETURNING {_USER_COLUMNS}
            """,
            (idp_sub, email, name),
        )
        user = _one_user(cur)
    if user is None:
        raise RuntimeError("INSERT returned no row")
    return user


# --- workspaces ------------------------------------------------------------

_WORKSPACE_COLUMNS = "w.id, w.name, w.timezone, w.created_at, w.deleted_at"


def _workspace_from_row(row: tuple[Any, ...]) -> Workspace:
    return Workspace(
        id=row[0], name=row[1], timezone=row[2], created_at=row[3], deleted_at=row[4]
    )


def insert_workspace(conn: Connection, name: str, timezone: str) -> Workspace:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO workspaces AS w (name, timezone) VALUES (%s, %s)
            RETURNING {_WORKSPACE_COLUMNS}
            """,
            (name, timezone),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("INSERT returned no row")
    return _workspace_from_row(row)


def get_workspace(conn: Connection, workspace_id: int) -> Workspace | None:
    """A workspace by id, including a soft-deleted one."""
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {_WORKSPACE_COLUMNS} FROM workspaces w WHERE w.id = %s",
            (workspace_id,),
        )
        row = cur.fetchone()
    return _workspace_from_row(row) if row else None


def update_workspace(conn: Connection, workspace: Workspace) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE workspaces SET name = %s, timezone = %s WHERE id = %s",
            (workspace.name, workspace.timezone, workspace.id),
        )


def soft_delete_workspace(conn: Connection, workspace_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE workspaces SET deleted_at = now() WHERE id = %s AND deleted_at IS NULL",
            (workspace_id,),
        )


# --- members ---------------------------------------------------------------


def add_member(conn: Connection, workspace_id: int, user_id: int, role: Role) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO workspace_members (workspace_id, user_id, role)
            VALUES (%s, %s, %s)
            """,
            (workspace_id, user_id, role.value),
        )


def get_access(
    conn: Connection, workspace_id: int, user_id: int
) -> tuple[Workspace, Role] | None:
    """The live workspace and this user's role in it, or None if either is missing."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {_WORKSPACE_COLUMNS}, m.role
            FROM workspaces w
            JOIN workspace_members m ON m.workspace_id = w.id
            WHERE w.id = %s AND m.user_id = %s AND w.deleted_at IS NULL
            """,
            (workspace_id, user_id),
        )
        row = cur.fetchone()
    return (_workspace_from_row(row[:5]), Role(row[5])) if row else None


def get_memberships(conn: Connection, user_id: int) -> list[tuple[Workspace, Role]]:
    """This user's live workspaces with their role, oldest membership first."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {_WORKSPACE_COLUMNS}, m.role
            FROM workspaces w
            JOIN workspace_members m ON m.workspace_id = w.id
            WHERE m.user_id = %s AND w.deleted_at IS NULL
            ORDER BY m.created_at, w.id
            """,
            (user_id,),
        )
        rows = cur.fetchall()
    return [(_workspace_from_row(row[:5]), Role(row[5])) for row in rows]


def get_members(
    conn: Connection, workspace_id: int, *, for_update: bool = False
) -> list[Member]:
    """Every member of a workspace, oldest first.

    `for_update` locks the membership rows until the transaction ends, so
    two concurrent changes cannot both remove the last owner.
    """
    lock: LiteralString = "FOR UPDATE OF m" if for_update else ""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT m.user_id, u.email, u.name, m.role, m.created_at
            FROM workspace_members m
            JOIN users u ON u.id = m.user_id
            WHERE m.workspace_id = %s
            ORDER BY m.created_at, m.user_id
            {lock}
            """,
            (workspace_id,),
        )
        rows = cur.fetchall()
    return [
        Member(user_id=r[0], email=r[1], name=r[2], role=Role(r[3]), joined_at=r[4])
        for r in rows
    ]


def set_member_role(
    conn: Connection, workspace_id: int, user_id: int, role: Role
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE workspace_members SET role = %s
            WHERE workspace_id = %s AND user_id = %s
            """,
            (role.value, workspace_id, user_id),
        )


def delete_member(conn: Connection, workspace_id: int, user_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM workspace_members WHERE workspace_id = %s AND user_id = %s",
            (workspace_id, user_id),
        )
