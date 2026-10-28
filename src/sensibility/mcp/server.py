"""The MCP server: the SDK's MCPServer with the eight tools, served
statelessly at /mcp behind the gate.

Registration is thin on purpose: each tool here only names its arguments
(their descriptions become the input schema) and calls the plain function
in `tools` with a database connection and the gate's caller. The result's
model is the output schema; the text beside it is a one-line summary and
the same data as JSON, for clients that read only text.

Stateless streamable HTTP with JSON responses: nothing is held between
requests, so any pod can serve any call. The SDK answers both the
2026-07-28 protocol and the older initialize-handshake revisions.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field

from sensibility import __version__
from sensibility.db import get_connection_context

from . import tools
from .gate import current_caller, gate
from .results import (
    BalancesResult,
    CashFlowsResult,
    DeleteCashFlowResult,
    HistoryResult,
    SaveAccountResult,
    SaveCashFlowResult,
    ToolResult,
    UpdateBalancesResult,
    WorkspacesResult,
)
from .tools import Amount, FormulaInput, Interval, ToolFailure

INSTRUCTIONS = """\
Sensibility tracks one person's or household's money in workspaces: accounts \
(assets and liabilities) with dated balance snapshots, and recurring cash \
flows (income and expenses). Refer to workspaces, accounts, cash flows and \
categories by name. Money is a decimal string ("12400.00"). Before saving \
balances the user has not confirmed, call update_balances with preview: true \
and show what would change."""

server = MCPServer(
    name="sensibility",
    title="Sensibility",
    instructions=INSTRUCTIONS,
    version=__version__,
)

WorkspaceArg = Annotated[
    str | None,
    Field(
        description="Workspace name. Optional if you belong to exactly one; "
        "list_workspaces shows them."
    ),
]
TimezoneArg = Annotated[
    str | None,
    Field(
        description="IANA time zone (e.g. America/Los_Angeles) deciding which "
        "day today is. Defaults to the server's (America/Chicago)."
    ),
]


def _call(fn: Callable[..., ToolResult], **arguments: Any) -> CallToolResult:
    caller = current_caller()
    if caller is None:  # the gate always sets one; never served without it
        raise ToolError("Not signed in")
    try:
        with get_connection_context() as conn:
            result = fn(conn, caller, **arguments)
    except ToolFailure as e:
        raise ToolError(str(e)) from None
    return CallToolResult(
        content=[
            TextContent(type="text", text=result.summary()),
            TextContent(type="text", text=result.model_dump_json()),
        ],
        structured_content=result.model_dump(mode="json"),
    )


def _read(title: str) -> ToolAnnotations:
    return ToolAnnotations(title=title, read_only_hint=True, open_world_hint=False)


def _write(title: str, *, destructive: bool, idempotent: bool) -> ToolAnnotations:
    return ToolAnnotations(
        title=title,
        read_only_hint=False,
        destructive_hint=destructive,
        idempotent_hint=idempotent,
        open_world_hint=False,
    )


@server.tool(annotations=_read("List workspaces"))
def list_workspaces() -> Annotated[CallToolResult, WorkspacesResult]:
    """Your workspaces: each one's name, your role in it (owner, editor or
    viewer), its latest snapshot date and net worth."""
    return _call(tools.list_workspaces)


@server.tool(annotations=_read("Get balances"))
def get_balances(
    workspace: WorkspaceArg = None, timezone: TimezoneArg = None
) -> Annotated[CallToolResult, BalancesResult]:
    """The latest snapshot: net worth, its change over about 30 days (as the
    dashboard computes it), days since the last save, and every active
    account by category with its amount. Computed accounts show their
    formula."""
    return _call(tools.get_balances, workspace=workspace, timezone=timezone)


@server.tool(annotations=_read("Get history"))
def get_history(
    workspace: WorkspaceArg = None,
    start: Annotated[
        dt.date | None,
        Field(description="First date (YYYY-MM-DD); default one year before end"),
    ] = None,
    end: Annotated[
        dt.date | None,
        Field(description="Last date; default the latest snapshot"),
    ] = None,
    interval: Annotated[
        Interval,
        Field(
            description="One row per snapshot, or per month, quarter or year "
            "(the last snapshot in each)"
        ),
    ] = "month",
    accounts: Annotated[
        list[str] | None,
        Field(description="Account names to include an amount for in each row"),
    ] = None,
) -> Annotated[CallToolResult, HistoryResult]:
    """Net worth, assets and liabilities over time. Each row is a period's
    last snapshot (its period-end value); periods with no snapshot are left
    out. Ranges count from the latest snapshot, not today. A retired
    account's series ends at its last save."""
    return _call(
        tools.get_history,
        workspace=workspace,
        start=start,
        end=end,
        interval=interval,
        accounts=accounts,
    )


@server.tool(annotations=_read("Get cash flows"))
def get_cash_flows(
    workspace: WorkspaceArg = None,
    per: Annotated[
        Literal["day", "month", "year"],
        Field(description="Show amounts per day, month or year"),
    ] = "month",
) -> Annotated[CallToolResult, CashFlowsResult]:
    """Recurring income and expenses per day, month or year: total income,
    expenses by category with each flow, the amount left over (or short),
    and each category's share of income."""
    return _call(tools.get_cash_flows, workspace=workspace, per=per)


