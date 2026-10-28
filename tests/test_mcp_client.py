"""End to end through the MCP SDK's own client: streamable HTTP into the
FastAPI app (in process), with a minted token, on both protocol eras."""

from decimal import Decimal

import anyio
import httpx2
import pytest
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client

from sensibility.accounts import create_account
from sensibility.config import get_settings
from sensibility.models import RecordType
from sensibility.repository import get_all_records
from tests.mcp_support import mint
from tests.support import WS
from tests.web_support import SECRET

pytestmark = pytest.mark.db


@pytest.fixture
def app(db_connection, db_url, mcp_env, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", SECRET)
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.delenv("ALLOWED_EMAILS", raising=False)
    get_settings.cache_clear()
    from sensibility.web.app import app

    yield app
    get_settings.cache_clear()


STATUSES: list[int] = []


async def _record(response) -> None:
    STATUSES.append(response.status_code)


async def session(app, mode: str, token: str, work):
    """Run `work(client)` against the app's lifespan, as Claude would connect.
    Each HTTP status lands in STATUSES."""
    STATUSES.clear()
    async with app.router.lifespan_context(app):
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="https://sensibility.money",
            headers={"Authorization": f"Bearer {token}"},
            event_hooks={"response": [_record]},
        ) as http:
            transport = streamable_http_client(
                "https://sensibility.money/mcp", http_client=http
            )
            async with Client(transport, mode=mode) as client:  # type: ignore[arg-type]
                return await work(client)


@pytest.mark.parametrize("mode", ["legacy", "2026-07-28"])
def test_list_and_call(app, db_connection, mode):
    create_account(db_connection, WS, "Cash", RecordType.ASSET)

    async def work(client):
        listed = await client.list_tools()
        saved = await client.call_tool(
            "update_balances", {"balances": {"cash": "12400"}}
        )
        balances = await client.call_tool("get_balances", {})
        refused = await client.call_tool("get_balances", {"workspace": "Elsewhere"})
        return listed, saved, balances, refused

    listed, saved, balances, refused = anyio.run(session, app, mode, mint(), work)

    tools = {t.name: t for t in listed.tools}
    assert len(tools) == 8
    schema = tools["get_balances"].output_schema
    assert schema is not None and "net_worth" in schema["properties"]
    assert tools["update_balances"].input_schema["required"] == ["balances"]

    assert not saved.is_error
    assert saved.structured_content["saved"] is True
    assert saved.structured_content["balances"]["net_worth"] == "12400.00"
    assert [r.amount for r in get_all_records(db_connection, WS)] == [Decimal("12400")]

    assert balances.structured_content["net_worth"] == "12400.00"
    assert balances.content[0].text.startswith("Test: net worth $12,400.00")

    assert refused.is_error
    assert "No workspace named 'Elsewhere'" in refused.content[0].text


@pytest.mark.parametrize("mode", ["legacy", "2026-07-28"])
def test_read_only_token_cannot_call_a_write_tool(app, db_connection, mode):
    """The gate finds the tool name in either era's request body."""
    create_account(db_connection, WS, "Cash", RecordType.ASSET)

    async def work(client):
        read = await client.call_tool("get_balances", {})
        try:
            await client.call_tool("update_balances", {"balances": {"Cash": "1"}})
        except Exception as e:  # the client raises on the 403
            return read, e
        return read, None

    read, refused = anyio.run(session, app, mode, mint(scope="sensibility:read"), work)
    assert not read.is_error
    assert refused is not None
    assert STATUSES[-1] == 403
    assert get_all_records(db_connection, WS) == []
