"""Thin SQL layer. Functions here never commit; callers own the transaction.

Every account and snapshot function takes the workspace it acts in and
filters on it, so an id from another workspace behaves as if it did not
exist. The composite foreign keys in the schema back this up.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, LiteralString

from psycopg import Connection, Cursor
from psycopg.types.json import Jsonb

from sensibility.models import (
    Account,
    CashFlow,
    CashFlowCategory,
    CashFlowDirection,
    DailySummary,
    Formula,
    FrequencyUnit,
    Invite,
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


def get_snapshot_saved_at(
    conn: Connection, workspace_id: int, on: date
) -> datetime | None:
    """When this workspace's snapshot for `on` was saved (its newest row's
    created_at), or None if there is none. A same-day save that replaces
    rows keeps their created_at, so this is when the date was first saved,
    or when an account was last added to it."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT MAX(created_at) FROM snapshots WHERE workspace_id = %s AND date = %s",
            (workspace_id, on),
        )
        row = cur.fetchone()
    return row[0] if row else None


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


def get_user_by_sub(conn: Connection, idp_sub: str) -> User | None:
    with conn.cursor() as cur:
        cur.execute(f"SELECT {_USER_COLUMNS} FROM users WHERE idp_sub = %s", (idp_sub,))
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

_WORKSPACE_COLUMNS = "w.id, w.name, w.created_at, w.deleted_at"


def _workspace_from_row(row: tuple[Any, ...]) -> Workspace:
    return Workspace(id=row[0], name=row[1], created_at=row[2], deleted_at=row[3])


def insert_workspace(conn: Connection, name: str) -> Workspace:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO workspaces AS w (name) VALUES (%s)
            RETURNING {_WORKSPACE_COLUMNS}
            """,
            (name,),
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
            "UPDATE workspaces SET name = %s WHERE id = %s",
            (workspace.name, workspace.id),
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
    return (_workspace_from_row(row[:4]), Role(row[4])) if row else None


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
    return [(_workspace_from_row(row[:4]), Role(row[4])) for row in rows]


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


# --- invites ---------------------------------------------------------------

_INVITE_COLUMNS = """
    i.id, i.workspace_id, i.email, i.role, i.invited_by, i.created_at,
    i.expires_at, i.accepted_at, i.declined_at, i.revoked_at
"""


def _invite_from_row(row: tuple[Any, ...]) -> Invite:
    return Invite(
        id=row[0],
        workspace_id=row[1],
        email=row[2],
        role=Role(row[3]),
        invited_by=row[4],
        created_at=row[5],
        expires_at=row[6],
        accepted_at=row[7],
        declined_at=row[8],
        revoked_at=row[9],
    )


def insert_invite(
    conn: Connection,
    workspace_id: int,
    email: str,
    role: Role,
    invited_by: int,
    expires_at: datetime,
) -> Invite:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO workspace_invites AS i
                (workspace_id, email, role, invited_by, expires_at)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING {_INVITE_COLUMNS}
            """,
            (workspace_id, email, role.value, invited_by, expires_at),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("INSERT returned no row")
    return _invite_from_row(row)


def get_invite(
    conn: Connection, invite_id: int, *, for_update: bool = False
) -> Invite | None:
    lock: LiteralString = "FOR UPDATE" if for_update else ""
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {_INVITE_COLUMNS} FROM workspace_invites i WHERE i.id = %s {lock}",
            (invite_id,),
        )
        row = cur.fetchone()
    return _invite_from_row(row) if row else None


def get_open_invite(conn: Connection, workspace_id: int, email: str) -> Invite | None:
    """The open (unresolved, possibly expired) invite for this email, if any."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {_INVITE_COLUMNS} FROM workspace_invites i
            WHERE i.workspace_id = %s AND i.email = %s
              AND i.accepted_at IS NULL AND i.declined_at IS NULL
              AND i.revoked_at IS NULL
            """,
            (workspace_id, email),
        )
        row = cur.fetchone()
    return _invite_from_row(row) if row else None


