import os
import subprocess
from pathlib import Path

import psycopg
import pytest
from testcontainers.community.postgres import PostgresContainer

from tests.support import SEED_USER, USER_ID, WS


@pytest.fixture(scope="session")
def postgres_container():
    """Start a PostgreSQL container for the test session."""
    with PostgresContainer("postgres:17") as pg:
        yield pg


@pytest.fixture(scope="session")
def db_url(postgres_container):
    """Get the database URL from the container."""
    # testcontainers returns: postgresql+psycopg2://user:pass@host:port/db
    # Convert to standard format: postgresql://user:pass@host:port/db
    url = postgres_container.get_connection_url()
    url = url.replace("postgresql+psycopg2://", "postgresql://")
    # Disable SSL for test container (not configured for SSL)
    return f"{url}?sslmode=disable"


@pytest.fixture(scope="session")
def _run_migrations(db_url):
    """Run dbmate migrations against the test database.

    --no-dump-schema keeps the run from rewriting db/schema.sql, which should
    only change when a migration is applied to a real database.
    """
    project_root = Path(__file__).parent.parent

    # Run dbmate up with the test database URL
    result = subprocess.run(
        ["dbmate", "--no-dump-schema", "up"],
        cwd=project_root,
        env={**os.environ, "DATABASE_URL": db_url},
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        pytest.fail(f"dbmate up failed:\n{result.stderr}\n{result.stdout}")


@pytest.fixture
def db_connection(db_url, _run_migrations):
    """A database connection, seeded with workspace WS owned by user USER_ID."""
    conn = psycopg.connect(db_url)
    _truncate(conn)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (idp_sub, email, name) VALUES (%s, %s, %s)",
            (SEED_USER["sub"], SEED_USER["email"], SEED_USER["name"]),
        )
        cur.execute("INSERT INTO workspaces (name) VALUES ('Test')")
        cur.execute(
            "INSERT INTO workspace_members (workspace_id, user_id, role) VALUES (%s, %s, 'owner')",
            (WS, USER_ID),
        )
    conn.commit()

    yield conn

    # Clean up: roll back anything left open, then truncate every table
    try:
        conn.rollback()
        _truncate(conn)
    finally:
        conn.close()


def _truncate(conn, attempts: int = 5) -> None:
    """Empty every table. A browser test's server can still be answering the
    page's last request, and Postgres may then pick the TRUNCATE as a
    deadlock's victim; that is retried, as Postgres expects."""
    for attempt in range(attempts):
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    TRUNCATE TABLE snapshots, formula_inputs, accounts,
                                   cash_flows, cash_flow_categories,
                                   workspace_invites, workspace_members,
                                   workspaces, users
                    RESTART IDENTITY CASCADE
                    """
                )
            conn.commit()
            return
        except psycopg.errors.DeadlockDetected:
            conn.rollback()
            if attempt == attempts - 1:
                raise


@pytest.fixture(autouse=True)
def skip_db_tests_in_ci(request):
    """Skip database tests in CI if Docker is not available."""
    if request.node.get_closest_marker("db"):
        if os.getenv("CI") == "true" and os.getenv("SKIP_DB_TESTS") == "true":
            pytest.skip("Skipping DB tests in CI (Docker not available)")


@pytest.fixture
def client(db_connection, db_url, monkeypatch):
    """A TestClient wired to the test container. db_connection handles cleanup.

    It sends the API's CSRF header (web/csrf.py) on every request, as the SPA
    does on every mutation; test_csrf.py takes it off to check the refusal."""
    from tests.web_support import API_HEADERS, SECRET

    monkeypatch.setenv("SECRET_KEY", SECRET)
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.delenv("ALLOWED_EMAILS", raising=False)

    from fastapi.testclient import TestClient

    from sensibility.config import get_settings
    from sensibility.web.app import app

    get_settings.cache_clear()
    with TestClient(app, headers=API_HEADERS) as test_client:
        yield test_client
    get_settings.cache_clear()


@pytest.fixture
def mcp_env(monkeypatch):
    """Configure /mcp for tests: our resource and issuer, and identity's
    keys replaced by the test key (tests/mcp_support.py mints tokens)."""
    from sensibility.mcp import tokens
    from tests.mcp_support import IDP_URL, ISSUER, RESOURCE, StaticKeys

    monkeypatch.setenv("MCP_RESOURCE_URL", RESOURCE)
    monkeypatch.setenv("IDP_ISSUER", ISSUER)
    monkeypatch.setenv("IDP_URL", IDP_URL)
    monkeypatch.setattr(tokens, "key_source", lambda config: StaticKeys())
