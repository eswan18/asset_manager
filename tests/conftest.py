import os
import re
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


def extract_up_migration(sql_content: str) -> str:
    """Extract the 'up' migration section from dbmate format."""
    # Find content between -- migrate:up and -- migrate:down
    match = re.search(
        r"--\s*migrate:up\s*\n(.*?)(?:--\s*migrate:down|$)",
        sql_content,
        re.DOTALL,
    )
    if match:
        return match.group(1).strip()
    return sql_content


@pytest.fixture(scope="session")
def _run_migrations(db_url):
    """Run dbmate migrations against the test database."""
    # Convert SQLAlchemy URL to psycopg format
    # testcontainers returns: postgresql+psycopg2://user:pass@host:port/db
    # We need: postgresql://user:pass@host:port/db
    psycopg_url = db_url.replace("postgresql+psycopg2://", "postgresql://")

    migrations_dir = Path(__file__).parent.parent / "db" / "migrations"

    # Find and sort all migration files
    migration_files = sorted(migrations_dir.glob("*.sql"))

    with psycopg.connect(psycopg_url) as conn:
        for migration_file in migration_files:
            sql_content = migration_file.read_text()
            up_sql = extract_up_migration(sql_content)

            with conn.cursor() as cur:
                cur.execute(up_sql)
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
