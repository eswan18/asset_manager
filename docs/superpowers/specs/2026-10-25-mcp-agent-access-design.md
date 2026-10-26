# Agent Access: MCP Server with OAuth via identity

**Date:** 2026-10-25
**Status:** Parked. Researched and agreed in outline; not started. Blocked on
renaming the app.

## Goal

Let an agent (Claude on claude.ai, desktop, mobile, Claude Code) read and update
this app's data as a signed-in user: check balances, save a snapshot, edit cash
flows. The same pattern must work for the fleet's other apps (footstrike-api
next), all signing in through **identity**.

Options weighed: (a) per-user API keys, (b) an MCP server with OAuth, (c) some
login-as-you scheme. **Chosen: (b).** It is what Claude's connectors expect, it
scales to many apps on one identity provider, and nothing to copy or rotate by
hand.

## Blocker: pick the name first

"Asset Manager" is likely to be renamed. The MCP URL (for example
`https://<host>/mcp`) is the OAuth **resource**: it is the audience in every
token, it is stored in every connector a user adds, and identity shows it on
the consent screen. Scope names (`<app>:read`) end up in tokens and saved
grants. Renaming after people connect breaks every connection, so the name
(and host) is settled before this work starts.

A rename is otherwise ordinary, and haruspex's Sept 2026 rename is the
template: repo, Python package and CLI, namespaces, SAs, secrets, image repo,
Cloud Build trigger, bifrost registry, identity client and redirect URIs,
hostnames (`assets.ethanswan.com`, `assets-staging.tailc06f30.ts.net`), the
`asset-events-{env}` topic, and the fleet CLAUDE.md. User-visible names (name,
domain, MCP URL, scopes) must change; internal ones may stay as deliberate
holdouts, as haruspex did. The database needs nothing.

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
10. Scopes: `<app>:read` and `<app>:write`, capped by workspace role.
11. The same verifier accepts bearer tokens on `/api/`, so scripts can use it.
12. Tools, few and task-shaped (Anthropic's "Writing tools for agents"):
    `list_workspaces`, `get_balances`, `update_balances` (partial snapshot with
    carry-forward), `list_cash_flows`, `upsert_cash_flow`. Prefixed names,
    names rather than bare ids in results, concise output, actionable errors,
    destructive tools annotated. Any multi-step state goes back to the agent
    as an explicit handle; nothing held server-side.
13. Test with Claude Code first (loopback redirects), then claude.ai.

### footstrike-api

14. Same pattern as this app.

## Open questions

- The new name and host.
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
