"""The gate in front of the MCP SDK: every /mcp request passes through here.

Claude starts sign-in only on a real HTTP 401 (a tool error inside a 200
never prompts it), and asks for more scope only on a 403 with
`error="insufficient_scope"`, so authentication and scope are decided here,
as HTTP, before the SDK sees the request:

- no bearer token: 401, with `WWW-Authenticate` pointing at the protected
  resource metadata;
- a token that fails `tokens.verify`: 401 with `error="invalid_token"`;
- a token whose `sub` maps to no user we may serve: 403 with the reason
  (users are created on first use through `record_login`, exactly as the
  browser login does: verified email, in ALLOWED_EMAILS, fail closed);
- a token with neither scope, or a `tools/call` of a tool outside
  `READ_TOOLS` without `sensibility:write`: 403 `insufficient_scope`
  (step-up). Per-tool scope is enforced by reading the JSON-RPC body here,
  since the SDK has no per-tool scope hook; each write tool checks again.

A request that passes runs with its `Caller` in a context variable, which
the SDK carries into the tool call.
"""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from typing import Any

import anyio.to_thread
from starlette.types import Message, Receive, Scope, Send

from sensibility import repository as repo
from sensibility.db import get_connection_context
from sensibility.users import record_login
from sensibility.web.auth import is_email_allowed

from . import tokens
from .tokens import SCOPES, WRITE_SCOPE, InvalidToken, McpConfig, mcp_config
from .tools import READ_TOOLS, Caller

logger = logging.getLogger(__name__)

# The SDK's own limit on a request body; the gate reads the body first.
MAX_BODY = 4 * 1024 * 1024
SCOPE_TEXT = " ".join(SCOPES)

_caller: ContextVar[Caller | None] = ContextVar("mcp_caller", default=None)


def current_caller() -> Caller | None:
    """The caller of the request being served, set by the gate."""
    return _caller.get()


class Refused(Exception):
    """The token is good but its user may not use Sensibility (403)."""


def protected_resource_metadata(config: McpConfig) -> dict[str, Any]:
    """RFC 9728 metadata for /mcp. Claude uses the first (only) server."""
    return {
        "resource": config.resource,
        "authorization_servers": [config.issuer],
        "scopes_supported": list(SCOPES),
        "bearer_methods_supported": ["header"],
    }


def challenge(config: McpConfig, error: str | None = None) -> str:
    """A `WWW-Authenticate` value for a 401 (no error, or invalid_token)."""
    params = [] if error is None else [f'error="{error}"']
    params += [
        f'resource_metadata="{config.metadata_url}"',
        f'scope="{SCOPE_TEXT}"',
    ]
    return "Bearer " + ", ".join(params)


def step_up(config: McpConfig) -> str:
    """A `WWW-Authenticate` value for a 403 asking for more scope."""
    return (
        f'Bearer error="insufficient_scope", scope="{SCOPE_TEXT}", '
        f'resource_metadata="{config.metadata_url}"'
    )


def resolve_caller(claims: dict[str, Any]) -> Caller:
    """The Sensibility user for verified claims, created on first use.

    Raises Refused when that user may not use the app.
    """
    sub = claims["sub"]
    with get_connection_context() as conn:
        user = repo.get_user_by_sub(conn, sub)
        if user is None:
            email = claims.get("email")
            if not isinstance(email, str) or not email:
                raise Refused("identity sent no email for this account")
            if not is_email_allowed(email):
                raise Refused(f"{email} is not allowed to use Sensibility")
            # identity lets unverified accounts log in; see handle_callback.
            if claims.get("email_verified") is not True:
                raise Refused(
                    f"{email} is not verified at identity. Verify it there, "
                    "then connect again"
                )
            name = claims.get("name")
            user = record_login(
                conn, sub, email, name if isinstance(name, str) else None
            )
        elif not is_email_allowed(user.email):
            raise Refused(f"{user.email} is not allowed to use Sensibility")
    return Caller(
        user=user,
        scopes=tokens.scopes_of(claims),
        client_id=str(claims["client_id"]),
    )


def tools_called(body: bytes) -> list[str]:
    """The tool names in a JSON-RPC body's `tools/call` messages."""
    try:
        payload = json.loads(body)
    except ValueError:
        return []
    messages = payload if isinstance(payload, list) else [payload]
    names = []
    for message in messages:
        if isinstance(message, dict) and message.get("method") == "tools/call":
            params = message.get("params")
            name = params.get("name") if isinstance(params, dict) else None
            names.append(name if isinstance(name, str) else "")
    return names


def needs_write(body: bytes) -> bool:
    """Deny by default: any tool not known to only read needs write."""
    return any(name not in READ_TOOLS for name in tools_called(body))


async def _respond(
    send: Send, status: int, body: dict[str, Any], challenge: str | None = None
) -> None:
    data = json.dumps(body).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(data)).encode()),
    ]
    if challenge is not None:
        headers.append((b"www-authenticate", challenge.encode()))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": data})


async def _read_body(receive: Receive) -> bytes | None:
    """The whole request body, or None if it is over MAX_BODY."""
    chunks, size = [], 0
    while True:
        message = await receive()
        if message["type"] != "http.request":
            break
        chunk = message.get("body", b"")
        size += len(chunk)
        if size > MAX_BODY:
            return None
        chunks.append(chunk)
        if not message.get("more_body", False):
            break
    return b"".join(chunks)


def _bearer(scope: Scope) -> str | None:
    for key, value in scope["headers"]:
        if key == b"authorization":
            text = value.decode("latin-1")
            kind, _, token = text.partition(" ")
            if kind.lower() == "bearer" and token.strip():
                return token.strip()
            return None
    return None


class McpGate:
    """ASGI app at /mcp: authenticate, authorize, then hand to the SDK's
    session manager (set while the app's lifespan runs)."""

    def __init__(self) -> None:
        self.handler: Any = None  # the SDK's handle_request, during lifespan

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        config = mcp_config()
        if config is None or self.handler is None:
            await _respond(send, 503, {"error": "MCP is not configured here"})
            return
        token = _bearer(scope)
        if token is None:
            await _respond(
                send,
                401,
                {"error": "invalid_token", "error_description": "Sign in required"},
                challenge(config),
            )
            return
        try:
            claims = await anyio.to_thread.run_sync(
                tokens.verify, token, config, tokens.key_source(config)
            )
        except InvalidToken as e:
            logger.info("MCP token refused: %s", e)
            await _respond(
                send,
                401,
                {"error": "invalid_token", "error_description": "Token not accepted"},
                challenge(config, "invalid_token"),
            )
            return
        try:
            caller = await anyio.to_thread.run_sync(resolve_caller, claims)
        except Refused as e:
            logger.warning("MCP caller refused: %s", e)
            await _respond(
                send, 403, {"error": "access_denied", "error_description": str(e)}
            )
            return

        body = await _read_body(receive)
        if body is None:
            await _respond(send, 413, {"error": "Request body too large"})
            return
        if not caller.can_read or (
            needs_write(body) and WRITE_SCOPE not in caller.scopes
        ):
            await _respond(
                send,
                403,
                {
                    "error": "insufficient_scope",
                    "error_description": f"This needs {WRITE_SCOPE}"
                    if caller.can_read
                    else f"This needs {' or '.join(SCOPES)}",
                },
                step_up(config),
            )
            return

        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        reset = _caller.set(caller)
        try:
            await self.handler(scope, replay, send)
        finally:
            _caller.reset(reset)


gate = McpGate()
