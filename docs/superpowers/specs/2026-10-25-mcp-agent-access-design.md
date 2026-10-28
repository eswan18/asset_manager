# Agent Access: MCP Server with OAuth via identity

**Date:** 2026-10-25 (tools settled 2026-10-27)
**Status:** Unblocked: the app is now **Sensibility**, at `sensibility.money`.
Researched and agreed in outline, tools settled (see *Tools*); not started.

## Goal

Let an agent (Claude on claude.ai, desktop, mobile, Claude Code) read and update
this app's data as a signed-in user: check balances, save a snapshot, edit cash
flows. The same pattern must work for the fleet's other apps (footstrike-api
next), all signing in through **identity**.

Options weighed: (a) per-user API keys, (b) an MCP server with OAuth, (c) some
login-as-you scheme. **Chosen: (b).** It is what Claude's connectors expect, it
scales to many apps on one identity provider, and nothing to copy or rotate by
hand.

## Name and host (settled)

The MCP URL is the OAuth **resource**: the audience in every token, stored in
every connector a user adds, and shown on identity's consent screen. Scope
names end up in tokens and saved grants. Renaming after people connect would
break every connection, so this waited for the rename, which finished in Oct
2026 (domain, repo, cluster, package; nothing kept the old name).

- MCP URL (the resource and the exact `aud`): **`https://sensibility.money/mcp`**;
  staging `https://staging.sensibility.money/mcp`.
- Scopes: **`sensibility:read`** and **`sensibility:write`**.
- identity's login clients are "Sensibility" and "Sensibility - Staging", with
  audiences `https://sensibility.money` and `https://staging.sensibility.money`.
  Nothing checks those today (the app reads `/oauth/userinfo`; identity
  validates with no expected audience), and MCP tokens take their audience
  from `resource` instead.

## Roles of each piece

- **identity** is the authorization server for every app. It knows who you are
  and which app a token is for. It knows nothing about workspaces or roles.
- **Each app** is a resource server and hosts its own MCP endpoint. It checks
  tokens itself and owns authorization: identity's `sub` maps to the app's
  user, and the app's workspace role decides what that user may do.
- Effective permission is the **lower** of the token's scope and the user's
  workspace role. A `read` token held by an owner can still only read.

## State of the art (researched 2026-10-25)

- **MCP spec 2026-07-28** is current. The protocol is stateless: no
  `initialize` handshake, no `Mcp-Session-Id`; any request can go to any
  instance. Claude is still rolling it out, and its connector docs still cite
  2025-11-25, so the server must answer both.
- **Python SDK `mcp` 2.3.0** (PyPI, Oct 2026). 2.x speaks 2026-07-28 and still
  serves older revisions from one server object. The class is `MCPServer`
  (formerly `FastMCP`). Auth: a `TokenVerifier` whose `verify_token` returns an
  `AccessToken` or `None`, plus `AuthSettings(issuer_url, resource_server_url,
  required_scopes, validate_token_resource=True)`. Tools read the caller with
  `get_access_token()`. The SDK serves protected resource metadata at
  `/.well-known/oauth-protected-resource/mcp`.
- **Client registration:** Client ID Metadata Documents (CIMD, an HTTPS URL as
  the `client_id`) are preferred. Dynamic Client Registration is deprecated,
  kept for backward compatibility.
- **Required of the auth server:** PKCE S256 *and* advertising
  `code_challenge_methods_supported` (clients refuse without it); RFC 8707
  `resource` parameter, with tokens audience-bound to it; RFC 9207 `iss` in
  authorization responses; rotating refresh tokens for public clients.
- **Required of the resource server:** RFC 9728 protected resource metadata;
  401 with `WWW-Authenticate: Bearer resource_metadata="..."` for a missing or
  bad token; 403 with `error="insufficient_scope"` and the needed scope for
  step-up; validate the audience; never accept or pass through a token issued
  for another service.

### What Claude specifically needs

From Claude's connector authentication docs:

- Claude uses CIMD only if identity's metadata has **both**
  `client_id_metadata_document_supported: true` and `"none"` in
  `token_endpoint_auth_methods_supported`; otherwise it falls back to DCR.
  Supporting CIMD alone is therefore enough.
- Claude uses only the **first** entry of `authorization_servers`.
- Sign-in starts only on a **401**; `WWW-Authenticate` on a 200 is ignored.
- Redirect URIs: `https://claude.ai/api/mcp/auth_callback` (web, desktop,
  mobile). Claude Code uses loopback `http://localhost/callback` and
  `http://127.0.0.1/callback` on **any port**; its CIMD is
  `https://claude.ai/oauth/claude-code-client-metadata`.
- Token endpoint: form-urlencoded bodies; `invalid_grant` for a dead refresh
  token; answer within 10s (30s for refresh).
- Claude appends `offline_access` if identity lists it in `scopes_supported`.
- Claude's servers call identity directly from `160.79.104.0/21`. A Cloudflare
  WAF rule in front of identity could break sign-in while the MCP endpoint
  itself works.

## Plan

### identity, phase 1 (backward compatible)

1. Discovery metadata: `code_challenge_methods_supported: ["S256"]`,
   `authorization_response_iss_parameter_supported: true`, `"none"` in
   `token_endpoint_auth_methods_supported`, `offline_access` in
   `scopes_supported`.
2. Accept `resource` on authorize and token requests, only for a registered
   list of resources; the token's `aud` is that resource. Today the audience
   comes from `oauth_clients.audience`, which cannot work when one client
   (Claude) talks to several apps.
3. Return `iss` on every authorization response (success and error).
4. Rotate refresh tokens on every use; `invalid_grant` for a used or revoked
   one.

### identity, phase 2

