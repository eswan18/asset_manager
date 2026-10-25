from collections.abc import Generator
from contextlib import contextmanager

import psycopg
from psycopg import Connection

from asset_manager.config import get_settings


def get_connection() -> Connection:
    settings = get_settings()
    return psycopg.connect(settings.database_url)


@contextmanager
def get_connection_context() -> Generator[Connection]:
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()
