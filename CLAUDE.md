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
- **Run tests**: `uv run pytest`
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
│           ├── rendering.py    # Templates, render(), flash messages
│           └── templates/
│               ├── account_form.html  # Drawer over accounts.html (extends it)
│               ├── accounts.html
│               ├── _components.html  # Jinja macros for the shared pieces
│               ├── base.html   # Tokens, shell, shared drawer styles and Escape
│               ├── cash_flow_categories.html  # Categories drawer over cash_flows.html
│               ├── cash_flow_form.html  # Cash flow drawer over cash_flows.html
│               ├── cash_flows.html
│               ├── dashboard.html
│               └── login.html
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
- **`workspaces.py`**: `create_workspace` (creator becomes owner), `update_workspace` (name), `delete_workspace` (soft), `change_role`/`remove_member` (refuse to drop the last owner; lock the member rows `FOR UPDATE`). Raises `WorkspaceError`.
- **`invites.py`**: Owners invite an email with a role; expires after `INVITE_TTL` (14 days). Only the invited (verified) email can accept or decline; anything else is `InviteNotFound` (404), so ids reveal nothing. An invite lapses once its sender is no longer an owner. Invites never bypass `ALLOWED_EMAILS`. **No email is sent** yet; the invitee is told out of band and uses `GET /api/invites`.
- **`cashflows.py`**: Recurring income/expenses. `per_year(flow)` is signed (expenses negative) and divides once, at the end, so equivalent frequencies (2 weeks / 14 days, 12 months / 1 year) agree exactly; `rates()` rounds to cents; `totals()` sums unrounded and rounds once. `category_totals(flows, categories)` groups expenses by category (every category in `position` order, empty ones too, then Uncategorized if any; an unknown `category_id` counts as Uncategorized) and sums each unrounded, so they add up to `totals()`'s expenses exactly. Page helpers: `Period` (day/month/year) with `parse_period` (unknown values fall back to month), `in_period` (divide, round once), `share` (None when income is not positive, never a divide by zero), `percent_text`, `every_text` ("every month", "every 2 weeks"). Service: create/update/delete flows and per-workspace categories, and `move_category` (one place up or down; renumbers positions 0..n-1, so tied positions set through the API come out tidy); raises `CashFlowError`.
- **`clock.py`**: `now()` (tests monkeypatch it to freeze time), `today(tz)`, `is_known_zone`, `zone_for(explicit, cookie)` (explicit, else a known cookie zone, else `TIMEZONE`). Pure; no web imports
- **`users.py`**: `record_login(sub, email, name)`: match on `idp_sub`, else claim the unclaimed (pre-provisioned) row with this email, else insert. Callers must have checked the email is verified.
- **`db.py`**: Database connection management using psycopg3
- **`report.py`**: Interactive HTML report generation using Plotly
- **`cli.py`**: Typer CLI with `report`, `serve`, and `version` commands
- **`web/app.py`**: App wiring, dashboard (`/workspaces/{id}`, `?range=6m|1y|all`, default 1y), auth routes, and the bare-path redirects: `GET /` and `GET /accounts` go to the same page in your oldest live workspace (403 if you have none). `/docs`, `/redoc` and `/openapi.json` are public
- **`web/dashboard.py`**: Pure helpers over `get_all_records` + `get_accounts`. `change_since` compares the latest snapshot with the earlier one closest to 30 days before it (ties to the older; none earlier → no change line). `filter_range` counts back from the latest snapshot, not today. `latest_category_totals` reads the latest snapshot's rows (so the columns meet the lines' ends; a same-day-retired account still counts until the next save); `account_cards` lists only active accounts. Category colors go by size along the token ramps; past a ramp's end the last token fades toward `--surface` with `color-mix`
- **`web/charts.py`**: One Plotly figure, two x domains sharing one y-axis. Every trace names its color as a token in `meta`; the page's script resolves the tokens and calls `Plotly.react`, again on a `prefers-color-scheme` change. The hex values in `charts.py` are only light-theme fallbacks (page templates may not contain hex colors)
- **`web/accounts_routes.py`**: Accounts page, account form, `POST .../snapshots`, all under `/workspaces/{workspace_id}`. **A page's path is its API path without `/api`** (`/api/workspaces/1/accounts` is the data behind `/workspaces/1/accounts`). The account form (`.../accounts/new`, `.../accounts/{id}/edit`, and a POST's 400 re-render) is a **drawer over the Accounts page**: `account_form.html` extends `accounts.html`, both built from `accounts_view()`, and sets `drawer_open`, which makes `base.html` render the page behind `inert` and fill its `drawer` block. No JS needed to open or close it: Close, Cancel and Escape are links back to `.../accounts`. Its validation error is `form_error`, not `error` (`base.html` would show that behind the scrim). The drawer styles and the Escape handler live in `base.html`, shared with the Cash flows drawers
- **`web/cash_flows_routes.py`**: `GET /workspaces/{id}/cash-flows?per=day|month|year` (default month). `cash_flows_view` builds every figure: the net "left over", the "Where income goes" bar (100% = income; all expenses, scaled to their total, when they exceed income; empty when there is no income), the cards (Income, then expense categories that have flows, Uncategorized last), and `colors` (each expense category's color by id, for the drawers). Expense colors follow the liability ramp by size, largest strongest; past four, the rest share `--liability-4`. Two drawers over the page, as the account form is over Accounts, each keeping `?per=`: the **cash flow form** (`.../cash-flows/new?direction=&category_id=`, `.../cash-flows/{id}/edit`; POST `.../cash-flows`, `.../cash-flows/{id}`, `.../cash-flows/{id}/delete`, which redirect to the page with a flash) and **categories** (`GET .../cash-flow-categories?confirm={id}&add=1`; POST create, `/{id}` rename, `/{id}/move` with `direction=up|down`, `/{id}/delete`, which come back to the drawer and flash in its footer). Delete confirms in the row via `?confirm=`, so no JS is needed. `_parse_form` only turns the form's text into fields (plain digits, no exponents); every rule is the service's. `form_rates` gives the rates strip from `rates()`, so it matches the page; the drawer's script recomputes it exactly in BigInt cents. All drawer routes are editor-only (they exist to write); viewers see the page with no controls. The period toggle always links to the page itself
- **`web/api_routes.py`**: JSON API. `GET /api/me` (you + workspaces with roles); `GET /api/invites` (your pending invites), `POST /api/invites/{id}/accept|decline`; `POST /api/workspaces`; `GET/PATCH/DELETE /api/workspaces/{id}`; `/members` (list, `PATCH /{user_id}` role, `DELETE /{user_id}` remove or leave); `/invites` (owner: create, list pending, `DELETE /{invite_id}` revoke); `/cash-flows` (list with per-day/month/year and totals, create, `PATCH`, delete) and `/cash-flow-categories` (list, create, `PATCH` name/position, delete); `GET /accounts` (active accounts + latest amounts); `POST /snapshots` saves today's snapshot (today in the optional `X-Timezone` header's zone, else the `tz` cookie's, else `TIMEZONE`) with `carry_forward=True`, so omitted plain accounts keep their latest amount, and reports each account's `source` (`updated`/`carried_forward`/`computed`). Session auth for now; logged-out `/api/` requests always get 401. All errors are `{"error": ...}`
- **`web/viewer_zone.py`**: `Today`, a dependency giving today's date for the request; `today_for(request)` for shared helpers. Explicit `X-Timezone` header wins (unknown one: 400), else the `tz` cookie that `base.html` sets from `Intl.DateTimeFormat().resolvedOptions().timeZone` on every page load (unknown or missing: silently `TIMEZONE`)
- **`web/access.py`**: `ViewerAccess`/`EditorAccess`/`OwnerAccess` for API routes and pages with `{workspace_id}` in the path: **404** if you are not a live member (existence not revealed), **403** if your role is too low. `shell_context(access, path)` is what `base.html` needs on every page (user, workspace, picker links)
- **`web/auth.py`**: OAuth/OIDC with PKCE, `ALLOWED_EMAILS` gate. The callback requires `email_verified: true` (identity lets unverified accounts log in) and calls `record_login`; the session holds the user `id` and `sub`. `require_user` reloads the user from the database on every request and refuses a missing row, a mismatched `sub`, or an email no longer allowed

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
- `test_workspace_api.py`: Isolation sweep (a member of workspace 2 gets 404 on every workspace-1 route and changes nothing), role sweeps (exact 403 sets for viewer and editor), members, login

`conftest.py` seeds workspace `WS = 1` owned by user `USER_ID = 1` (`tests/support.py`) before every DB test; web helpers (sessions, `FakeIdp`, `sweep`, `add_user`, and `PAGES`, the seeded workspace's page prefix) live in `tests/web_support.py`. **New routes are swept automatically** (they come from the OpenAPI schema); the role sweeps compare exact 403 sets, so a new write route makes them fail until you decide its role.

The project uses:
- **testcontainers**: Spins up real PostgreSQL containers for database tests
- **hypothesis**: Property-based testing

To run tests: `uv run pytest`

### Rules worth knowing

- **Formula inputs must be plain, active accounts.** A computed account cannot feed another. An account that is an input cannot be made computed.
- **Retire flow**: Retire from the edit page at any amount; a non-zero last value only produces a warning (`retire_warning`). Blocked (`retire_blocker`) only while an active computed account lists it as an input. Retirement writes no row: the series ends at the last saved value.
- **Partial saves** (`carry_forward`) fill only from the latest snapshot *date*; an active plain account with no row there must be sent explicitly.
- **Same-day Save replaces** that day's rows. Retired accounts get no row.
- **Repository never commits**; the service layer does. `save_snapshot` uses `conn.transaction()`.
- **Workspace scoping**: a new table holding workspace data gets a `workspace_id` with a composite foreign key to its parent's `(workspace_id, id)`, and every repository function for it takes `workspace_id`. A new API route or page takes `ViewerAccess`/`EditorAccess`/`OwnerAccess`; a page renders with `**shell_context(access, request.url.path)` and links within its workspace through `{{ base }}`.
- **Drawers**: a form is a drawer over its page, rendered by its own route (no JS to open it). The template extends the page's template, fills `{% block drawer %}` and sets `drawer_open`; `base.html` makes the page `inert`, locks scrolling, closes on Escape (to `.drawer-close`'s href) and keeps the flash out of the page behind. Put the error in `form_error`, inside the drawer.
- **Frontend tokens**: `base.html` defines every color as a CSS custom property for light and for dark (`prefers-color-scheme`); templates name tokens, never hex values (a test enforces it). The old token names are aliased there until the pages using them are redesigned. Design: `docs/superpowers/specs/2026-10-26-frontend-redesign-design.md`.
- **Roles**: viewer reads; editor also changes data; owner also manages the workspace and members. A workspace always keeps at least one owner. Anyone may leave (`DELETE .../members/{self}`) except the last owner.
- **Today is the viewer's day.** Snapshot dates and `retired_at` use the zone of the person acting (`Today` in `web/viewer_zone.py`), never `date.today()` (pods run in UTC) and never a per-workspace setting. They stay calendar dates, not timestamps. The very first page load has no cookie yet and uses `TIMEZONE`.
- **Latest snapshot date is per workspace.** Never compute `MAX(date)` over all snapshots.
- **Admin**: `users.is_admin`, set only by the migration on the pre-provisioned `ethanpswan@gmail.com` row. Grants nothing yet; it does not bypass workspace membership.
- **Categories** group rows under subheadings on `/accounts` (enum order, Uncategorized last, empty groups hidden). Any category may be used on either type. Adding one means a value in `AccountCategory` *and* a migration widening the CHECK constraint.
- **Adding a formula kind** later: one Pydantic class in `models.py` (make `Formula` a discriminated union on `kind`), one branch in `formulas._evaluate`, one form variant. No migration.
