from collections.abc import Generator
from contextlib import contextmanager
from threading import Lock

import psycopg
from psycopg import Connection
from psycopg.pq import TransactionStatus
from psycopg_pool import ConnectionPool

from sensibility.config import get_settings

# Connections kept open between requests. A new connection to Neon is a TCP,
# TLS and auth round trip each time, and one request can take several (the
# session's access check, then the page's data). Keyed by URL, so tests that
# point the settings at their own database get their own pool.
_pools: dict[str, ConnectionPool] = {}
_pools_lock = Lock()


def get_connection() -> Connection:
    """A connection of your own, outside the pool: the caller closes it."""
    settings = get_settings()
    return psycopg.connect(settings.database_url)


def _pool(url: str) -> ConnectionPool:
    with _pools_lock:
        pool = _pools.get(url)
        if pool is None:
            pool = ConnectionPool(
                url,
                min_size=1,
                max_size=5,
                # Neon closes idle connections (and suspends the database), so
                # check each one as it is handed out and replace a dead one.
                check=ConnectionPool.check_connection,
                max_idle=300,
                # Neon's pooler (PgBouncer, transaction mode) can't keep the
                # server-side prepared statements a reused connection makes.
                kwargs={"prepare_threshold": None},
                name="sensibility",
                open=True,
            )
            _pools[url] = pool
        return pool


@contextmanager
def get_connection_context() -> Generator[Connection]:
    """A pooled connection for the block. As when connections were closed
    after use, anything the block didn't commit is rolled back, never
    committed, before the connection goes back."""
    pool = _pool(get_settings().database_url)
    conn = pool.getconn()
    try:
        yield conn
    finally:
        if conn.info.transaction_status in (
            TransactionStatus.INTRANS,
            TransactionStatus.INERROR,
        ):
            try:
                conn.rollback()
            except psycopg.Error:
                pass  # A broken connection: putconn discards it.
        pool.putconn(conn)


def close_pools() -> None:
    """Close every pool (at shutdown)."""
    with _pools_lock:
        for pool in _pools.values():
            pool.close()
        _pools.clear()
