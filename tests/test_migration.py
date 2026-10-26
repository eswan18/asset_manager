"""Apply the create_accounts migration to legacy rows and check the backfill."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

MIGRATIONS = sorted((Path(__file__).parent.parent / "db" / "migrations").glob("*.sql"))


def split_migration(path: Path) -> tuple[str, str]:
    text = path.read_text()
    up_marker, down_marker = "-- migrate:up", "-- migrate:down"
    up = text[text.index(up_marker) + len(up_marker) : text.index(down_marker)]
    down = text[text.index(down_marker) + len(down_marker) :]
    return up, down


@pytest.fixture
def fresh_db_url(db_url):
    """A throwaway database in the same container, with no migrations applied."""
    fresh = urlunsplit(urlsplit(db_url)._replace(path="/migration_test"))
    with psycopg.connect(db_url, autocommit=True) as admin:
        admin.execute("DROP DATABASE IF EXISTS migration_test")
        admin.execute("CREATE DATABASE migration_test")
    yield fresh
    with psycopg.connect(db_url, autocommit=True) as admin:
        admin.execute("DROP DATABASE IF EXISTS migration_test")


def _columns(conn, table: str) -> set[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
        (table,),
    ).fetchall()
    return {r[0] for r in rows}


@pytest.mark.db
def test_create_accounts_migration_backfills_and_reverses(fresh_db_url):
    create_snapshots, create_accounts = MIGRATIONS[0], MIGRATIONS[1]
    assert "create_accounts" in create_accounts.name

    with psycopg.connect(fresh_db_url) as conn:
        # psycopg runs multi-statement strings when no parameters are passed.
        conn.execute(split_migration(create_snapshots)[0])
        legacy = [
            (date(2024, 1, 10), "asset", "Savings", Decimal("100.00")),
            (date(2024, 1, 10), "liability", "Card", Decimal("50.00")),
            (date(2024, 2, 10), "asset", "Savings", Decimal("120.00")),
            (date(2024, 2, 10), "asset", "Brokerage", Decimal("500.00")),
        ]
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO snapshots (date, type, description, amount) VALUES (%s, %s, %s, %s)",
                legacy,
            )
        conn.commit()

        conn.execute(split_migration(create_accounts)[0])
        conn.commit()

        accounts = conn.execute(
            "SELECT name, type FROM accounts ORDER BY id"
        ).fetchall()
        assert accounts == [
            ("Savings", "asset"),
            ("Card", "liability"),
            ("Brokerage", "asset"),
        ]

        rows = conn.execute(
            """
            SELECT s.date, a.type, a.name, s.amount
            FROM snapshots s JOIN accounts a ON a.id = s.account_id
            """
        ).fetchall()
        assert sorted(rows) == sorted(legacy)
        assert {"type", "description"}.isdisjoint(_columns(conn, "snapshots"))
        assert "account_id" in _columns(conn, "snapshots")

        conn.execute(split_migration(create_accounts)[1])
        conn.commit()

        restored = conn.execute(
            "SELECT date, type, description, amount FROM snapshots"
        ).fetchall()
        assert sorted(restored) == sorted(legacy)
        assert "account_id" not in _columns(conn, "snapshots")
        assert conn.execute("SELECT to_regclass('accounts')").fetchone() == (None,)


def _apply(conn, migrations, part: int = 0) -> None:
    for migration in migrations:
        conn.execute(split_migration(migration)[part])
    conn.commit()


WORKSPACES = next(m for m in MIGRATIONS if "add_users_and_workspaces" in m.name)
BEFORE_WORKSPACES = MIGRATIONS[: MIGRATIONS.index(WORKSPACES)]


@pytest.mark.db
def test_workspaces_migration_moves_existing_data_into_one_owned_workspace(
    fresh_db_url,
):
    with psycopg.connect(fresh_db_url) as conn:
        _apply(conn, BEFORE_WORKSPACES)
        conn.execute(
            """
            INSERT INTO accounts (name, type) VALUES ('Schwab', 'asset'), ('Cash', 'asset');
            INSERT INTO accounts (name, type, formula) VALUES
                ('Tax', 'liability', '{"kind": "proportional", "rate": "0.15"}');
            INSERT INTO formula_inputs (account_id, input_id) VALUES (3, 1);
            INSERT INTO snapshots (date, account_id, amount) VALUES
                ('2026-10-01', 1, 1000), ('2026-10-01', 2, 50), ('2026-10-01', 3, 150);
            """
        )
        conn.commit()

        _apply(conn, [WORKSPACES])

        assert conn.execute("SELECT id, name, timezone FROM workspaces").fetchall() == [
            (1, "Personal", "America/Chicago")
        ]
        assert conn.execute(
            "SELECT id, idp_sub, email, is_admin FROM users"
        ).fetchall() == [(1, None, "ethanpswan@gmail.com", True)]
        assert conn.execute(
            "SELECT workspace_id, user_id, role FROM workspace_members"
        ).fetchall() == [(1, 1, "owner")]
        for table in ("accounts", "formula_inputs", "snapshots"):
            assert conn.execute(
                f"SELECT DISTINCT workspace_id FROM {table}"
            ).fetchall() == [(1,)], table

        # Names are unique per workspace now, not globally.
        conn.execute(
            """
            INSERT INTO workspaces (name, timezone) VALUES ('Other', 'UTC');
            INSERT INTO accounts (workspace_id, name, type) VALUES (2, 'Schwab', 'asset');
            """
        )
        conn.commit()
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(
                "INSERT INTO accounts (workspace_id, name, type) VALUES (2, 'Schwab', 'asset')"
            )
        conn.rollback()

        # The database refuses rows that cross workspaces, whatever the app does.
        crossing = [
            # workspace 2's formula reading workspace 1's account
            "INSERT INTO formula_inputs (workspace_id, account_id, input_id) VALUES (2, 4, 1)",
            # a workspace 2 snapshot row for workspace 1's account
            "INSERT INTO snapshots (workspace_id, date, account_id, amount) VALUES (2, '2026-10-02', 1, 1)",
            # a workspace 1 snapshot row for workspace 2's account
            "INSERT INTO snapshots (workspace_id, date, account_id, amount) VALUES (1, '2026-10-02', 4, 1)",
        ]
        for statement in crossing:
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                conn.execute(statement)
            conn.rollback()

        conn.execute("DELETE FROM accounts WHERE workspace_id = 2")
        conn.execute("DELETE FROM workspaces WHERE id = 2")
        conn.commit()
        _apply(conn, [WORKSPACES], part=1)

        assert conn.execute("SELECT to_regclass('workspaces')").fetchone() == (None,)
        assert conn.execute("SELECT to_regclass('users')").fetchone() == (None,)
        for table in ("accounts", "formula_inputs", "snapshots"):
            assert "workspace_id" not in _columns(conn, table), table
        assert conn.execute(
            "SELECT date::text, account_id, amount FROM snapshots ORDER BY account_id"
        ).fetchall() == [
            ("2026-10-01", 1, Decimal("1000.00")),
            ("2026-10-01", 2, Decimal("50.00")),
            ("2026-10-01", 3, Decimal("150.00")),
        ]
        assert conn.execute("SELECT * FROM formula_inputs").fetchall() == [(3, 1)]


@pytest.mark.db
def test_workspaces_migration_on_an_empty_database_creates_no_rows(fresh_db_url):
    with psycopg.connect(fresh_db_url) as conn:
        _apply(conn, BEFORE_WORKSPACES)
        _apply(conn, [WORKSPACES])
        for table in ("workspaces", "users", "workspace_members"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)


@pytest.mark.db
def test_every_migration_reverses_cleanly(fresh_db_url):
    """All ups, all downs in reverse, then all ups again, on an empty database."""
    with psycopg.connect(fresh_db_url) as conn:
        _apply(conn, MIGRATIONS)
        _apply(conn, list(reversed(MIGRATIONS)), part=1)
        tables = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
        assert tables == []
        _apply(conn, MIGRATIONS)


@pytest.mark.db
def test_an_invite_has_at_most_one_resolution(db_connection):
    from tests.support import USER_ID, WS

    with pytest.raises(psycopg.errors.CheckViolation):
        db_connection.execute(
            """
            INSERT INTO workspace_invites
                (workspace_id, email, role, invited_by, expires_at, declined_at, revoked_at)
            VALUES (%s, 'a@b.com', 'viewer', %s, now(), now(), now())
            """,
            (WS, USER_ID),
        )


DROP_TIMEZONE = next(m for m in MIGRATIONS if "drop_workspace_timezone" in m.name)


@pytest.mark.db
def test_drop_workspace_timezone_migration_and_its_reversal(fresh_db_url):
    """Up drops the column, keeping the rows; down brings it back as Chicago."""
    with psycopg.connect(fresh_db_url) as conn:
        _apply(conn, MIGRATIONS[: MIGRATIONS.index(DROP_TIMEZONE)])
        conn.execute(
            "INSERT INTO workspaces (name, timezone) VALUES ('A', 'UTC'), ('B', 'Asia/Tokyo')"
        )
        conn.commit()

        _apply(conn, [DROP_TIMEZONE])
        assert "timezone" not in _columns(conn, "workspaces")
        assert conn.execute(
            "SELECT id, name FROM workspaces ORDER BY id"
        ).fetchall() == [
            (1, "A"),
            (2, "B"),
        ]

        _apply(conn, [DROP_TIMEZONE], part=1)
        assert conn.execute(
            "SELECT id, timezone FROM workspaces ORDER BY id"
        ).fetchall() == [(1, "America/Chicago"), (2, "America/Chicago")]
        with pytest.raises(psycopg.errors.NotNullViolation):
            conn.execute("INSERT INTO workspaces (name, timezone) VALUES ('C', NULL)")
        conn.rollback()
        # No lasting default: the restored column is as it was, required.
        with pytest.raises(psycopg.errors.NotNullViolation):
            conn.execute("INSERT INTO workspaces (name) VALUES ('C')")
