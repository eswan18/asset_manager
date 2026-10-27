# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Asset Manager is a Python application for tracking financial assets and liabilities. Values are entered on the web dashboard's Accounts tab (or the JSON API) and saved as dated snapshots in PostgreSQL. Liabilities can be computed from other accounts by a formula. Data belongs to **workspaces**; users are members of workspaces with a role. Multi-user is the plan (open sign-up eventually); today `ALLOWED_EMAILS` gates who can log in.

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
ENV=dev uv run asset-manager report --workspace 1
ENV=dev uv run asset-manager report --workspace 1 --output report.html --no-open

# Run web dashboard locally
ENV=dev uv run asset-manager serve
ENV=dev uv run asset-manager serve --port 8080

# Show version
uv run asset-manager version

# Or use python -m invocation
ENV=dev uv run python -m asset_manager report --workspace 1
```

### Development Commands
- **Run tests**: `uv run pytest` (browser tests excluded; `uv run pytest -m browser` runs them, after a one-time `uv run playwright install chromium`)
- **Run tests with coverage**: `uv run pytest --cov=asset_manager`
- **Type checking**: `uv run ty check src/asset_manager`
- **Linting**: `uv run ruff check src tests`
- **Code formatting**: `uv run ruff format src tests`

## Architecture

### Project Structure

```
asset_manager/
├── src/
│   └── asset_manager/
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
│       └── web/                # Web dashboard
│           ├── __init__.py
│           ├── app.py          # FastAPI application
│           ├── auth.py         # OAuth/OIDC authentication
│           ├── access.py       # Which workspace a request acts in; role checks
│           ├── viewer_zone.py  # Today: the viewer's date (tz cookie / X-Timezone)
│           ├── accounts_routes.py  # Accounts page, account form, POST /snapshots
│           ├── api_routes.py   # JSON API: /api/me, /api/workspaces/...
│           ├── cash_flows_routes.py  # Cash flows page, its view model, its two drawers
│           ├── charts.py       # The dashboard's Plotly figure (lines + columns)
│           ├── dashboard.py    # Dashboard numbers: 30-day change, ranges, categories
│           ├── rendering.py    # Templates, render(), flash messages (base.html: success role=status, error role=alert, a × to dismiss)
│           ├── settings_routes.py  # Workspace settings: name, people, leave, delete
│           ├── welcome_routes.py   # Welcome: your invites, create a workspace
│           ├── invite_strip.py # The shell's invite strips; safe_next for Decline
│           ├── wording.py      # a_role ("an editor"), day_text ("Nov 3")
│           └── templates/
│               ├── account_form.html  # Drawer over accounts.html (extends it)
│               ├── accounts.html
│               ├── _components.html  # Jinja macros for the shared pieces
│               ├── base.html   # Tokens, shell, shared drawer styles and Escape
│               ├── cash_flow_categories.html  # Categories drawer over cash_flows.html
│               ├── cash_flow_form.html  # Cash flow drawer over cash_flows.html
│               ├── cash_flows.html
│               ├── dashboard.html
│               ├── login.html
│               ├── settings.html  # Board V
│               └── welcome.html   # Board W; header without nav or picker
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
- **`accounts.py`**: Service layer; every function takes the `workspace_id` it acts in. `create_account`/`update_account` enforce input rules; `retire_account` refuses only inputs of active computed accounts; `save_snapshot` is all-or-nothing. Raises `AccountError` with user-facing messages. Commits.
- **`repository.py`**: Thin SQL. Never commits. Every account/snapshot function takes `workspace_id` and filters on it, so another workspace's ids behave as nonexistent.
- **`workspaces.py`**: `create_workspace` (creator becomes owner), `update_workspace` (name), `delete_workspace` (soft), `change_role`/`remove_member` (refuse to drop the last owner; lock the member rows `FOR UPDATE`). `is_last_owner(member, members)` is that rule as a predicate, for pages deciding whether to offer Leave. Raises `WorkspaceError`.
- **`invites.py`**: Owners invite an email with a role; expires after `INVITE_TTL` (14 days). Only the invited (verified) email can accept or decline; anything else is `InviteNotFound` (404), so ids reveal nothing. An invite lapses once its sender is no longer an owner (`sender_is_owner`); `acceptable_invites(email)` leaves lapsed ones out in one query (`repo.get_acceptable_invites_for_email`, with the sender's name), for the welcome page and the invite strip (`GET /api/invites` still lists them). Invites never bypass `ALLOWED_EMAILS`. **No email is sent** yet; the invitee is told out of band and finds it in the strip on every page, on `/welcome`, or via `GET /api/invites`.
- **`cashflows.py`**: Recurring income/expenses. `per_year(flow)` is signed (expenses negative) and divides once, at the end, so equivalent frequencies (2 weeks / 14 days, 12 months / 1 year) agree exactly; `rates()` rounds to cents; `totals()` sums unrounded and rounds once. `category_totals(flows, categories)` groups expenses by category (every category in `position` order, empty ones too, then Uncategorized if any; an unknown `category_id` counts as Uncategorized) and sums each unrounded, so they add up to `totals()`'s expenses exactly. Page helpers: `Period` (day/month/year) with `parse_period` (unknown values fall back to month), `in_period` (divide, round once), `share` (None when income is not positive, never a divide by zero), `percent_text`, `every_text` ("every month", "every 2 weeks"). Service: create/update/delete flows and per-workspace categories, and `move_category` (one place up or down; renumbers positions 0..n-1, so tied positions set through the API come out tidy); raises `CashFlowError`.
- **`clock.py`**: `now()` (tests monkeypatch it to freeze time), `today(tz)`, `is_known_zone`, `zone_for(explicit, cookie)` (explicit, else a known cookie zone, else `TIMEZONE`). Pure; no web imports
- **`users.py`**: `record_login(sub, email, name)`: match on `idp_sub`, else claim the unclaimed (pre-provisioned) row with this email, else insert. Callers must have checked the email is verified.
- **`db.py`**: Database connection management using psycopg3
- **`report.py`**: Interactive HTML report generation using Plotly
- **`cli.py`**: Typer CLI with `report`, `serve`, and `version` commands
- **`web/app.py`**: App wiring, dashboard (`/workspaces/{id}`, `?range=6m|1y|all`, default 1y), auth routes, and the bare-path redirects: `GET /` and `GET /accounts` go to the same page in your oldest live workspace, or to `/welcome` if you have none. `/docs`, `/redoc` and `/openapi.json` are public. A workspace with no snapshot yet gets the **getting-started dashboard** (board Y, `dashboard.onboarding_context`): three steps, where step 1 ("+ Add an account") carries the button until an active account exists, then step 2 ("Enter balances", to Accounts); a placeholder chart; the cards listing any accounts with "—". Viewers get no buttons and a line saying an editor hasn't added anything yet. Empty Accounts and Cash flows pages use `ui.empty_card` (what goes here, one add button for editors)
- **`web/dashboard.py`**: Pure helpers over `get_all_records` + `get_accounts`. `change_since` compares the latest snapshot with the earlier one closest to 30 days before it (ties to the older; none earlier → no change line). `filter_range` counts back from the latest snapshot, not today. `latest_category_totals` reads the latest snapshot's rows (so the columns meet the lines' ends; a same-day-retired account still counts until the next save); `account_cards` lists only active accounts. Category colors go by size along the token ramps; past a ramp's end the last token fades toward `--surface` with `color-mix`
- **`web/charts.py`**: One Plotly figure, two x domains sharing one y-axis. Every trace names its color as a token in `meta`; the page's script resolves the tokens and calls `Plotly.react`, again on a `prefers-color-scheme` change. The hex values in `charts.py` are only light-theme fallbacks (page templates may not contain hex colors). A lone snapshot gets markers and a fixed axis (the 30 days before it), since Plotly would otherwise zoom one date down to milliseconds
- **`web/accounts_routes.py`**: Accounts page, account form, `POST .../snapshots`, all under `/workspaces/{workspace_id}`. **A page's path is its API path without `/api`** (`/api/workspaces/1/accounts` is the data behind `/workspaces/1/accounts`). The account form (`.../accounts/new`, `.../accounts/{id}/edit`, and a POST's 400 re-render) is a **drawer over the Accounts page**: `account_form.html` extends `accounts.html`, both built from `accounts_view()`, and sets `drawer_open`, which makes `base.html` render the page behind `inert` and fill its `drawer` block. No JS needed to open or close it: Close, Cancel and Escape are links back to `.../accounts`. Its validation error is `form_error`, not `error` (`base.html` would show that behind the scrim). The drawer styles and the Escape handler live in `base.html`, shared with the Cash flows drawers
- **`web/cash_flows_routes.py`**: `GET /workspaces/{id}/cash-flows?per=day|month|year` (default month). `cash_flows_view` builds every figure: the net "left over", the "Where income goes" bar (100% = income; all expenses, scaled to their total, when they exceed income; empty when there is no income), the cards (Income, then expense categories that have flows, Uncategorized last). **Expenses above income** (board AA): the headline reads "Short each {period}" in `--danger`; the bar's 100% is total expenses, with `marker` (income's unrounded share of expenses) placing a line and "▲ Income runs out", the part past it hatched; `over_by` and `over_share` (of income, display-rounded) give "Expenses exceed income by $X (N%)". Zero income stays the "no income" state, and `colors` (each expense category's color by id, for the drawers). Expense colors follow the liability ramp by size, largest strongest; past four, the rest share `--liability-4`. Two drawers over the page, as the account form is over Accounts, each keeping `?per=`: the **cash flow form** (`.../cash-flows/new?direction=&category_id=`, `.../cash-flows/{id}/edit`; POST `.../cash-flows`, `.../cash-flows/{id}`, `.../cash-flows/{id}/delete`, which redirect to the page with a flash) and **categories** (`GET .../cash-flow-categories?confirm={id}&add=1`; POST create, `/{id}` rename, `/{id}/move` with `direction=up|down`, `/{id}/delete`, which come back to the drawer and flash in its footer). Delete confirms in the row via `?confirm=`, so no JS is needed. `_parse_form` only turns the form's text into fields (plain digits, no exponents); every rule is the service's. `form_rates` gives the rates strip from `rates()`, so it matches the page; the drawer's script recomputes it exactly in BigInt cents. All drawer routes are editor-only (they exist to write); viewers see the page with no controls. The period toggle always links to the page itself
- **`web/api_routes.py`**: JSON API. `GET /api/me` (you + workspaces with roles); `GET /api/invites` (your pending invites), `POST /api/invites/{id}/accept|decline`; `POST /api/workspaces`; `GET/PATCH/DELETE /api/workspaces/{id}`; `/members` (list, `PATCH /{user_id}` role, `DELETE /{user_id}` remove or leave); `/invites` (owner: create, list pending, `DELETE /{invite_id}` revoke); `/cash-flows` (list with per-day/month/year and totals, create, `PATCH`, delete) and `/cash-flow-categories` (list, create, `PATCH` name/position, delete); `GET /accounts` (active accounts + latest amounts); `POST /snapshots` saves today's snapshot (today in the optional `X-Timezone` header's zone, else the `tz` cookie's, else `TIMEZONE`) with `carry_forward=True`, so omitted plain accounts keep their latest amount, and reports each account's `source` (`updated`/`carried_forward`/`computed`). Session auth for now; logged-out `/api/` requests always get 401. All errors are `{"error": ...}`
- **`web/viewer_zone.py`**: `Today`, a dependency giving today's date for the request; `today_for(request)` for shared helpers. Explicit `X-Timezone` header wins (unknown one: 400), else the `tz` cookie that `base.html` sets from `Intl.DateTimeFormat().resolvedOptions().timeZone` on every page load (unknown or missing: silently `TIMEZONE`)
- **`web/access.py`**: `ViewerAccess`/`EditorAccess`/`OwnerAccess` for API routes and pages with `{workspace_id}` in the path: **404** if you are not a live member (existence not revealed), **403** if your role is too low. `shell_context(request, access, path=None)` is what `base.html` needs on every page (user, workspace, picker links, and the **invite strip**: board Z, one strip per acceptable invite, newest first, one query); a page that re-renders after a refused POST (or a drawer) passes its own GET path, or the picker links to the POST path in other workspaces. `here` is where the strip's Decline returns: the request with its query on a GET, else that path. `base.html` hides the strip under a drawer; `/welcome` and login have no `shell_context`, so no strip. `check_can_remove` is the one rule the services do not hold: owners remove anyone, anyone removes themselves (leaving); the API and the settings page both call it. A page without a workspace (welcome) passes no `workspace`, and `base.html` drops the nav, picker and settings gear
- **`web/settings_routes.py`**: `GET /workspaces/{id}/settings` for every member (board V). Owners: General (rename, `POST .../settings`), Leave and Delete (`POST .../delete`, soft), and People: invite (`POST .../invites`), a role select per member (`POST .../members/{user_id}`, auto-submitted by a small script; its Save button is the no-JS fallback), × to remove (`POST .../members/{user_id}/remove`; on your own row it means Leave) and pending invites with × to revoke (`POST .../invites/{id}/revoke`). Editors and viewers get it read-only: members with roles as text, no pending invites (the API lists them to owners only), and Leave. Removing, revoking, leaving and deleting confirm in the page via `?confirm=member-{id}|invite-{id}|leave|delete` (ignored when you could not act on it). The last owner is not offered Leave. Writes redirect back with a flash, or to `/` after leaving or deleting; refusals re-render (400) with the service's message beside the control and the user's input kept. Dates ("Sent by you Oct 20 · expires Nov 3") are in the viewer's `tz` cookie zone (`viewer_zone.zone_of`)
- **`web/welcome_routes.py`**: `GET /welcome` (board W), for anyone logged in: "Welcome, {first name}" with no workspace, "New workspace" otherwise (the user menu links here). Lists `acceptable_invites` with Join (`POST /invites/{id}/accept`, into that workspace's dashboard with a flash) and Decline (`POST /invites/{id}/decline`, back to the form's `next` if `invite_strip.safe_next` passes it, a same-site path with no `//`, backslash or control characters, else here); someone else's invite id is a 404. Create (`POST /workspaces`) goes into the new workspace. These are the API's paths without `/api`
- **`web/auth.py`**: OAuth/OIDC with PKCE, `ALLOWED_EMAILS` gate. The callback requires `email_verified: true` (identity lets unverified accounts log in) and calls `record_login`; the session holds the user `id` and `sub`. `require_user` reloads the user from the database on every request and refuses a missing row, a mismatched `sub`, or an email no longer allowed. A refused login renders `login.html` with a **403** (board X): `EmailNotAllowed` (not in `ALLOWED_EMAILS`, or no email) or `EmailUnverified`, each showing the email. **"Log in with a different account" is `GET /auth/switch`**: logging out only here is not enough, since identity keeps its own session and the next login would come straight back as the same account. It clears our session and goes to identity's `end_session_endpoint` with `post_logout_redirect_uri` set to **our callback** (the only URI identity has registered for this client, and identity requires an exact match); the session's `AFTER_IDP_LOGOUT` (read once by `after_idp_logout`, which accepts only `/auth/start` or `/login`) sends that code-less return on to a fresh `/auth/start`. **`/logout` takes the same trip** but returns to `/login`, so Log out ends identity's session too and the next Log in asks identity who you are. Without an `end_session_endpoint`, or with identity unreachable, both just clear our session and go to `/login`. `/login` reads identity's host for its footnote from the discovery doc's `authorization_endpoint` (`IDP_URL` is the in-cluster address), and falls back to generic text if identity is unreachable

### Data Flow

1. The user edits amounts on `/accounts`. Edits are staged in the page (and `sessionStorage`) until **Save snapshot**.
2. `POST /snapshots` sends `{values: {account_id: amount}, cost_bases: {account_id: basis}}`.
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
- `test_dashboard.py`: Pure tests of the dashboard helpers (30-day change edge cases, ranges and month-end clamping, category totals and ramps, cards, formatting) and the figure's structure
- `test_cash_flows_page.py`: the Cash flows view model (periods, no income, expenses above income, colors) and the page against the container, including another workspace's flows never appearing
- `test_cash_flow_drawers.py`: both Cash flows drawers: prefill, create/edit/delete, every validation error, the rates strip, header colors, categories create/rename/move/delete (flows become Uncategorized), the period surviving every round trip, isolation (another workspace's ids are 404) and roles
- `test_account_drawer.py`: the account form drawer in every state (new of either type, edit plain and computed, retire warning and blocker, retired, validation errors, viewers) and `formula_preview`, the computed-value line
- `test_web.py`: FastAPI TestClient with a signed session cookie against the container, including the every-route login and allowlist sweeps
- `test_settings_page.py`, `test_welcome_page.py`: Workspace settings as owner, editor and viewer (every write, refusal and `?confirm=`), and the welcome page (invites, join/decline, create, bare-path redirects). Both set `client.follow_redirects = False` so tests read each redirect
- `test_login_page.py`: the login page, refused logins (not allowed, unverified, no email), `/auth/switch` and `/logout`.
- `test_invite_strip.py`: board Z: the invite strip (which invites, order, where it shows), Decline's `next` (`safe_next`), Join, the flash markup and roles, the snapshot-saved flash, the header gear. `FakeIdp` carries a `client_id` and `server_metadata`; public routes are listed in `web_support.PUBLIC_PATHS`
- `test_empty_states.py`: the getting-started dashboard (editor vs viewer, accounts but no snapshot) and the empty Accounts and Cash flows pages
- `test_workspace_api.py`: Isolation sweep (a member of workspace 2 gets 404 on every workspace-1 route and changes nothing), role sweeps (exact 403 sets for viewer and editor), members, login
- `browser/`: real-browser tests of the page scripts (Playwright, Chromium only), marked `browser`. They run the app under uvicorn in a subprocess against the session's test container (so nothing is shared with TestClient), log in by adding the signed `session` cookie to the browser context, and fail on any uncaught JS error. Covered: Accounts staging, "was $X", the save bar's count and net worth, computed accounts recomputing, Discard, sessionStorage across reloads, and a save dated in the browser's zone via the `tz` cookie; the account drawer (focus, inert page, scroll lock, Escape, the live computed-value line, type switch); the cash flow drawer's rates strip (checked against `form_rates` and the server-rendered strip), header colours and Escape; categories rename-on-blur, the Enter double-submit guard and the 44px move targets; the dashboard chart re-theming (Plotly served from the plotly package, no network). **Phones**: `open_page(path, phone=390)` opens a page as a phone; `tests/browser/mobile.py`'s `assert_fits_phone` checks no sideways scroll, 44px targets and 16px fields at `PHONE_WIDTHS` (320, 390); `test_mobile_*.py` per area (`test_mobile_shell.py`: top bar, tab bar, menu, strip, flash, drawer frame). On a phone the drawer slides up, so wait for `document.getAnimations()` to finish before measuring positions in one

`conftest.py` seeds workspace `WS = 1` owned by user `USER_ID = 1` (`tests/support.py`) before every DB test; web helpers (sessions, `FakeIdp`, `sweep`, `add_user`, and `PAGES`, the seeded workspace's page prefix) live in `tests/web_support.py`. **New routes are swept automatically** (they come from the OpenAPI schema); the role sweeps compare exact 403 sets, so a new write route makes them fail until you decide its role.

The project uses:
- **testcontainers**: Spins up real PostgreSQL containers for database tests
- **hypothesis**: Property-based testing

To run tests: `uv run pytest`

**Browser tests** are excluded from that run (`addopts` has `-m 'not browser'`); opt in with `uv run pytest -m browser` (a later `-m` overrides the default, so `-m browser tests/browser/test_x.py` works for one file). They need Chromium once: `uv run playwright install chromium`; without it they fail at setup with that command in the message. They take about 20s locally. CI runs them as their own **Browser Tests** job, in parallel with Test All, with the Playwright download cached. A change to a page script should come with a browser test that fails without it.

### Rules worth knowing

- **Formula inputs must be plain, active accounts.** A computed account cannot feed another. An account that is an input cannot be made computed.
- **Retire flow**: Retire from the edit page at any amount; a non-zero last value only produces a warning (`retire_warning`). Blocked (`retire_blocker`) only while an active computed account lists it as an input. Retirement writes no row: the series ends at the last saved value.
- **Partial saves** (`carry_forward`) fill only from the latest snapshot *date*; an active plain account with no row there must be sent explicitly.
- **Same-day Save replaces** that day's rows. Retired accounts get no row.
- **Repository never commits**; the service layer does. `save_snapshot` uses `conn.transaction()`.
- **Workspace scoping**: a new table holding workspace data gets a `workspace_id` with a composite foreign key to its parent's `(workspace_id, id)`, and every repository function for it takes `workspace_id`. A new API route or page takes `ViewerAccess`/`EditorAccess`/`OwnerAccess`; a page renders with `**shell_context(request, access)` and links within its workspace through `{{ base }}`.
- **Drawers**: a form is a drawer over its page, rendered by its own route (no JS to open it). The template extends the page's template, fills `{% block drawer %}` and sets `drawer_open`; `base.html` makes the page `inert`, locks scrolling, closes on Escape (to `.drawer-close`'s href) and keeps the flash out of the page behind. Put the error in `form_error`, inside the drawer.
- **Mobile** (`docs/superpowers/specs/2026-10-26-mobile-design.md`): one breakpoint, `@media (max-width: 600px)`; desktop above it is unchanged. `--gutter` (24px, 16px on phones) is the side padding; `--tabbar-h` is the bottom tab bar's height on phones (0px elsewhere; it does not change while a field has focus, so nothing under a finger moves). Anything fixed to the bottom sits at `bottom: var(--tabbar-h)`. On phones `.main-nav` is the bottom tab bar (its icons are hidden on desktop), the workspace select is the title, and drawers are full-screen sheets. Tap targets 44px, fields 16px (iOS zooms below), hover styles under `@media (hover: hover)`. Pages adjust shared pieces from their own `{% block styles %}`.
- **Frontend tokens**: `base.html` defines every color as a CSS custom property for light and for dark (`prefers-color-scheme`); templates name tokens, never hex values (a test enforces it, `login.html` included). `login.html` extends `base.html` and empties its `shell_header` block, so a page outside any workspace gets the tokens without the header. Design: `docs/superpowers/specs/2026-10-26-frontend-redesign-design.md`.
- **Roles**: viewer reads; editor also changes data; owner also manages the workspace and members. A workspace always keeps at least one owner. Anyone may leave (`DELETE .../members/{self}`) except the last owner.
- **Today is the viewer's day.** Snapshot dates and `retired_at` use the zone of the person acting (`Today` in `web/viewer_zone.py`), never `date.today()` (pods run in UTC) and never a per-workspace setting. They stay calendar dates, not timestamps. The very first page load has no cookie yet and uses `TIMEZONE`.
- **Latest snapshot date is per workspace.** Never compute `MAX(date)` over all snapshots.
- **Admin**: `users.is_admin`, set only by the migration on the pre-provisioned `ethanpswan@gmail.com` row. Grants nothing yet; it does not bypass workspace membership.
- **Categories** group rows under subheadings on `/accounts` (enum order, Uncategorized last, empty groups hidden). Any category may be used on either type. Adding one means a value in `AccountCategory` *and* a migration widening the CHECK constraint.
- **Adding a formula kind** later: one Pydantic class in `models.py` (make `Formula` a discriminated union on `kind`), one branch in `formulas._evaluate`, one form variant. No migration.
