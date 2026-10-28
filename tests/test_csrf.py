"""The API's CSRF rule (web/csrf.py): a mutating /api/ request without
`X-Requested-With: sensibility` is refused before any route runs."""

import pytest

from sensibility.repository import get_memberships
from tests.support import USER_ID, WS
from tests.web_support import PAGES, login, protected_routes

pytestmark = pytest.mark.db

MESSAGE = "Missing the X-Requested-With: sensibility header"


@pytest.fixture
def bare(client):
    """The logged-in client without the header the fixture adds."""
    login(client)
    del client.headers["X-Requested-With"]
    return client


def test_a_write_without_the_header_is_refused_and_changes_nothing(bare, db_connection):
    response = bare.post("/api/workspaces", json={"name": "Sneaky"})

    assert response.status_code == 403
    assert response.json() == {"error": MESSAGE}
    assert [w.name for w, _ in get_memberships(db_connection, USER_ID)] == ["Test"]


def test_the_same_write_with_the_header_goes_through(bare):
    response = bare.post(
        "/api/workspaces",
        json={"name": "Ours"},
        headers={"X-Requested-With": "sensibility"},
    )
    assert response.status_code == 201, response.text


@pytest.mark.parametrize("value", ["XMLHttpRequest", "", "Sensibility"])
def test_another_value_is_refused(bare, value):
    response = bare.post(
        "/api/workspaces", json={"name": "Ours"}, headers={"X-Requested-With": value}
    )
    assert response.status_code == 403


def test_every_mutating_api_route_requires_it(bare):
    writes = [
        (method, path)
        for method, path in protected_routes()
        if path.startswith("/api/") and method != "GET"
    ]
    assert len(writes) >= 10
    for method, path in writes:
        response = bare.request(method, path, json={})
        assert response.status_code == 403, (method, path)
        assert response.json() == {"error": MESSAGE}


def test_reads_do_not_need_it(bare):
    assert bare.get("/api/me").status_code == 200
    assert bare.get(f"/api/workspaces/{WS}").status_code == 200


def test_it_is_checked_before_login(client):
    """Logged out, a write is still refused for the header, not the session:
    the rule needs nothing from the database."""
    del client.headers["X-Requested-With"]
    assert client.post("/api/workspaces", json={"name": "x"}).status_code == 403


def test_the_pages_own_form_posts_are_not_affected(bare):
    """The Jinja forms post outside /api/ and cannot send headers."""
    response = bare.post(
        f"{PAGES}/settings", data={"name": "Renamed"}, follow_redirects=False
    )
    assert response.status_code == 303


def test_mcp_is_exempt(bare, mcp_env):
    """/mcp takes bearer tokens, not cookies: its own 401, not this 403."""
    response = bare.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert response.status_code == 401