5. CIMD: when `client_id` is an HTTPS URL, fetch the document with SSRF
   protection (no private/loopback addresses, size and time limits), require
   its `client_id` to equal the URL, match `redirect_uri` exactly against its
   list (loopback: any port), and cache it.
6. Consent screen: client name, **redirect hostname**, the app (resource) being
   granted, and a warning when every redirect is localhost.
7. A "Connected apps" page to see and revoke grants.

### This app

8. Mount `MCPServer` at `/mcp` in the existing FastAPI app, so tools call the
   same service layer as the JSON API.
9. `TokenVerifier` checking identity's JWT as footstrike-api does
   (`footstrike/app/oauth.py`: PyJWKClient, `iss`, `exp`, `sub`) plus
   `aud == <exact MCP URL>` and scopes. Users are created on first MCP request
   through `record_login`, requiring `email_verified` and `ALLOWED_EMAILS`,
   exactly as browser login does.
10. Scopes: `sensibility:read` and `sensibility:write`, capped by workspace role.
11. The same verifier accepts bearer tokens on `/api/`, so scripts can use it.
12. The eight tools under *Tools*, all in the first version.
13. Test with Claude Code first (loopback redirects), then claude.ai.

### footstrike-api

14. Same pattern as this app.

## Tools

Eight, task-shaped (Anthropic's "Writing tools for agents"), each calling the
service layer the JSON API and pages use. Read tools need `sensibility:read`
and a viewer role; write tools `sensibility:write` and an editor role.

| Tool | Does |
|---|---|
| `list_workspaces` | Your workspaces: name, your role, latest snapshot date, net worth |
| `get_balances` | The latest snapshot: net worth, its change over ~30 days (as the dashboard computes it), days since the last save, and every active account by category with its amount; computed accounts show their formula |
| `get_history` | Net worth, assets and liabilities over time, optionally per named account (below) |
| `get_cash_flows` | Per `day`, `month` or `year` (default month): income, expenses by category with each flow, the amount left over, and each category's share of income |
| `update_balances` | Today's snapshot from `{account name: amount}` (below) |
| `save_cash_flow` | Create or update a cash flow, matched by name: amount, direction, every N unit, category, note, estimate. An unknown category is created, and the result says so |
| `delete_cash_flow` | Delete a cash flow by name. Annotated destructive |
| `save_account` | Create or update an account (name, type, category, or a computed formula over named input accounts), or retire or unretire it. The service's rules apply: a retire blocked by a computed account's inputs fails with that reason; a non-zero last value comes back as a warning |

Left out on purpose: members, invites, workspace settings and deletion,
category rename and reorder, the HTML report. Rare, administrative, and with
a large blast radius; the UI keeps them.

**`update_balances`.** `balances: {account name: amount}`, optional
`cost_bases: {account name: amount}`, `preview`, `overwrite`, `timezone`.
Omitted plain accounts carry forward from the latest snapshot and computed
ones recompute (`save_snapshot` with `carry_forward=True`). The result gives
the new net worth and change, and each account's source (`updated`,
`carried_forward`, `computed`).
- `preview: true` computes all of that and saves nothing, so the agent can
  show "net worth would go from $X to $Y" before you approve.
- **A second save on the same day fails** unless `overwrite: true`. The error
  says when today's earlier snapshot was saved and what it holds, so the
  agent can ask. `preview` works either way.
- A computed account named in `balances` fails with what to set instead (its
  inputs, or its cost basis).

**`get_history`.** `start` and `end` (dates; default one year before the
latest snapshot, to the latest), `interval` (`snapshot`, `month`, `quarter`,
`year`; default `month`), `accounts` (names, optional). One row per period,
from the **last snapshot in it** (the period-end value), carrying the period
(`2026-09`), the date of the snapshot used, net worth, assets, liabilities,
and an amount per named account. `snapshot` returns every snapshot. Ranges
count from the latest snapshot, not today, as the dashboard does; a period
with no snapshot is left out; a retired account's series ends at its last
save.

**Conventions for every tool.**
- Accounts, flows and categories are referred to **by name**, never by id,
  matched case-insensitively. An unknown or ambiguous name fails with the
  candidates ("No account 'Chase'. Did you mean 'Chase Sapphire Reserve'?").
- `workspace` (a name) is optional when you belong to exactly one; otherwise
  the error lists them.
- Writes return the outcome in the read tools' shape, so no follow-up read.
- Money is a decimal string with two places (`"12400.00"`). Results are
  structured (an output schema), with a short text summary beside them.
- "Today" is the day in the optional `timezone` (IANA), else `TIMEZONE`, as
  the API's `X-Timezone` works; there is no browser cookie here.
- Errors say what to do. Tool annotations: reads `readOnlyHint`;
  `delete_cash_flow` `destructiveHint`; nothing is held server-side between
  calls.

## Open questions

- Scope granularity: per-app `read`/`write` only, or finer?
- Whether identity's consent should be remembered per (client, resource).
- Rate limiting and audit logging of agent writes.

## Sources

- [The 2026-07-28 Specification (MCP blog)](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
- [Authorization, 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)
- [Client Registration, 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/client-registration)
- [Authorization Security Considerations, 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/security-considerations)
- [Authentication for connectors (Claude docs)](https://claude.com/docs/connectors/building/authentication)
- [Bringing MCP 2026-07-28 to Claude](https://claude.com/blog/bringing-mcp-2026-07-28-to-claude)
- [MCP Python SDK: authorization](https://py.sdk.modelcontextprotocol.io/run/authorization/)
- [Writing tools for agents (Anthropic)](https://www.anthropic.com/engineering/writing-tools-for-agents)
- [mcp on PyPI](https://pypi.org/project/mcp/)
