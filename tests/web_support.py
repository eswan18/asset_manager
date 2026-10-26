"""Helpers for web tests: sessions, fake identity, users, and route sweeps."""

import re

from itsdangerous import URLSafeTimedSerializer

from tests.support import SEED_USER, WS

SECRET = "test-secret-key"
USER = dict(SEED_USER)
STRANGER = {
    "id": 2,
    "sub": "user-2",
    "email": "stranger@example.com",
    "name": "Stranger",
}
TZ = "America/Chicago"  # the default zone (TIMEZONE): requests here send no tz cookie
ACCOUNTS = f"/api/workspaces/{WS}/accounts"
SNAPSHOTS = f"/api/workspaces/{WS}/snapshots"
# The seeded workspace's pages: the API path without /api.
PAGES = f"/workspaces/{WS}"


def claims(user: dict, **extra) -> dict:
    """What identity puts in the ID token for this user."""
    return {
        "sub": user["sub"],
        "email": user["email"],
        "name": user["name"],
        "email_verified": True,
        **extra,
    }


def session_for(client, user) -> None:
    client.cookies.set("session", URLSafeTimedSerializer(SECRET).dumps(user))


def login(client) -> None:
    session_for(client, USER)


def add_user(conn, user: dict, role: str | None = None, workspace_id: int = WS) -> None:
    """Insert a user row (ids are assigned in order) and optionally a membership."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (idp_sub, email, name) VALUES (%s, %s, %s) RETURNING id",
            (user["sub"], user["email"], user["name"]),
        )
        row = cur.fetchone()
        assert row is not None and row[0] == user["id"]
        if role is not None:
            cur.execute(
                "INSERT INTO workspace_members (workspace_id, user_id, role) VALUES (%s, %s, %s)",
                (workspace_id, user["id"], role),
            )
    conn.commit()


# Routes reachable without a session. Every other route must refuse. The
# docs routes are public too but are not in the schema, so not listed here.
PUBLIC_PATHS = {"/login", "/auth/start", "/auth/callback", "/logout", "/health"}


def protected_routes(fill: str = "1"):
    """(method, path) for every non-public route, with `fill` for each path id."""
    # The OpenAPI schema, not app.routes: since FastAPI 0.162, routes from
    # include_router sit behind a wrapper there and would be skipped.
    from asset_manager.web.app import app

    for path, operations in app.openapi()["paths"].items():
        if path not in PUBLIC_PATHS:
            for method in sorted(operations):
                yield method.upper(), re.sub(r"\{[a-z_]+\}", fill, path)


def sweep(client):
    """Hit every protected route as a JSON client; return {(method, path): status}."""
    return {
        (method, path): client.request(
            method,
            path,
            json={"values": {"1": "5"}},
            headers={"Accept": "application/json"},
            follow_redirects=False,
        ).status_code
        for method, path in protected_routes()
    }


class FakeIdp:
    """Stands in for authlib's registered client in the callback route."""

    def __init__(self, token=None, error=None, userinfo=None):
        self.token = token
        self.error = error
        self.userinfo_data = userinfo

    async def authorize_access_token(self, request):
        if self.error:
            raise self.error
        return self.token

    async def userinfo(self, token):
        return self.userinfo_data