@server.tool(annotations=_write("Update balances", destructive=True, idempotent=True))
def update_balances(
    balances: Annotated[
        dict[str, Amount],
        Field(description='Account name to amount, e.g. {"Checking": "2450.10"}'),
    ],
    workspace: WorkspaceArg = None,
    cost_bases: Annotated[
        dict[str, Amount] | None,
        Field(description="Computed account name to its new cost basis"),
    ] = None,
    preview: Annotated[
        bool, Field(description="Compute the result and save nothing")
    ] = False,
    overwrite: Annotated[
        bool,
        Field(description="Replace a snapshot already saved today (ask first)"),
    ] = False,
    timezone: TimezoneArg = None,
) -> Annotated[CallToolResult, UpdateBalancesResult]:
    """Save today's snapshot. Plain accounts left out keep their latest
    amount; computed accounts recompute. The result gives the new net worth
    and change, and each account's source (updated, carried_forward or
    computed). A second save on the same day fails unless overwrite is true;
    the error says what the earlier save holds. Use preview to show the user
    the change before saving."""
    return _call(
        tools.update_balances,
        balances=balances,
        workspace=workspace,
        cost_bases=cost_bases,
        preview=preview,
        overwrite=overwrite,
        timezone=timezone,
    )


@server.tool(annotations=_write("Save cash flow", destructive=False, idempotent=True))
def save_cash_flow(
    name: Annotated[
        str, Field(description="The cash flow's name; matched to an existing one")
    ],
    workspace: WorkspaceArg = None,
    amount: Annotated[
        Amount | None, Field(description="Each occurrence, never negative")
    ] = None,
    direction: Literal["income", "expense"] | None = None,
    every: Annotated[
        int | None, Field(description="Every N units (1-1000); default 1")
    ] = None,
    unit: Literal["day", "week", "month", "year"] | None = None,
    category: Annotated[
        str | None,
        Field(
            description="Category name; created if new. Empty string for Uncategorized"
        ),
    ] = None,
    note: Annotated[str | None, Field(description="Empty string clears it")] = None,
    estimate: Annotated[
        bool | None, Field(description="Mark the amount as an estimate")
    ] = None,
    new_name: Annotated[str | None, Field(description="Rename it")] = None,
) -> Annotated[CallToolResult, SaveCashFlowResult]:
    """Create a cash flow, or change the one with this name (only the fields
    given change). A new one needs amount, direction and unit. An unknown
    category is created, and the result says so."""
    return _call(
        tools.save_cash_flow,
        name=name,
        workspace=workspace,
        amount=amount,
        direction=direction,
        every=every,
        unit=unit,
        category=category,
        note=note,
        estimate=estimate,
        new_name=new_name,
    )


@server.tool(annotations=_write("Delete cash flow", destructive=True, idempotent=False))
def delete_cash_flow(
    name: Annotated[str, Field(description="The cash flow's name")],
    workspace: WorkspaceArg = None,
) -> Annotated[CallToolResult, DeleteCashFlowResult]:
    """Delete a cash flow by name. There is no undo."""
    return _call(tools.delete_cash_flow, name=name, workspace=workspace)


@server.tool(annotations=_write("Save account", destructive=False, idempotent=False))
def save_account(
    name: Annotated[
        str,
        Field(
            description="The account's name. If an asset and a liability share "
            "it, say 'Name (asset)' or give type"
        ),
    ],
    workspace: WorkspaceArg = None,
    type: Annotated[
        Literal["asset", "liability"] | None,
        Field(description="Needed to create; an account's type never changes"),
    ] = None,
    new_name: Annotated[str | None, Field(description="Rename it")] = None,
    category: Annotated[
        str | None,
        Field(
            description="Bank Accounts, Investment Accounts, Credit Cards, Tax "
            "Liability, or Uncategorized"
        ),
    ] = None,
    formula: Annotated[
        FormulaInput | None,
        Field(description="Make it computed: rate_percent × (inputs − cost_basis)"),
    ] = None,
    make_plain: Annotated[
        bool, Field(description="Make a computed account plain again")
    ] = False,
    retired: Annotated[
        bool | None,
        Field(description="true retires it (as of today), false unretires it"),
    ] = None,
    timezone: TimezoneArg = None,
) -> Annotated[CallToolResult, SaveAccountResult]:
    """Create an account, or change the one with this name: rename it, set
    its category, make it computed from named input accounts or plain again,
    or retire or unretire it. A retire is refused while a computed account
    uses it as an input; retiring one whose last value is not zero succeeds
    with a warning to pass on."""
    return _call(
        tools.save_account,
        name=name,
        workspace=workspace,
        type=type,
        new_name=new_name,
        category=category,
        formula=formula,
        make_plain=make_plain,
        retired=retired,
        timezone=timezone,
    )


@asynccontextmanager
async def running() -> AsyncGenerator[None]:
    """Run the SDK's session manager for one app lifespan, handing its
    request handler to the gate. A manager runs only once, so each lifespan
    (each TestClient, in tests) builds a fresh one."""
    server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        # Bearer tokens guard /mcp; the SDK's DNS-rebinding check is for
        # servers on localhost and would refuse sensibility.money.
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        ),
    )
    manager = server.session_manager
    async with manager.run():
        gate.handler = manager.handle_request
        try:
            yield
        finally:
            gate.handler = None
