"""/mcp over HTTP: the gate's 401s and 403s, users on first use, the
protected resource metadata, and tool calls reaching the tools."""

import json
from decimal import Decimal

import pytest

from sensibility.accounts import create_account, save_snapshot
from sensibility.models import RecordType
from sensibility.repository import get_all_records
from tests.mcp_support import BOTH, ISSUER, PRM_URL, RESOURCE, mint
from tests.support import SEED_USER, WS
from tests.web_support import login

pytestmark = pytest.mark.db

MCP = "/mcp"
PRM = "/.well-known/oauth-protected-resource/mcp"
SCOPES = "sensibility:read sensibility:write"
CHALLENGE = f'Bearer resource_metadata="{PRM_URL}", scope="{SCOPES}"'
INVALID = (
    f'Bearer error="invalid_token", resource_metadata="{PRM_URL}", scope="{SCOPES}"'
)
STEP_UP = (
    f'Bearer error="insufficient_scope", scope="{SCOPES}", '
    f'resource_metadata="{PRM_URL}"'
)
NEW_USER = {"id": 2, "sub": "new-sub", "email": "New@Example.com", "name": "New"}


def rpc(client, method: str, params: dict | None = None, token: str | None = None):
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2025-11-25",
    }
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return client.post(MCP, content=json.dumps(body), headers=headers)


def call(client, tool: str, arguments: dict | None = None, token: str | None = None):
    return rpc(
        client, "tools/call", {"name": tool, "arguments": arguments or {}}, token
    )


@pytest.fixture
def mcp(client, mcp_env):
    return client


