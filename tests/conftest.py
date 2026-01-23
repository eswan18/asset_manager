import os
from pathlib import Path

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def postgres_container():
    """Start a PostgreSQL container for the test session."""
    with PostgresContainer("postgres:16") as pg:
        yield pg


@pytest.fixture(scope="session")
def db_url(postgres_container):
    """Get the database URL from the container."""
    return postgres_container.get_connection_url()


@pytest.fixture(scope="session")
def _run_migrations(db_url):
    """Run yoyo migrations against the test database."""
    # Convert SQLAlchemy URL to psycopg format
    # testcontainers returns: postgresql+psycopg2://user:pass@host:port/db
    # We need: postgresql://user:pass@host:port/db
    psycopg_url = db_url.replace("postgresql+psycopg2://", "postgresql://")

    migrations_dir = Path(__file__).parent.parent / "migrations"

    # Read and execute the migration SQL directly
    migration_file = migrations_dir / "0001_create_records_table.sql"
    with open(migration_file) as f:
        migration_sql = f.read()

    # Remove the yoyo header comment
    lines = migration_sql.split("\n")
    sql_lines = [line for line in lines if not line.strip().startswith("-- depends:")]
    migration_sql = "\n".join(sql_lines)

    with psycopg.connect(psycopg_url) as conn:
        with conn.cursor() as cur:
            cur.execute(migration_sql)
        conn.commit()


@pytest.fixture
def db_connection(db_url, _run_migrations):
    """Get a database connection for testing."""
    psycopg_url = db_url.replace("postgresql+psycopg2://", "postgresql://")
    conn = psycopg.connect(psycopg_url)

    yield conn

    # Clean up: truncate tables after each test
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE records RESTART IDENTITY")
    conn.commit()
    conn.close()


@pytest.fixture(autouse=True)
def skip_db_tests_in_ci(request):
    """Skip database tests in CI if Docker is not available."""
    if request.node.get_closest_marker("db"):
        if os.getenv("CI") == "true" and os.getenv("SKIP_DB_TESTS") == "true":
            pytest.skip("Skipping DB tests in CI (Docker not available)")