def get_pending_workspace_invites(conn: Connection, workspace_id: int) -> list[Invite]:
    """Open, unexpired invites to this workspace, oldest first."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {_INVITE_COLUMNS} FROM workspace_invites i
            WHERE i.workspace_id = %s
              AND i.accepted_at IS NULL AND i.declined_at IS NULL
              AND i.revoked_at IS NULL AND i.expires_at > now()
            ORDER BY i.created_at, i.id
            """,
            (workspace_id,),
        )
        rows = cur.fetchall()
    return [_invite_from_row(row) for row in rows]


def get_pending_invites_for_email(
    conn: Connection, email: str
) -> list[tuple[Invite, Workspace]]:
    """Open, unexpired invites to live workspaces for this email."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {_INVITE_COLUMNS}, {_WORKSPACE_COLUMNS}
            FROM workspace_invites i
            JOIN workspaces w ON w.id = i.workspace_id
            WHERE i.email = %s AND w.deleted_at IS NULL
              AND i.accepted_at IS NULL AND i.declined_at IS NULL
              AND i.revoked_at IS NULL AND i.expires_at > now()
            ORDER BY i.created_at, i.id
            """,
            (email,),
        )
        rows = cur.fetchall()
    return [(_invite_from_row(row[:10]), _workspace_from_row(row[10:])) for row in rows]


def get_acceptable_invites_for_email(
    conn: Connection, email: str
) -> list[tuple[Invite, Workspace, str]]:
    """The pending invites for this email whose sender is still an owner of
    the (live) workspace, each with the sender's name (or email), oldest
    first. One query: the shell runs it on every page."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {_INVITE_COLUMNS}, {_WORKSPACE_COLUMNS},
                   COALESCE(NULLIF(u.name, ''), u.email)
            FROM workspace_invites i
            JOIN workspaces w ON w.id = i.workspace_id
            JOIN workspace_members m
              ON m.workspace_id = i.workspace_id AND m.user_id = i.invited_by
            JOIN users u ON u.id = i.invited_by
            WHERE i.email = %s AND w.deleted_at IS NULL AND m.role = 'owner'
              AND i.accepted_at IS NULL AND i.declined_at IS NULL
              AND i.revoked_at IS NULL AND i.expires_at > now()
            ORDER BY i.created_at, i.id
            """,
            (email,),
        )
        rows = cur.fetchall()
    return [
        (_invite_from_row(row[:10]), _workspace_from_row(row[10:14]), row[14])
        for row in rows
    ]


def set_invite_accepted(conn: Connection, invite_id: int, user_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE workspace_invites SET accepted_at = now(), accepted_by = %s
            WHERE id = %s
            """,
            (user_id, invite_id),
        )


def set_invite_declined(conn: Connection, invite_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE workspace_invites SET declined_at = now() WHERE id = %s",
            (invite_id,),
        )


def set_invite_revoked(conn: Connection, invite_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE workspace_invites SET revoked_at = now() WHERE id = %s",
            (invite_id,),
        )


def is_member_email(conn: Connection, workspace_id: int, email: str) -> bool:
    """Whether a member of this workspace currently has this email."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM workspace_members m JOIN users u ON u.id = m.user_id
            WHERE m.workspace_id = %s AND u.email = %s
            """,
            (workspace_id, email),
        )
        return cur.fetchone() is not None


# --- cash flows ------------------------------------------------------------

_CATEGORY_COLUMNS = "c.id, c.workspace_id, c.name, c.position"


def _category_from_row(row: tuple[Any, ...]) -> CashFlowCategory:
    return CashFlowCategory(
        id=row[0], workspace_id=row[1], name=row[2], position=row[3]
    )


def get_cash_flow_categories(
    conn: Connection, workspace_id: int
) -> list[CashFlowCategory]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {_CATEGORY_COLUMNS} FROM cash_flow_categories c
            WHERE c.workspace_id = %s ORDER BY c.position, c.id
            """,
            (workspace_id,),
        )
        rows = cur.fetchall()
    return [_category_from_row(row) for row in rows]


