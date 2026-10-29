# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Sensibility Money (usually just "Sensibility"; formerly Asset Manager) is a Python application for tracking financial assets and liabilities. Values are entered on the web dashboard's Accounts tab (or the JSON API) and saved as dated snapshots in PostgreSQL. Liabilities can be computed from other accounts by a formula. Data belongs to **workspaces**; users are members of workspaces with a role. Multi-user is the plan (open sign-up eventually); today `ALLOWED_EMAILS` gates who can log in.

The app is named "Sensibility" on its pages (the React app's shell and titles; `rendering.APP_NAME` for the login page). The deployment is named `sensibility` too (namespaces `sensibility-{prod,staging}`, image `containers/sensibility`, trigger `sensibility-build`, secrets `sensibility_{env}_*`; moved from asset-manager in Oct 2026), and so are the Python package (`sensibility`, formerly `asset_manager`) and the CLI (`sensibility`, formerly `asset-manager`).

Prod is served at `https://sensibility.money` (it replaced `assets.ethanswan.com`, deleted in Oct 2026) through the Cloudflare tunnel; staging at `https://staging.sensibility.money`, tailnet-only, through the shared ingress-nginx (`k8s/staging/nginx-ingress.yaml`; it replaced `assets-staging.tailc06f30.ts.net`, a Tailscale ingress, in Oct 2026). The GitHub repo is `eswan18/sensibility`.

## Development Setup

This project uses uv for dependency management. To set up the development environment:

```bash
uv sync
```

### Prerequisites

- **dbmate**: Database migration tool. Install with `brew install dbmate`

### Environment Configuration

The project uses `.env` files for configuration. Copy the example and configure for your environment:

```bash
cp .env.example .env.dev   # For development/staging
cp .env.example .env.prod  # For production
```

Edit the `.env.dev` and `.env.prod` files with your database credentials:

```
DATABASE_URL=postgresql://user:password@host:5432/dbname
```

### Database Setup

Apply migrations to create the database schema:
```bash
uv run dotenv -f .env.dev run dbmate up
# Or for production:
uv run dotenv -f .env.prod run dbmate up
```

## Common Commands

### Database Migrations (dbmate)
```bash
# Apply pending migrations
uv run dotenv -f .env.dev run dbmate up

# Rollback last migration
uv run dotenv -f .env.dev run dbmate down

# Create a new migration
dbmate new <migration_name>

# Check migration status
uv run dotenv -f .env.dev run dbmate status
```

### CLI Commands
```bash
# Generate interactive HTML report
ENV=dev uv run sensibility report --workspace 1
ENV=dev uv run sensibility report --workspace 1 --output report.html --no-open

# Run web dashboard locally
ENV=dev uv run sensibility serve
ENV=dev uv run sensibility serve --port 8080

# Show version
uv run sensibility version

# Or use python -m invocation
ENV=dev uv run python -m sensibility report --workspace 1
```

### Development Commands
- **Run tests**: `uv run pytest` (browser tests excluded; `uv run pytest -m browser` runs them, after a one-time `uv run playwright install chromium`)
- **Run tests with coverage**: `uv run pytest --cov=sensibility`
- **Type checking**: `uv run ty check src/sensibility`
- **Linting**: `uv run ruff check src tests`
- **Code formatting**: `uv run ruff format src tests`
- **Frontend** (`frontend/`, Node 24): `npm ci`, `npm run lint` (eslint + prettier), `npm run typecheck`, `npm test` (Vitest), `npm run build` (to `frontend/dist`, served from `/`), `npm run dev` (Vite on :5173 proxying the server-side paths to :8000). See *Frontend (React)* below and `frontend/README.md`

## Architecture

### Project Structure

```
sensibility/
├── src/
│   └── sensibility/
│       ├── __init__.py         # Package version
│       ├── __main__.py         # python -m support
│       ├── cli.py              # Typer CLI application
│       ├── config.py           # pydantic-settings configuration
│       ├── db.py               # Database connections
│       ├── models.py           # Pydantic models
│       ├── repository.py       # Database operations
│       ├── accounts.py         # Account rules, retire checks, snapshot save transaction
│       ├── workspaces.py       # Workspace and membership rules (names, last owner)
│       ├── users.py            # record_login: match/claim/create users at login
│       ├── invites.py          # Workspace invites: create, revoke, accept, decline
│       ├── cashflows.py        # Cash flows: per-day/month/year math (pure) and rules
│       ├── clock.py            # today(tz), zone validation, the TIMEZONE fallback
│       ├── formulas.py         # Pure formula evaluation (compute_snapshot)
│       ├── report.py           # Interactive HTML report generation
│       ├── py.typed            # PEP 561 marker
│       ├── mcp/                # Agent access: the MCP endpoint at /mcp
│       │   ├── tokens.py       # Config; verifying identity's access tokens (JWKS)
│       │   ├── gate.py         # ASGI gate: 401/403, the caller, scopes; PRM document
│       │   ├── tools.py        # The eight tools as plain functions
│       │   ├── results.py      # Their structured results and summaries
│       │   └── server.py       # MCPServer, thin tool registration, lifespan
│       └── web/                # The web server: JSON API, login, serving the React app
│           ├── __init__.py
│           ├── app.py          # FastAPI application: routers, login/auth routes, /health, /mcp
│           ├── spa.py          # Serves the React app's build from the root; /app/… redirects
│           ├── csrf.py         # Mutating /api/ requests need X-Requested-With: sensibility
│           ├── auth.py         # OAuth/OIDC authentication
│           ├── access.py       # Which workspace a request acts in; role checks
│           ├── viewer_zone.py  # Today: the viewer's date (X-Timezone, else TIMEZONE)
│           ├── api_routes.py   # JSON API: /api/me, /api/workspaces/..., snapshots, cash flows
│           ├── api_dashboard.py  # GET .../dashboard: the dashboard page as data
│           ├── api_accounts.py # .../accounts/overview, the drawer, account writes
│           ├── api_models.py   # Shared by those two: Money, ErrorOut, category keys
│           ├── api_cash_flows.py  # JSON API: the Cash flows overview, category move
│           ├── api_settings.py # JSON API: settings model, your invites
│           ├── accounts_model.py  # Accounts page facts: sections, groups, inputs, retire state
│           ├── cash_flows_model.py  # Cash flows figures, unformatted
│           ├── settings_model.py   # Settings facts: can_leave, removable, lapsed
│           ├── dashboard.py    # Dashboard numbers: 30-day change, ranges, categories
│           ├── rendering.py    # render() for login.html; APP_NAME
│           └── templates/
│               ├── base.html   # The design tokens and login's few shared styles; no shell
│               └── login.html  # The one server-rendered page (board X)
├── frontend/                   # The React app (Vite; see "Frontend (React)")
├── tests/
├── db/
│   └── migrations/
├── pyproject.toml              # Includes Vercel app entrypoint
└── README.md
```

### Core Modules

- **`config.py`**: Environment configuration using pydantic-settings, loads from `.env.{ENV}` files
- **`models.py`**: `Account` (with `category`, `formula` JSON document and `input_ids`), `AccountCategory`, `ProportionalFormula`, `Record`, `DailySummary`, `User`, `Workspace`, `Member`, `Role`
- **`formulas.py`**: `compute_snapshot(accounts, values, as_of)`: pure evaluation, raises `MissingValueError`
- **`accounts.py`**: Service layer; every function takes the `workspace_id` it acts in. `create_account`/`update_account` enforce input rules; `retire_account` refuses only inputs of active computed accounts; `save_snapshot` is all-or-nothing; `preview_snapshot` runs the same checks and evaluation in a rolled-back transaction and returns the amounts it would write. `parse_formula(rate_percent, cost_basis)` is the form's formula parsing, shared with the MCP tools. Raises `AccountError` with user-facing messages. Commits.
- **`repository.py`**: Thin SQL. Never commits. Every account/snapshot function takes `workspace_id` and filters on it, so another workspace's ids behave as nonexistent.
- **`workspaces.py`**: `create_workspace` (creator becomes owner), `update_workspace` (name), `delete_workspace` (soft), `change_role`/`remove_member` (refuse to drop the last owner; lock the member rows `FOR UPDATE`). `is_last_owner(member, members)` is that rule as a predicate, for pages deciding whether to offer Leave. Raises `WorkspaceError`.
- **`invites.py`**: Owners invite an email with a role; expires after `INVITE_TTL` (14 days). Only the invited (verified) email can accept or decline; anything else is `InviteNotFound` (404), so ids reveal nothing. An invite lapses once its sender is no longer an owner (`sender_is_owner`); `acceptable_invites(email)` leaves lapsed ones out in one query (`repo.get_acceptable_invites_for_email`, with the sender's name), for `GET /api/settings`'s neighbours (`GET /api/invites` lists every pending one, with `acceptable`). Invites never bypass `ALLOWED_EMAILS`. **No email is sent** yet; the invitee is told out of band and finds it in the shell's invite strip on every page, on `/welcome`, or via `GET /api/invites`.
- **`cashflows.py`**: Recurring income/expenses. `per_year(flow)` is signed (expenses negative) and divides once, at the end, so equivalent frequencies (2 weeks / 14 days, 12 months / 1 year) agree exactly; `rates()` rounds to cents; `totals()` sums unrounded and rounds once. `category_totals(flows, categories)` groups expenses by category (every category in `position` order, empty ones too, then Uncategorized if any; an unknown `category_id` counts as Uncategorized) and sums each unrounded, so they add up to `totals()`'s expenses exactly. Page helpers: `Period` (day/month/year) with `parse_period` (unknown values fall back to month), `in_period` (divide, round once), `share` (None when income is not positive, never a divide by zero), `percent_text`, `every_text` ("every month", "every 2 weeks"). Service: create/update/delete flows and per-workspace categories, and `move_category` (one place up or down; renumbers positions 0..n-1, so tied positions set through the API come out tidy); raises `CashFlowError`.
- **`clock.py`**: `now()` (tests monkeypatch it to freeze time), `today(tz)`, `local_date`, `is_known_zone`, `default_timezone()` (the `TIMEZONE` setting). Pure; no web imports
- **`users.py`**: `record_login(sub, email, name)`: match on `idp_sub`, else claim the unclaimed (pre-provisioned) row with this email, else insert. Callers must have checked the email is verified.
- **`db.py`**: Database connections (psycopg3). `get_connection_context()` lends a connection from a pool (`psycopg_pool`, one per database URL, 1–5 connections, each checked as it is handed out since Neon drops idle ones; `prepare_threshold=None` for Neon's PgBouncer). Anything the block didn't commit is rolled back before the connection goes back, as when connections were closed after use. The app's lifespan closes the pools. `get_connection()` is an unpooled connection the caller closes
- **`report.py`**: Interactive HTML report generation using Plotly
- **`cli.py`**: Typer CLI with `report`, `serve`, and `version` commands
- **`web/app.py`**: App wiring: the API routers, the login and auth routes, `/health`, `/mcp` and its protected resource metadata, the exception handlers (every error body `{"error": …}`; `LoginRequired` is always a JSON 401, since only the API needs a session), and **last** the React app's router (`spa.py`), which must stay last or it would shadow routes after it. `/docs`, `/redoc` and `/openapi.json` are public. There are no server-rendered pages but `/login`
- **`web/dashboard.py`**: Pure helpers over `get_all_records` + `get_accounts`, for `api_dashboard` and the MCP tools. `change_since` compares the latest snapshot with the earlier one closest to 30 days before it (ties to the older; none earlier → no change line). `filter_range` counts back from the latest snapshot, not today. `latest_category_totals` reads the latest snapshot's rows (so the columns meet the lines' ends; a same-day-retired account still counts until the next save); `account_cards` lists only active accounts (`computed_label`: "15% of gains, computed"). `category_bars` lays the columns on their side for phones (both bars on one scale, the larger total fills the track; negative categories draw nothing). Category colors go by size along the token ramps; past a ramp's end the last token fades toward `--surface` with `color-mix`. `getting_started(active)` is a new workspace's three steps (board Y), with workspace-relative action paths
- **`web/accounts_model.py`**: The Accounts page's facts, unformatted, for `api_accounts` (and `format_percent`/`formula_text` for the MCP tools): `accounts_view` (rows active first then by name, case-insensitively; Assets and Liabilities with their category groups in `AccountCategory` order, Uncategorized last, a group `retired` when all its rows are; `retired_count`; `snapshot_is_today`), `saved_total` (active rows' latest amounts), `candidate_groups` (the drawer's formula inputs: active, plain, not the account itself), `retire_state` (blocker, warning)
- **`web/api_routes.py`**: JSON API. `GET /api/me` (you + workspaces with roles); `POST /api/invites/{id}/accept|decline`; `POST /api/workspaces`; `GET/PATCH/DELETE /api/workspaces/{id}`; `/members` (list, `PATCH /{user_id}` role, `DELETE /{user_id}` remove or leave; someone not a member here is a 404); `/invites` (owner: create, list pending, `DELETE /{invite_id}` revoke); `/cash-flows` (list with per-day/month/year and totals, create, `PATCH`, delete) and `/cash-flow-categories` (list, create, `PATCH` name/position, delete); an id not in this workspace (`CashFlowNotFound`) is a 404, while a bad `category_id` in a flow's fields is a 400; `GET /accounts` (active accounts + latest amounts); `POST /snapshots` saves today's snapshot (today in the optional `X-Timezone` header's zone, else `TIMEZONE`) with `carry_forward=True`, so omitted plain accounts keep their latest amount, and reports each account's `source` (`updated`/`carried_forward`/`computed`). Session auth for now; logged-out `/api/` requests always get 401. All errors are `{"error": ...}`
- **`web/api_dashboard.py`, `web/api_accounts.py`**: page models for the React frontend, each a Pydantic response model (the OpenAPI schema it types against), computed by `dashboard.py` and `accounts_model.py`. Money is a two-place decimal string, dates ISO, categories by key (`bank_accounts`, `uncategorized`). `GET .../dashboard?range=` (net worth, change, history in range, latest categories with color tokens, phone bars, cards with account ids, `onboarding` with workspace-relative action paths when there is no snapshot). `GET .../accounts/overview?retired=` (sections, groups with subtotals, each account with its formula, `as_of` = the viewer's today, `last_saved`, `can_edit`). `GET .../accounts/{id}` (the drawer: eligible inputs, `retire_blocker`, `retire_warning`, history). Editor: `POST .../accounts` (201), `PATCH .../accounts/{id}` (only fields sent change; `formula: null` makes it plain, a formula without `cost_basis` keeps the basis), `POST .../accounts/{id}/retire|unretire`; each returns the account. Service refusals are 400 `{"error"}`, another workspace's account ids 404; a malformed body is FastAPI's 422. `/overview` is declared before `/{account_id}`
- **`web/api_cash_flows.py`**, **`web/api_settings.py`**: the JSON the React pages read, with Pydantic response models. `GET /api/workspaces/{id}/cash-flows/overview?per=` (viewer; unknown `per` is month): `cash_flows_model.cash_flows_figures` serialized (headline/net, bar slices, over-income marker, cards with every flow's fields, categories with drawer colors, `can_edit`). Money is a 2-decimal string (only `net`/`other_net` signed), shares are text, colors are CSS `var(--token)` values. `POST .../cash-flow-categories/{id}/move` `{"direction": "up"|"down"}` (editor; unknown id 404; ends are no-ops) returns the categories in order. `GET /api/workspaces/{id}/settings` (viewer): `settings_model.settings_facts` (members with `you`/`removable`, `can_leave`, `is_owner`, pending invites with sender and `lapsed`, owners only). `GET /api/invites`: your pending invites, oldest first, with `sender_name` and `acceptable` (false once lapsed; the welcome page and the invite strip show only acceptable ones)
- **`web/spa.py`**: the React app's build (`SPA_DIST`, else the checkout's `frontend/dist`) from the root, as the app's last route (a GET catch-all, not in the OpenAPI schema): `/assets/…` with `Cache-Control: public, max-age=31536000, immutable` (404 if missing, never the app), any other built file as is, and `index.html` with `no-cache` for every other GET no server route claimed (the client router's paths and its not-found page). Unknown paths under the server's prefixes (`/api/`, `/auth/`, `/.well-known/`) are JSON 404s, never the app. `/app` and `/app/…` (the build-out's home) redirect 301 to the same path without the prefix, query kept. Public, like `/login`: the shell holds no data and the SPA sends a 401 to `/login`. No build: the app's paths answer 503 saying how to build
- **`web/csrf.py`**: ASGI middleware. Every mutating `/api/` request (POST, PUT, PATCH, DELETE) must carry `X-Requested-With: sensibility` or gets 403 `{"error": "Missing the X-Requested-With: sensibility header"}` before any route (or the login check) runs. Reads, the login flow (outside `/api/`) and `/mcp` (bearer tokens) are untouched. Scripts calling the API must send the header too
- **`web/viewer_zone.py`**: `Today`, a dependency giving today's date for the request: the `X-Timezone` header's zone (the React app sends the browser's on every request; an unknown one is a 400), else `TIMEZONE`. The Jinja pages' `tz` cookie is gone and ignored
- **`web/access.py`**: `ViewerAccess`/`EditorAccess`/`OwnerAccess` for API routes with `{workspace_id}` in the path: **404** if you are not a live member (existence not revealed), **403** if your role is too low. `check_can_remove` is the one rule the services do not hold: owners remove anyone, anyone removes themselves (leaving)
- **`web/auth.py`**: OAuth/OIDC with PKCE, `ALLOWED_EMAILS` gate. The callback requires `email_verified: true` (identity lets unverified accounts log in) and calls `record_login`; the session holds the user `id` and `sub`. `require_user` reloads the user from the database on every request and refuses a missing row, a mismatched `sub`, or an email no longer allowed. A refused login renders `login.html` with a **403** (board X): `EmailNotAllowed` (not in `ALLOWED_EMAILS`, or no email) or `EmailUnverified`, each showing the email. **"Log in with a different account" is `GET /auth/switch`**: logging out only here is not enough, since identity keeps its own session and the next login would come straight back as the same account. It clears our session and goes to identity's `end_session_endpoint` with `post_logout_redirect_uri` set to **our callback** (the only URI identity has registered for this client, and identity requires an exact match); the session's `AFTER_IDP_LOGOUT` (read once by `after_idp_logout`, which accepts only `/auth/start` or `/login`) sends that code-less return on to a fresh `/auth/start`. **`/logout` takes the same trip** but returns to `/login`, so Log out ends identity's session too and the next Log in asks identity who you are. Without an `end_session_endpoint`, or with identity unreachable, both just clear our session and go to `/login`. `/login` reads identity's host for its footnote from the discovery doc's `authorization_endpoint` (`IDP_URL` is the in-cluster address), and falls back to generic text if identity is unreachable

### MCP (agent access)

Spec: `docs/superpowers/specs/2026-10-25-mcp-agent-access-design.md`. `/mcp` is the SDK's (`mcp` 2.3.0) `MCPServer`, stateless streamable HTTP with JSON responses (it serves both the 2026-07-28 protocol and the older initialize-handshake revisions), mounted as a plain Starlette `Route` (not in the OpenAPI schema) behind `mcp.gate.McpGate`. The app's lifespan (`mcp.server.running`) builds a fresh session manager each time, since one can run only once. The SDK's own auth is **not** used: Claude starts sign-in only on a real 401 and steps up only on a 403 `insufficient_scope`, and the SDK has no per-tool scopes, so the gate decides everything as HTTP before the SDK sees the request:

- **Tokens** (`mcp.tokens.verify`): identity's RFC 9068 access tokens only. ES256 against identity's JWKS, fetched from `IDP_URL` (in-cluster) and cached by `PyJWKClient`; header `typ: at+jwt`; `iss` exactly `IDP_ISSUER`; `aud` (string or list) containing `MCP_RESOURCE_URL`, compared canonically (scheme/host case, default port, trailing slash); `exp`, `iat`, `sub`, `client_id` required. Missing token: 401 `WWW-Authenticate: Bearer resource_metadata="…/.well-known/oauth-protected-resource/mcp", scope="sensibility:read sensibility:write"`; a bad one: the same with `error="invalid_token"`.
- **Users**: `sub` is `users.idp_sub`. An unknown `sub` is created or claimed through `record_login`, only with a verified email in `ALLOWED_EMAILS` (fails closed), exactly as browser login; a known user's email is re-checked against `ALLOWED_EMAILS` on every request. Refused: 403 with the reason.
- **Scopes**: a token needs `sensibility:read` or `sensibility:write`; a `tools/call` of any tool outside `tools.READ_TOOLS` (deny by default) needs `sensibility:write`, found by reading the JSON-RPC body. Otherwise 403 `Bearer error="insufficient_scope", scope="sensibility:read sensibility:write", resource_metadata="…"`. Write tools check the scope again. Role is the tool's business: read tools need viewer, write tools editor, and a role too low is a **tool error**, not a 403. Effective permission is the lower of the two.
- **Caller**: the gate sets a `ContextVar` that the SDK carries into the (threaded) tool call; `server._call` opens a connection and calls the plain function in `tools` with it.
- `GET /.well-known/oauth-protected-resource/mcp` (public): `resource`, `authorization_servers` (`[IDP_ISSUER]`), `scopes_supported`, `bearer_methods_supported: ["header"]`. With `MCP_RESOURCE_URL`, `IDP_ISSUER` or `IDP_URL` unset, it and `/mcp` answer 503.
- **Tools** (`mcp/tools.py`): `list_workspaces`, `get_balances`, `get_history`, `get_cash_flows`, `update_balances`, `save_cash_flow`, `delete_cash_flow`, `save_account`. Each takes `(conn, caller, …)` and returns a `results.ToolResult` (the output schema) whose `summary()` is the first text block; the second is the same JSON. Names, never ids, matched case-insensitively (`Name (asset)` / `Name (liability)` when both exist); unknown or ambiguous names fail listing candidates. `workspace` is optional with exactly one. `timezone` (IANA) else `TIMEZONE` decides today. `update_balances` refuses a second save on the same day unless `overwrite`, saying when the first was saved and what it holds; `preview` uses `preview_snapshot`. All business rules stay in the service layer; tools only translate names and messages. A new tool goes in `READ_TOOLS` or `WRITE_TOOLS` (a test checks they cover the registered tools).
- **Not yet**: bearer tokens on `/api/` (spec item 11). `/api/` is session-only.

### Frontend (React)

Spec: `docs/superpowers/specs/2026-10-28-react-frontend-design.md`; details and commands in `frontend/README.md`. Every page is a React SPA in `frontend/` (Vite, React 19, TypeScript strict, React Router 7 library mode, TanStack Query 5, Tailwind 4, Radix primitives copied in shadcn-style, sonner, lucide-react, Recharts; versions pinned exactly to footstrike-dashboard's lockfile), served from the root (`web/spa.py`) since the Phase C cutover (Oct 2026), which deleted the Jinja pages; only `login.html` (with its refused states) is still server-rendered. Rollback is `bif promote` of an earlier image. One image: the Dockerfile's `node:24-alpine` stage runs `npm ci && npm run build` and the Python image gets `dist/` at `/app/frontend/dist` (`SPA_DIST`).

- **Dev**: `ENV=dev uv run sensibility serve`, log in at `localhost:8000/login` (the cookie covers every port), then `npm run dev` in `frontend/` and open `localhost:5173/`. Vite proxies `/api`, `/auth`, `/login`, `/logout`, `/health` to `SENSIBILITY_BACKEND` (default `http://127.0.0.1:8000`). Or `npm run build` and open `localhost:8000/`.
- **Routes** (`src/router.tsx`, one module per page or drawer in `src/routes/`): `/` (into your oldest workspace, else `/welcome`), `/accounts` (the same, onto Accounts: bare paths predate workspaces in the URL), `/welcome`, `/workspaces/:workspaceId` (`?range=`), `…/accounts`, `…/accounts/new`, `…/accounts/:accountId/edit`, `…/cash-flows` (`?per=`), `…/cash-flows/new`, `…/cash-flows/:flowId/edit`, `…/cash-flow-categories`, `…/settings`, and a not-found page. **Drawers are child routes** of their page under a pathless layout route: the page renders `<Outlet />` and stays mounted; the drawer renders `<RouteSheet closeTo=…>` (Radix Dialog: right panel, full-screen sheet on phones, Escape/scrim/✕ close by navigating back, `data-autofocus` marks the field to focus). **Each page and drawer is lazy** (React Router `lazy`, its own chunk, through the `load` table), and `preloadRoutes()` (called from `App`) fetches every chunk in idle time after the first render, since the router holds the old page until a lazy route's chunk arrives; the dashboard chart is lazy on its own. A new page goes in `load`, `routes` and `src/page-routes.json` (`router.test.tsx` checks the JSON matches the router; the phone sweep reads it)
- **Shell** (`src/components/shell`): top bar, pill nav that is the bottom tab bar on phones (`data-tabbar` sets `--tabbar-h`), workspace picker (same section in the other workspace; the phone title), gear, account menu (New workspace → `/welcome`, Log out → `/logout` as a full navigation), invite strips (`GET /api/invites`, Join/Decline through the API), flashes as toasts (`flash.success/error`). Data from `GET /api/me`; a workspace you're not in is the not-found page. Pages get `useWorkspace()` (`id`, `name`, `role`, `base`, `canEdit`, `isOwner`) and set the title with `useDocumentTitle()`.
- **API** (`src/api/client.ts`): `api.get/post/patch/put/delete` only: same-origin cookie, `X-Timezone` from `Intl` on every request, `X-Requested-With: sensibility` on mutations, `{"error"}` thrown as `ApiError`, any 401 → `/login`. Query keys all in `src/api/queryKeys.ts` (inside a workspace they start `["workspaces", id]`); each area's types, fetchers and hooks in its own `src/api/<area>.ts`.
- **Tokens**: `src/styles/tokens.css` holds the design tokens (light and dark; `tests/test_spa.py` checks they match `base.html`'s, which login uses), exposed as Tailwind colors by name (`bg-surface`, `text-ink`, `text-muted`, `border-rule-strong`, `text-asset`, `bg-liability-2`, …; page background `bg-bg`). Tailwind's palette is removed and `src/test/tokens.test.ts` fails on any other color literal. **One breakpoint**: `phone:` (max-width 600px) and `desk:`; Tailwind's `sm:`/`md:`… are removed.
- **Accounts** (`routes/accounts.tsx`, `routes/account-drawer.tsx`, `api/accounts.ts`): The overview is always fetched with `retired=true` (Show retired is a client toggle). Staged edits live in page state and sessionStorage (`sensibility:staged-edits`) and survive the drawer, which is a child route. Figures a save will store are computed exactly, never in floats: `lib/decimal.ts` (BigInt decimals, ROUND_HALF_UP), `lib/formulas.ts` (`compute_snapshot`, `parse_formula`, `formula_preview`, tested with the Python tests' vectors), `lib/staged-edits.ts` (fields, live totals, the save body), `lib/amounts.ts` (parsing and the page's formatters). Saves go to `POST /api/workspaces/{id}/snapshots`, dated by `X-Timezone`; every account write awaits the refetch of the whole `["workspaces", id]` prefix before it resolves. Viewers get the amounts read-only and no save bar. Browser tests: `tests/browser/test_spa_accounts.py`
- **Dashboard** (`routes/dashboard.tsx`, `routes/dashboard-chart.tsx`, `routes/dashboard-key.tsx`, `api/dashboard.ts`, `lib/dashboard.ts`): Recharts (Plotly is only in the CLI's `report.py`). The range toggle sets `?range=` without a reload and keeps the old figures while the new range loads. Desktop: the lines, a dashed divider and the category columns on one dollar scale (the Plotly chart's fractions); phones: lines only, plus the stacked bars over the key. Every chart color is a `var(--token)` or the API's `color-mix()`, so the chart re-themes with the page; the axis ticks approximate Plotly's. The chart module is loaded lazily (Recharts is most of the bundle), so the key lives apart from it. Browser tests: `tests/browser/test_spa_dashboard.py`
- **Cash flows** (`routes/cash-flows.tsx`, `routes/cash-flow-drawer.tsx`, `routes/cash-flow-categories.tsx`, `api/cash-flows.ts`, `lib/cash-flows.ts`): `?per=` is kept in the page's links and the drawers' `closeTo`; the rates strip is exact BigInt-cents arithmetic (`formRates`; the browser test checks it against the service's `rates()`); the edit drawer reads its flow from the overview. A viewer, or an edit of a missing flow, is sent back to the page. Category saves report in the drawer footer's `role=status`, cash-flow saves as toasts. Browser tests: `tests/browser/test_spa_cash_flows.py`
- **Settings and Welcome** (`routes/settings.tsx`, `routes/welcome.tsx`, `api/settings.ts`, `lib/settings.ts`): Confirms are `?confirm=member-{id}|invite-{id}|leave|delete` (ignored when you could not act on them); a refusal shows in its section; a role saves when chosen. Leaving or deleting goes to your oldest remaining workspace, else `/welcome`. Join and Decline reuse `useAnswerInvite` (`api/shell.ts`). Browser tests: `tests/browser/test_spa_settings.py`
- **Loading** (details in `frontend/README.md`'s *Loading*): nothing renders blank while it waits. Pages and the shell show a skeleton in their own layout (`components/ui/skeleton.tsx`, inside `<Loading>`, which is `aria-busy` and fades in only after 150ms so a quick answer never flashes one). Drawers open at once with a `busy` sheet and fill in when their data lands; the account drawer is seeded from the page's overview, so only its history and Retire wait for the detail, and its form state is set once (a refetch never resets what was typed). Links prefetch their destination's queries on pointerenter, focus and touchstart (`api/prefetch.ts`); each area exports `queryOptions` objects that its hooks and the prefetch share. Data being replaced in place dims (`updating`), and every write button shows a spinner (`Button`'s `busy`)
- **Money formatting is per page on purpose** (each `lib/` formatter is a port of its Jinja page's, which went at the cutover): Accounts' `formatMoney` with a hyphen, the dashboard's and Cash flows' `money` with `−`. The server sends unformatted two-place strings; the Vitest tests pin the text

### Data Flow

1. The user edits amounts on the Accounts page (`/workspaces/{id}/accounts`). Edits are staged in the page (and `sessionStorage`) until **Save snapshot**.
2. `POST /api/workspaces/{id}/snapshots` sends `{values: {account_id: amount}, cost_bases: {account_id: basis}}`.
3. `accounts.save_snapshot` validates, updates cost bases, evaluates formulas via `formulas.compute_snapshot`, and upserts one `snapshots` row per active account for today, in the viewer's time zone. All in one transaction.
4. Retired accounts get no row, so their series end. Charts read `snapshots` joined to `accounts`; formulas are never re-evaluated for history.

### Database Schema

Migrations are managed by dbmate and stored in `db/migrations/`.

```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    idp_sub TEXT UNIQUE,        -- identity's stable id; NULL until a pre-provisioned row's first login
    email TEXT NOT NULL,        -- lowercased; refreshed at each login; not unique (only among unclaimed rows)
    name TEXT,
    is_admin BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMPTZ
);

CREATE TABLE workspaces (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMPTZ      -- soft delete; restore by setting it back to NULL
);

CREATE TABLE workspace_members (
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    role TEXT NOT NULL CHECK (role IN ('owner', 'editor', 'viewer')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (workspace_id, user_id)
);

CREATE TABLE workspace_invites (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
    email TEXT NOT NULL,        -- lowercased
    role TEXT NOT NULL,         -- owner | editor | viewer
    invited_by INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL,
    accepted_at TIMESTAMPTZ, accepted_by INTEGER REFERENCES users(id),
    declined_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,     -- at most one of accepted/declined/revoked
    -- unique (workspace_id, email) among open (unresolved) invites
);

CREATE TABLE cash_flow_categories (   -- per-workspace, unlike account categories
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
    name TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,   -- display order; new ones go last
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (workspace_id, name), UNIQUE (workspace_id, id)
);

CREATE TABLE cash_flows (   -- a current list, edited in place; not dated history
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
    name TEXT NOT NULL,                     -- unique per workspace
    direction TEXT NOT NULL,                -- income | expense
    amount NUMERIC(15, 2) NOT NULL,         -- >= 0; direction carries the sign
    every INTEGER NOT NULL,                 -- 1..1000
    unit TEXT NOT NULL,                     -- day | week | month | year
    category_id INTEGER,                    -- FK (workspace_id, category_id); category delete nulls it
    description TEXT,
    is_estimate BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE accounts (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
    name TEXT NOT NULL,
    type VARCHAR(10) NOT NULL CHECK (type IN ('asset', 'liability')),
    category TEXT CHECK (category IN (...)),  -- NULL = Uncategorized; values = models.AccountCategory
    formula JSONB,              -- NULL = plain; {"kind": "proportional", "rate": "0.15", "cost_basis": "70634.00"}
    retired_at DATE,            -- NULL = active
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (workspace_id, type, name),
    UNIQUE (workspace_id, id)   -- target of the composite keys below
);

-- The composite foreign keys make rows that cross workspaces impossible.
CREATE TABLE formula_inputs (   -- which plain accounts a computed account sums
    workspace_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    input_id INTEGER NOT NULL,
    PRIMARY KEY (account_id, input_id),
    FOREIGN KEY (workspace_id, account_id) REFERENCES accounts (workspace_id, id) ON DELETE CASCADE,
    FOREIGN KEY (workspace_id, input_id) REFERENCES accounts (workspace_id, id),
    CHECK (account_id <> input_id)
);

CREATE TABLE snapshots (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER NOT NULL,
    date DATE NOT NULL,
    account_id INTEGER NOT NULL,   -- FOREIGN KEY (workspace_id, account_id) REFERENCES accounts (workspace_id, id)
    amount DECIMAL(15, 2) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX idx_snapshots_unique ON snapshots(date, account_id);
```

### Configuration

- **`.env.dev` / `.env.prod`**: Database URL and web settings per environment
- **Environment variable `ENV`**: Controls which `.env` file is loaded (default: `dev`)

#### Web Dashboard Environment Variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `IDP_URL` | OAuth identity provider URL (e.g., `https://identity.ethanswan.com`) |
| `CLIENT_ID` | OAuth client ID |
| `CLIENT_SECRET` | OAuth client secret |
| `SECRET_KEY` | Random secret for signing session cookies |
| `ALLOWED_EMAILS` | Comma-separated allowlist, checked at login (403) and on every request (401). **Fails closed**: unset or blank lets nobody in, except under `ENV=dev`. Set in both k8s env configmaps; identity has open registration, so it is the only thing keeping other identity users out |
| `ENV` | Set to `dev` for local development (disables secure cookies)
| `MCP_RESOURCE_URL` | The MCP endpoint's URL, exactly as identity puts it in `aud` and as the protected resource metadata's `resource`: `https://sensibility.money/mcp` (prod), `https://staging.sensibility.money/mcp` (staging) |
| `IDP_ISSUER` | identity's external issuer, compared exactly with `iss` (identity's `JWT_ISSUER`): `https://identity.ethanswan.com` (prod), `https://identity-staging.tailc06f30.ts.net` (staging). Keys come from `IDP_URL` |
| `TIMEZONE` | Fallback IANA zone for "today" (default America/Chicago), used when the request names no valid zone of its own (see *Today is the viewer's day*) |

### Testing

Tests are organized by module with pytest:
- `test_repository.py`: Database operations tests (uses testcontainers)
- `test_cli.py`: CLI command tests
- `test_models.py`, `test_formulas.py`: Pure unit tests (Hypothesis for the formula property)
- `test_accounts.py`: Service rules and the save transaction (testcontainers)
- `test_migration.py`: Applies migrations to legacy rows and checks the backfill and rollback; the workspaces migration also checks the database refuses rows crossing workspaces. `test_every_migration_reverses_cleanly` runs all ups, all downs, all ups, so a new migration needs a working down
- `test_cashflows.py`: Rate math against rows from the original spreadsheet, Hypothesis properties (equivalent frequencies agree, direction only flips the sign, category totals add up to `totals()`), period and wording helpers, rules, and workspace scoping down to the repository
- `test_users.py`, `test_workspaces.py`, `test_invites.py`: Login matching/claiming; workspace and invite rules, including concurrency tests for the last-owner lock and accept-vs-revoke
- `test_dashboard.py`: Pure tests of the dashboard helpers (30-day change edge cases, ranges and month-end clamping, category totals and ramps, the phone's category bars, cards, `computed_label`, the getting-started steps)
- `test_db.py`: the connection pool: connections reused, uncommitted work rolled back (never committed), a connection usable after a block raised or a statement failed, a terminated connection replaced
- `test_cash_flows_model.py`: the Cash flows figures as the API serves them (`cash_flows_overview`), hand-worked: each period, no income, expenses above income (board AA, the marker, by a hair), equal, zero slices, estimates, expense colors by size
- `test_accounts_model.py`: the Accounts page's facts (`accounts_model`): rows, order, groups, saved totals, formula text, formula inputs
- `test_mcp_tokens.py`: the token verifier (signature, `typ`, `iss`, `aud` forms, expiry, required claims, other algorithms) and `JwksKeys` against a stubbed JWKS; config fails closed
- `test_mcp_http.py`: `/mcp` over HTTP: the exact 401 and 403 headers, read-only tokens stepping up on write tools, users created or claimed on first use and refused when unverified or not allowed (and re-checked every request), the PRM document, `tools/list` annotations and output schemas
- `test_mcp_tools.py`: each tool against seeded data: balances and change, history intervals and period-end rows, cash flows matching the page in every period, `update_balances` (sources, preview, same-day `overwrite`, computed accounts, zones), cash flow and account writes with every documented error and role
- `test_mcp_client.py`: end to end through the SDK's own client over streamable HTTP into the app, on both protocol eras, with a minted token. Tokens come from `tests/mcp_support.py` (a test ES256 key; the `mcp_env` fixture points the app at it)
- `test_web.py`: FastAPI TestClient with a signed session cookie against the container: the allowlist, the login page's themes, `GET /accounts` and `POST /snapshots`, the callback and logout, and the every-route login and allowlist sweeps (every protected route is under `/api/`)
- `test_login_page.py`: the login page, refused logins (not allowed, unverified, no email), `/auth/switch` and `/logout`.
- `test_viewer_zone.py`: today is the `X-Timezone` header's day (saves, retirements, the overview's `as_of`), an unknown zone is a 400, no header is `TIMEZONE`, and a leftover `tz` cookie is ignored. `FakeIdp` (in `web_support`) carries a `client_id` and `server_metadata`; public routes are listed in `web_support.PUBLIC_PATHS`
- `test_api_cash_flows.py`, `test_api_settings.py`: the pages' JSON. The overview against the service's math (`totals`, `category_totals`) and the color rules for every dataset shape and period, and over HTTP; category move (ends, ties, 404s, roles); settings per role, lapsed invites, `GET /api/invites`
- `test_spa.py`: serving the React app from the root against a stand-in build (index for every app path, `no-cache`; `/app/…` 301s to the same path and query without the prefix; immutable assets; missing asset 404; no path traversal; 503 without a build; unknown `/api/`, `/auth/`, `/.well-known/` paths stay JSON 404s; `/login`, `/health`, `/docs`, `/mcp` and the PRM document still reach the server) and base.html's tokens matching `frontend/src/styles/tokens.css`
- `test_csrf.py`: the API header rule: every mutating `/api/` route refuses without it (before login), other values are refused, reads and paths outside `/api/` are untouched, `/mcp` is exempt. **The `client` fixture sends the header on every request** (`web_support.API_HEADERS`); a test that wants it off deletes it from `client.headers`
- `test_workspace_api.py`: Isolation sweep (a member of workspace 2 gets 404 on every workspace-1 route and changes nothing; reads show only your own workspace), role sweeps (exact 403 sets for viewer and editor), workspace, member, invite and cash-flow endpoints with their refusal messages (someone else's or a missing id is a 404), login
- `browser/`: real-browser tests of the React app (Playwright, Chromium only), marked `browser`. They run the app under uvicorn in a subprocess against the session's test container (so nothing is shared with TestClient), log in by adding the signed `session` cookie to the browser context, and fail on any uncaught JS error. The session's server serves `frontend/dist` (`SPA_DIST`), and the `spa_dist` fixture runs `npm run build` (and `npm ci` if there are no `node_modules`) when `dist/` is missing or older than any source in `frontend/`, so the browser tests need npm; CI builds it in an earlier step and the fixture finds it fresh. One file per area: `test_spa_shell.py` (desktop, tablet and phone top bar and tab bar, the account menu, the invite strip and flashes, the drawer frame, `/` → oldest workspace, a lost session → `/login`, an API write without the header refused, the tab bar staying put while a field has focus, every page chunk preloaded), `test_spa_dashboard.py` (headline, range toggle, the chart on desktop and phone, re-theming, getting-started), `test_spa_accounts.py` (staging, "was $X", the save bar, computed accounts recomputing, Discard, sessionStorage across reloads, a save dated in the browser's zone, the drawer in every state), `test_spa_cash_flows.py` (every period and state, both drawers, the rates strip against the service's `rates()`, rename on blur, Enter's single save, the 44px move targets) `test_spa_settings.py` (settings and welcome, every write and confirm) and `test_spa_loading.py` (with a response held by `page.route`, the drawer and its header appear before it and the form after; a page's first load shows its skeleton; the loading drawer fits a phone). **Fonts**: `open_page` loads every web-font face (`LOAD_FONTS` in `tests/browser/conftest.py`) before handing over the page, because Google Fonts swaps in after the page loads and text in the fallback face is wider; a layout assertion that runs before that races the download and flakes in CI. **Phones**: `open_page(path, phone=390)` opens a page as a phone (touch, mobile viewport), and `tests/browser/mobile.py`'s `assert_fits_phone` checks the whole page, header and tab bar included, for no sideways scroll, 44px tap targets and 16px fields at `PHONE_WIDTHS` (320, 390); each area's file runs it on every page and drawer state. `test_mobile_sweep.py` opens every page at both widths: the React app's routes from `frontend/src/page-routes.json` (which a Vitest test keeps equal to the router) plus the server's one HTML page, `/login`, and **fails when a page has no entry in its `SCREENS`**; it also fits the refused-login 403 pages, rendered in-process and served to the browser with `page.route`. On a phone a drawer slides up, so wait for `document.getAnimations()` to finish before measuring positions in one; the React app renders after its first API call, so wait for the page's heading first
- `test_api_dashboard.py`, `test_api_accounts.py`: the page-model endpoints against the helpers they come from and hand-worked figures (ranges, the range leaving the headline alone, no snapshot, computed and retired accounts, another workspace's snapshots never counting), every create/update/retire refusal with the service's message, foreign ids 404, viewers 403

`conftest.py` seeds workspace `WS = 1` owned by user `USER_ID = 1` (`tests/support.py`) before every DB test; web helpers (sessions, `FakeIdp`, `sweep`, `add_user`, and `PAGES`, the seeded workspace's page prefix) live in `tests/web_support.py`. **New routes are swept automatically** (they come from the OpenAPI schema); the role sweeps compare exact 403 sets, so a new write route makes them fail until you decide its role.

The project uses:
- **testcontainers**: Spins up real PostgreSQL containers for database tests
- **hypothesis**: Property-based testing

To run tests: `uv run pytest`

**Frontend unit tests** are Vitest in `frontend/` (`npm test`), run by CI's **Frontend** job (lint, typecheck, test, build) in parallel with the Python jobs.

**Browser tests** are excluded from that run (`addopts` has `-m 'not browser'`); opt in with `uv run pytest -m browser` (a later `-m` overrides the default, so `-m browser tests/browser/test_x.py` works for one file). They need Chromium once: `uv run playwright install chromium`; without it they fail at setup with that command in the message. They take about 20s locally. CI runs them as their own **Browser Tests** job, in parallel with Test All, with the Playwright download cached. A change to a page's behavior should come with a Vitest or browser test that fails without it.

### Rules worth knowing

- **Formula inputs must be plain, active accounts.** A computed account cannot feed another. An account that is an input cannot be made computed.
- **Retire flow**: Retire from the account's drawer at any amount; a non-zero last value only produces a warning (`retire_warning`). Blocked (`retire_blocker`) only while an active computed account lists it as an input. Retirement writes no row: the series ends at the last saved value.
- **Partial saves** (`carry_forward`) fill only from the latest snapshot *date*; an active plain account with no row there must be sent explicitly.
- **Same-day Save replaces** that day's rows. Retired accounts get no row.
- **Repository never commits**; the service layer does. `save_snapshot` uses `conn.transaction()`.
- **Workspace scoping**: a new table holding workspace data gets a `workspace_id` with a composite foreign key to its parent's `(workspace_id, id)`, and every repository function for it takes `workspace_id`. A new API route takes `ViewerAccess`/`EditorAccess`/`OwnerAccess`, and an id from another workspace is a 404. A page links within its workspace through `useWorkspace().base`.
- **Drawers**: a form is a drawer over its page: a child route rendering `<RouteSheet closeTo=…>` (see *Frontend (React)*), so the page stays mounted and closing is a client navigation. A refusal shows inside the drawer, keeping what was typed.
- **Mobile** (`docs/superpowers/specs/2026-10-26-mobile-design.md`): one breakpoint, `phone:` (max-width 600px); desktop above it is unchanged. `--gutter` (24px, 16px on phones) is the side padding (`px-gutter`); `--tabbar-h` is the bottom tab bar's height on phones (0px elsewhere; it does not change while a field has focus, so nothing under a finger moves). Anything fixed to the bottom sits at `bottom: var(--tabbar-h)`. On phones the main nav is the bottom tab bar (its icons are hidden on desktop), the workspace select is the title, and drawers are full-screen sheets. Tap targets 44px, fields 16px (iOS zooms below), hover styles only where hovering exists.
- **Frontend tokens**: every color is a design token, light and dark (`prefers-color-scheme`), in `frontend/src/styles/tokens.css`; components name tokens, never colors (`src/test/tokens.test.ts`). `base.html` holds the same tokens for `login.html`, which names tokens too (`test_web.py`), and `test_spa.py` keeps the two in step. Design: `docs/superpowers/specs/2026-10-26-frontend-redesign-design.md`.
- **Roles**: viewer reads; editor also changes data; owner also manages the workspace and members. A workspace always keeps at least one owner. Anyone may leave (`DELETE .../members/{self}`) except the last owner.
- **Today is the viewer's day.** Snapshot dates and `retired_at` use the zone of the person acting (`Today` in `web/viewer_zone.py`, from the `X-Timezone` header the React app sends), never `date.today()` (pods run in UTC) and never a per-workspace setting. They stay calendar dates, not timestamps. A request without the header uses `TIMEZONE`.
- **Latest snapshot date is per workspace.** Never compute `MAX(date)` over all snapshots.
- **Admin**: `users.is_admin`, set only by the migration on the pre-provisioned `ethanpswan@gmail.com` row. Grants nothing yet; it does not bypass workspace membership.
- **Categories** group rows under subheadings on the Accounts page (enum order, Uncategorized last, empty groups hidden). Any category may be used on either type. Adding one means a value in `AccountCategory` *and* a migration widening the CHECK constraint.
- **Adding a formula kind** later: one Pydantic class in `models.py` (make `Formula` a discriminated union on `kind`), one branch in `formulas._evaluate`, one form variant. No migration.
