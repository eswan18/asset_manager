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