def user_rows(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT idp_sub, email, name FROM users ORDER BY id")
        return cur.fetchall()


class TestUnauthenticated:
    def test_no_token_is_a_401_pointing_at_the_metadata(self, mcp):
        response = rpc(mcp, "tools/list")
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == CHALLENGE

    @pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
    def test_every_method_needs_a_token(self, mcp, method):
        response = mcp.request(method, MCP)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == CHALLENGE

    def test_a_session_cookie_is_not_a_token(self, mcp):
        login(mcp)
        assert rpc(mcp, "tools/list").status_code == 401

    def test_other_schemes_are_not_a_token(self, mcp):
        response = mcp.post(MCP, headers={"Authorization": "Basic dXNlcjpwYXNz"})
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == CHALLENGE

    @pytest.mark.parametrize(
        "token",
        [
            "garbage",
            mint(iss="https://evil.example.com"),
            mint(aud=["https://another.example.com/mcp"]),
            mint(headers={"typ": None}),
            mint(exp=1),
        ],
        ids=["garbage", "issuer", "audience", "no-typ", "expired"],
    )
    def test_a_bad_token_is_a_401_invalid_token(self, mcp, token):
        response = rpc(mcp, "tools/list", token=token)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == INVALID


class TestScopes:
    def test_read_token_reads(self, mcp):
        response = call(mcp, "get_balances", token=mint(scope="sensibility:read"))
        assert response.status_code == 200
        assert response.json()["result"]["isError"] is False

    def test_read_token_calling_a_write_tool_is_a_403_step_up(self, mcp, db_connection):
        cash = create_account(db_connection, WS, "Cash", RecordType.ASSET)
        response = call(
            mcp,
            "update_balances",
            {"balances": {"Cash": "5"}},
            token=mint(scope="sensibility:read"),
        )
        assert response.status_code == 403
        assert response.headers["www-authenticate"] == STEP_UP
        assert response.json()["error"] == "insufficient_scope"
        assert get_all_records(db_connection, WS) == []
        assert cash.id is not None

    def test_unknown_tools_need_write(self, mcp):
        response = call(mcp, "no_such_tool", token=mint(scope="sensibility:read"))
        assert response.status_code == 403

    def test_write_implies_read(self, mcp):
        response = call(mcp, "list_workspaces", token=mint(scope="sensibility:write"))
        assert response.status_code == 200

    @pytest.mark.parametrize("scope", ["", "openid profile email"])
    def test_a_token_with_neither_scope_is_a_403(self, mcp, scope):
        response = rpc(mcp, "tools/list", token=mint(scope=scope))
        assert response.status_code == 403
        assert response.headers["www-authenticate"] == STEP_UP

    def test_write_token_writes(self, mcp, db_connection):
        create_account(db_connection, WS, "Cash", RecordType.ASSET)
        response = call(mcp, "update_balances", {"balances": {"cash": 5}}, token=mint())
        assert response.status_code == 200
        assert response.json()["result"]["isError"] is False
        assert [r.amount for r in get_all_records(db_connection, WS)] == [Decimal("5")]


class TestUsers:
    def test_a_known_sub_is_that_user(self, mcp, db_connection):
        response = call(mcp, "list_workspaces", token=mint())
        result = response.json()["result"]
        assert result["structuredContent"]["workspaces"][0]["name"] == "Test"
        assert len(user_rows(db_connection)) == 1

    def test_an_unknown_sub_is_created_through_record_login(self, mcp, db_connection):
        response = call(mcp, "list_workspaces", token=mint(NEW_USER))
        assert response.status_code == 200
        assert response.json()["result"]["structuredContent"] == {"workspaces": []}
        assert user_rows(db_connection)[1] == ("new-sub", "new@example.com", None)

    def test_a_pre_provisioned_user_is_claimed(self, mcp, db_connection):
        with db_connection.cursor() as cur:
            cur.execute(
                "INSERT INTO users (email, name) VALUES ('new@example.com', 'Pre')"
            )
        db_connection.commit()
        call(mcp, "list_workspaces", token=mint(NEW_USER))
        assert user_rows(db_connection)[1] == ("new-sub", "new@example.com", "Pre")

    def test_an_email_outside_allowed_emails_is_refused(
        self, mcp, db_connection, monkeypatch
    ):
        monkeypatch.setenv("ALLOWED_EMAILS", "me@example.com")
        response = call(mcp, "list_workspaces", token=mint(NEW_USER))
        assert response.status_code == 403
        assert "New@Example.com is not allowed" in response.json()["error_description"]
        assert len(user_rows(db_connection)) == 1

    def test_allowed_emails_fails_closed(self, mcp, db_connection, monkeypatch):
        monkeypatch.setenv("ENV", "prod")
        assert call(mcp, "list_workspaces", token=mint(NEW_USER)).status_code == 403
        assert call(mcp, "list_workspaces", token=mint()).status_code == 403
        assert len(user_rows(db_connection)) == 1

    def test_an_unverified_email_is_refused(self, mcp, db_connection):
        response = call(
            mcp, "list_workspaces", token=mint(NEW_USER, email_verified=False)
        )
        assert response.status_code == 403
        assert "not verified" in response.json()["error_description"]
        assert len(user_rows(db_connection)) == 1

    def test_no_email_is_refused(self, mcp, db_connection):
        response = call(mcp, "list_workspaces", token=mint(NEW_USER, email=None))
        assert response.status_code == 403
        assert len(user_rows(db_connection)) == 1

    def test_allowed_emails_is_rechecked_on_every_request(self, mcp, monkeypatch):
        assert call(mcp, "list_workspaces", token=mint()).status_code == 200
        monkeypatch.setenv("ALLOWED_EMAILS", "someone-else@example.com")
        response = call(mcp, "list_workspaces", token=mint())
        assert response.status_code == 403
        assert SEED_USER["email"] in response.json()["error_description"]


class TestMetadata:
    def test_protected_resource_metadata(self, mcp):
        response = mcp.get(PRM)
        assert response.status_code == 200
        assert response.json() == {
            "resource": RESOURCE,
            "authorization_servers": [ISSUER],
            "scopes_supported": SCOPES.split(),
            "bearer_methods_supported": ["header"],
        }

    def test_unconfigured_fails_closed(self, client):
        assert client.get(PRM).status_code == 503
        assert rpc(client, "tools/list", token=mint()).status_code == 503

    def test_mcp_is_not_in_the_schema(self, mcp):
        paths = mcp.get("/openapi.json").json()["paths"]
        assert MCP not in paths
        assert PRM in paths


class TestTools:
    def test_tools_list_names_the_eight_tools(self, mcp):
        response = rpc(mcp, "tools/list", token=mint(scope="sensibility:read"))
        tools = {t["name"]: t for t in response.json()["result"]["tools"]}
        assert set(tools) == {
            "list_workspaces",
            "get_balances",
            "get_history",
            "get_cash_flows",
            "update_balances",
            "save_cash_flow",
            "delete_cash_flow",
            "save_account",
        }
        assert all("outputSchema" in t for t in tools.values())
        for name in (
            "list_workspaces",
            "get_balances",
            "get_history",
            "get_cash_flows",
        ):
            assert tools[name]["annotations"]["readOnlyHint"] is True
        assert tools["delete_cash_flow"]["annotations"]["destructiveHint"] is True
        assert tools["update_balances"]["annotations"]["readOnlyHint"] is False

    def test_a_call_returns_structured_content_and_a_summary(self, mcp, db_connection):
        create_account(db_connection, WS, "Cash", RecordType.ASSET)
        from datetime import date

        save_snapshot(db_connection, WS, {1: Decimal("120.5")}, {}, date(2026, 10, 1))
        result = call(mcp, "get_balances", token=mint(scope=BOTH)).json()["result"]
        assert result["structuredContent"]["net_worth"] == "120.50"
        summary, data = result["content"]
        assert summary["text"].startswith("Test: net worth $120.50 on 2026-10-01")
        assert json.loads(data["text"]) == result["structuredContent"]

    def test_a_tool_failure_is_a_tool_error(self, mcp):
        result = call(mcp, "get_balances", {"workspace": "Nope"}, token=mint()).json()[
            "result"
        ]
        assert result["isError"] is True
        assert "No workspace named 'Nope'" in result["content"][0]["text"]
