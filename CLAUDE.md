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
│       ├── workspaces.py       # Workspace and membership rules (last owner, time zones)
│       ├── users.py            # record_login: match/claim/create users at login
│       ├── formulas.py         # Pure formula evaluation (compute_snapshot)
│       ├── report.py           # Interactive HTML report generation
│       ├── py.typed            # PEP 561 marker
│       └── web/                # Web dashboard
│           ├── __init__.py
│           ├── app.py          # FastAPI application
│           ├── auth.py         # OAuth/OIDC authentication
│           ├── access.py       # Which workspace a request acts in; role checks
│           ├── accounts_routes.py  # Accounts page, account form, POST /snapshots
│           ├── api_routes.py   # JSON API: /api/me, /api/workspaces/...
│           ├── charts.py       # Plotly chart HTML for the dashboard
│           ├── rendering.py    # Templates, render(), flash messages
│           └── templates/
│               ├── account_form.html
│               ├── accounts.html
│               ├── base.html
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
- **`workspaces.py`**: `create_workspace` (creator becomes owner), `update_workspace` (name, time zone), `delete_workspace` (soft), `change_role`/`remove_member` (refuse to drop the last owner; lock the member rows `FOR UPDATE`). Raises `WorkspaceError`.
- **`users.py`**: `record_login(sub, email, name)`: match on `idp_sub`, else claim the unclaimed (pre-provisioned) row with this email, else insert. Callers must have checked the email is verified.
- **`db.py`**: Database connection management using psycopg3
- **`report.py`**: Interactive HTML report generation using Plotly
- **`cli.py`**: Typer CLI with `report`, `serve`, and `version` commands
- **`web/app.py`**: App wiring, dashboard, auth routes. `/docs`, `/redoc` and `/openapi.json` are public
- **`web/accounts_routes.py`**: Accounts page, account form, `POST /snapshots`. Pages act in the user's **oldest membership** (`PageViewer`/`PageEditor`) until the frontend gets a workspace switcher
- **`web/api_routes.py`**: JSON API. `GET /api/me` (you + workspaces with roles); `POST /api/workspaces`; `GET/PATCH/DELETE /api/workspaces/{id}`; `/members` (list, `PATCH /{user_id}` role, `DELETE /{user_id}` remove or leave); `GET /accounts` (active accounts + latest amounts); `POST /snapshots` saves today's snapshot with `carry_forward=True`, so omitted plain accounts keep their latest amount, and reports each account's `source` (`updated`/`carried_forward`/`computed`). Session auth for now; logged-out `/api/` requests always get 401. All errors are `{"error": ...}`
- **`web/access.py`**: `ViewerAccess`/`EditorAccess`/`OwnerAccess` for API routes with `{workspace_id}` in the path: **404** if you are not a live member (existence not revealed), **403** if your role is too low
- **`web/auth.py`**: OAuth/OIDC with PKCE, `ALLOWED_EMAILS` gate. The callback requires `email_verified: true` (identity lets unverified accounts log in) and calls `record_login`; the session holds the user `id` and `sub`. `require_user` reloads the user from the database on every request and refuses a missing row, a mismatched `sub`, or an email no longer allowed

### Data Flow

1. The user edits amounts on `/accounts`. Edits are staged in the page (and `sessionStorage`) until **Save snapshot**.
2. `POST /snapshots` sends `{values: {account_id: amount}, cost_bases: {account_id: basis}}`.
3. `accounts.save_snapshot` validates, updates cost bases, evaluates formulas via `formulas.compute_snapshot`, and upserts one `snapshots` row per active account for today, in the workspace's time zone. All in one transaction.
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
    timezone TEXT NOT NULL,     -- IANA; dates this workspace's snapshots and retirements
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
| `TIMEZONE` | Default IANA zone for **new** workspaces (default America/Chicago). Each workspace dates its own snapshots in `workspaces.timezone` |

### Testing

Tests are organized by module with pytest:
- `test_repository.py`: Database operations tests (uses testcontainers)
- `test_cli.py`: CLI command tests
- `test_models.py`, `test_formulas.py`: Pure unit tests (Hypothesis for the formula property)
- `test_accounts.py`: Service rules and the save transaction (testcontainers)
- `test_migration.py`: Applies migrations to legacy rows and checks the backfill and rollback; the workspaces migration also checks the database refuses rows crossing workspaces
- `test_users.py`, `test_workspaces.py`: Login matching/claiming; workspace rules, including a concurrency test for the last-owner lock
- `test_web.py`: FastAPI TestClient with a signed session cookie against the container, including the every-route login and allowlist sweeps
- `test_workspace_api.py`: Isolation sweep (a member of workspace 2 gets 404 on every workspace-1 route and changes nothing), role sweeps (exact 403 sets for viewer and editor), members, login

`conftest.py` seeds workspace `WS = 1` owned by user `USER_ID = 1` (`tests/support.py`) before every DB test; web helpers (sessions, `FakeIdp`, `sweep`, `add_user`) live in `tests/web_support.py`. **New routes are swept automatically** (they come from the OpenAPI schema); the role sweeps compare exact 403 sets, so a new write route makes them fail until you decide its role.

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
- **Workspace scoping**: a new table holding workspace data gets a `workspace_id` with a composite foreign key to its parent's `(workspace_id, id)`, and every repository function for it takes `workspace_id`. A new API route takes `ViewerAccess`/`EditorAccess`/`OwnerAccess`.
- **Roles**: viewer reads; editor also changes data; owner also manages the workspace and members. A workspace always keeps at least one owner. Anyone may leave (`DELETE .../members/{self}`) except the last owner.
- **Latest snapshot date is per workspace.** Never compute `MAX(date)` over all snapshots.
- **Admin**: `users.is_admin`, set only by the migration on the pre-provisioned `ethanpswan@gmail.com` row. Grants nothing yet; it does not bypass workspace membership.
- **Categories** group rows under subheadings on `/accounts` (enum order, Uncategorized last, empty groups hidden). Any category may be used on either type. Adding one means a value in `AccountCategory` *and* a migration widening the CHECK constraint.
- **Adding a formula kind** later: one Pydantic class in `models.py` (make `Formula` a discriminated union on `kind`), one branch in `formulas._evaluate`, one form variant. No migration.
