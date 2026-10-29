"""The connection pool behind get_connection_context (db.py)."""

import pytest

from sensibility import db
from sensibility.config import get_settings


@pytest.fixture
def pooled(db_connection, db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    get_settings.cache_clear()
    yield
    db.close_pools()
    get_settings.cache_clear()


def _users(conn) -> int:
    return conn.execute("SELECT count(*) FROM users").fetchone()[0]


@pytest.mark.db
def test_connections_are_reused(pooled):
    # The pool may open a second connection while filling, and it hands
    # them out in turn, so count the connections rather than expect one.
    pids = set()
    for _ in range(10):
        with db.get_connection_context() as conn:
            pids.add(conn.info.backend_pid)
    assert len(pids) <= 2


@pytest.mark.db
def test_what_a_block_did_not_commit_is_rolled_back(pooled):
    with db.get_connection_context() as conn:
        before = _users(conn)
        conn.execute(
            "INSERT INTO users (idp_sub, email) VALUES ('uncommitted', 'u@example.com')"
        )
    with db.get_connection_context() as conn:
        assert _users(conn) == before


@pytest.mark.db
def test_a_block_that_raised_leaves_a_usable_connection(pooled):
    with pytest.raises(ZeroDivisionError):
        with db.get_connection_context() as conn:
            conn.execute("SELECT 1")
            raise ZeroDivisionError
    with db.get_connection_context() as conn:
        assert conn.execute("SELECT 1").fetchone() == (1,)


@pytest.mark.db
def test_a_failed_statement_is_cleared_before_reuse(pooled):
    with db.get_connection_context() as conn:
        with pytest.raises(Exception):
            conn.execute("SELECT * FROM no_such_table")
    with db.get_connection_context() as conn:
        assert conn.execute("SELECT 1").fetchone() == (1,)


@pytest.mark.db
def test_a_dead_connection_is_replaced(pooled, db_connection):
    with db.get_connection_context() as conn:
        pid = conn.info.backend_pid
    # As Neon does to an idle connection when it suspends.
    db_connection.execute("SELECT pg_terminate_backend(%s)", (pid,))
    db_connection.commit()
    with db.get_connection_context() as conn:
        assert conn.execute("SELECT 1").fetchone() == (1,)
        assert conn.info.backend_pid != pid
