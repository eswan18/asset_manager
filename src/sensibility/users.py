"""Users as identity knows them. Functions commit on success."""

from __future__ import annotations

from psycopg import Connection

from . import repository as repo
from .models import User


def record_login(conn: Connection, idp_sub: str, email: str, name: str | None) -> User:
    """The user for this identity login, created or claimed if need be.

    The caller must already have checked that `email` is verified, because
    a pre-provisioned row with no sub yet is claimed by email alone.
    """
    email = email.strip().lower()
    user = (
        repo.update_login_by_sub(conn, idp_sub, email, name)
        or repo.claim_unclaimed_user(conn, idp_sub, email, name)
        or repo.insert_user(conn, idp_sub, email, name)
    )
    conn.commit()
    return user