def get_cash_flow_category(
    conn: Connection, workspace_id: int, category_id: int
) -> CashFlowCategory | None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {_CATEGORY_COLUMNS} FROM cash_flow_categories c
            WHERE c.workspace_id = %s AND c.id = %s
            """,
            (workspace_id, category_id),
        )
        row = cur.fetchone()
    return _category_from_row(row) if row else None


def insert_cash_flow_category(
    conn: Connection, workspace_id: int, name: str
) -> CashFlowCategory:
    """Positioned after the workspace's existing categories."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO cash_flow_categories AS c (workspace_id, name, position)
            SELECT %s, %s, COALESCE(MAX(position) + 1, 0)
            FROM cash_flow_categories WHERE workspace_id = %s
            RETURNING {_CATEGORY_COLUMNS}
            """,
            (workspace_id, name, workspace_id),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("INSERT returned no row")
    return _category_from_row(row)


def update_cash_flow_category(conn: Connection, category: CashFlowCategory) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE cash_flow_categories SET name = %s, position = %s
            WHERE workspace_id = %s AND id = %s
            """,
            (category.name, category.position, category.workspace_id, category.id),
        )


def delete_cash_flow_category(
    conn: Connection, workspace_id: int, category_id: int
) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM cash_flow_categories WHERE workspace_id = %s AND id = %s",
            (workspace_id, category_id),
        )
        return cur.rowcount == 1


_CASH_FLOW_COLUMNS = """
    f.id, f.workspace_id, f.name, f.direction, f.amount, f.every, f.unit,
    f.category_id, f.description, f.is_estimate, f.created_at, f.updated_at
"""


def _cash_flow_from_row(row: tuple[Any, ...]) -> CashFlow:
    return CashFlow(
        id=row[0],
        workspace_id=row[1],
        name=row[2],
        direction=CashFlowDirection(row[3]),
        amount=Decimal(row[4]),
        every=row[5],
        unit=FrequencyUnit(row[6]),
        category_id=row[7],
        description=row[8],
        is_estimate=row[9],
        created_at=row[10],
        updated_at=row[11],
    )


def get_cash_flows(conn: Connection, workspace_id: int) -> list[CashFlow]:
    """Income first, then by category order (uncategorized last), then name."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {_CASH_FLOW_COLUMNS}
            FROM cash_flows f
            LEFT JOIN cash_flow_categories c
                ON c.workspace_id = f.workspace_id AND c.id = f.category_id
            WHERE f.workspace_id = %s
            ORDER BY f.direction DESC, c.position NULLS LAST, c.id,
                     lower(f.name), f.id
            """,
            (workspace_id,),
        )
        rows = cur.fetchall()
    return [_cash_flow_from_row(row) for row in rows]


def get_cash_flow(
    conn: Connection, workspace_id: int, cash_flow_id: int
) -> CashFlow | None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {_CASH_FLOW_COLUMNS} FROM cash_flows f
            WHERE f.workspace_id = %s AND f.id = %s
            """,
            (workspace_id, cash_flow_id),
        )
        row = cur.fetchone()
    return _cash_flow_from_row(row) if row else None


def _cash_flow_params(flow: CashFlow) -> tuple[Any, ...]:
    return (
        flow.name,
        flow.direction.value,
        flow.amount,
        flow.every,
        flow.unit.value,
        flow.category_id,
        flow.description,
        flow.is_estimate,
    )


def insert_cash_flow(conn: Connection, workspace_id: int, flow: CashFlow) -> CashFlow:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO cash_flows AS f
                (name, direction, amount, every, unit, category_id, description,
                 is_estimate, workspace_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {_CASH_FLOW_COLUMNS}
            """,
            (*_cash_flow_params(flow), workspace_id),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("INSERT returned no row")
    return _cash_flow_from_row(row)


def update_cash_flow(conn: Connection, workspace_id: int, flow: CashFlow) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE cash_flows SET
                name = %s, direction = %s, amount = %s, every = %s, unit = %s,
                category_id = %s, description = %s, is_estimate = %s,
                updated_at = now()
            WHERE workspace_id = %s AND id = %s
            """,
            (*_cash_flow_params(flow), workspace_id, flow.id),
        )


def delete_cash_flow(conn: Connection, workspace_id: int, cash_flow_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM cash_flows WHERE workspace_id = %s AND id = %s",
            (workspace_id, cash_flow_id),
        )
        return cur.rowcount == 1
