import os
import subprocess
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
    # testcontainers returns: postgresql+psycopg2://user:pass@host:port/db
    # Convert to standard format: postgresql://user:pass@host:port/db
    url = postgres_container.get_connection_url()
    url = url.replace("postgresql+psycopg2://", "postgresql://")
    # Disable SSL for test container (not configured for SSL)
    return f"{url}?sslmode=disable"


@pytest.fixture(scope="session")
def _run_migrations(db_url):
    """Run dbmate migrations against the test database."""
    project_root = Path(__file__).parent.parent

    # Run dbmate up with the test database URL
    result = subprocess.run(
        ["dbmate", "up"],
        cwd=project_root,
        env={**os.environ, "DATABASE_URL": db_url},
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        pytest.fail(f"dbmate up failed:\n{result.stderr}\n{result.stdout}")


@pytest.fixture
def db_connection(db_url, _run_migrations):
    """Get a database connection for testing."""
    conn = psycopg.connect(db_url)

    yield conn

    # Clean up: truncate tables after each test
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE snapshots RESTART IDENTITY")
    conn.commit()
    conn.close()


@pytest.fixture(autouse=True)
def skip_db_tests_in_ci(request):
    """Skip database tests in CI if Docker is not available."""
    if request.node.get_closest_marker("db"):
        if os.getenv("CI") == "true" and os.getenv("SKIP_DB_TESTS") == "true":
            pytest.skip("Skipping DB tests in CI (Docker not available)")
