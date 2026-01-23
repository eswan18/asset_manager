#!/usr/bin/env python3
"""
Apply database migrations using psycopg3.

Usage:
    ENV=dev uv run python scripts/apply_migrations.py

This is a simple migration runner that reads SQL files from the migrations/
directory and applies them in order.
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from asset_manager.db import get_connection_context


MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


def get_applied_migrations(conn) -> set[str]:
    """Get the set of already applied migration names."""
    with conn.cursor() as cur:
        # Create migrations tracking table if it doesn't exist
        cur.execute("""
            CREATE TABLE IF NOT EXISTS _yoyo_migration (
                id VARCHAR(255) PRIMARY KEY,
                applied_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

        cur.execute("SELECT id FROM _yoyo_migration")
        return {row[0] for row in cur.fetchall()}


def apply_migration(conn, migration_file: Path) -> bool:
    """Apply a single migration file. Returns True if applied, False if skipped."""
    migration_id = migration_file.stem

    with conn.cursor() as cur:
        # Read and execute the migration SQL
        sql = migration_file.read_text()

        # Remove yoyo-specific comments
        lines = sql.split("\n")
        sql_lines = [line for line in lines if not line.strip().startswith("-- depends:")]
        sql = "\n".join(sql_lines)

        try:
            cur.execute(sql)
            # Record the migration as applied
            cur.execute(
                "INSERT INTO _yoyo_migration (id) VALUES (%s)",
                (migration_id,)
            )
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            raise


def main():
    print("Applying database migrations...")

    # Find all migration SQL files (excluding rollback files)
    migration_files = sorted([
        f for f in MIGRATIONS_DIR.glob("*.sql")
        if not f.name.endswith(".rollback.sql")
    ])

    if not migration_files:
        print("No migration files found.")
        return

    with get_connection_context() as conn:
        applied = get_applied_migrations(conn)
        print(f"Already applied: {len(applied)} migrations")

        for migration_file in migration_files:
            migration_id = migration_file.stem

            if migration_id in applied:
                print(f"  [SKIP] {migration_file.name} (already applied)")
                continue

            print(f"  [APPLY] {migration_file.name}...", end=" ")
            try:
                apply_migration(conn, migration_file)
                print("OK")
            except Exception as e:
                print(f"FAILED: {e}")
                return

    print("Done!")


if __name__ == "__main__":
    main()
