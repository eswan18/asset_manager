# Sensibility Money

[![CI Status](https://github.com/eswan18/sensibility/workflows/Continuous%20Integration/badge.svg)](https://github.com/eswan18/sensibility/actions)

Sensibility (in full, Sensibility Money) is a Python application for tracking personal financial assets and liabilities. Values are entered on the web dashboard's Accounts tab and saved as dated snapshots in PostgreSQL. Liabilities such as deferred tax can be computed from other accounts by a formula.

The web dashboard is a React app (`frontend/`, see its README) served by the FastAPI server, which also serves the JSON API it reads, the login flow and the MCP endpoint for agents.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) for Python dependency management
- [Node 24](https://nodejs.org/) and npm, to build the web dashboard
- [dbmate](https://github.com/amacneil/dbmate) for database migrations: `brew install dbmate`
- PostgreSQL database (local or hosted)

## Setup

1. Install Python dependencies:
   ```bash
   uv sync
   ```

2. Configure environment variables by copying the example file:
   ```bash
   cp .env.example .env.dev   # For development
   cp .env.example .env.prod  # For production
   ```

   Edit the `.env.dev` and `.env.prod` files with your credentials:
   ```
   DATABASE_URL=postgresql://user:password@host:5432/dbname

   # For web dashboard (optional)
   IDP_URL=https://your-idp.example.com
   CLIENT_ID=your-oauth-client-id
   CLIENT_SECRET=your-oauth-client-secret
   SECRET_KEY=random-secret-for-session-signing
   ALLOWED_EMAILS=you@example.com   # comma-separated allowlist; required outside ENV=dev
   TIMEZONE=America/Chicago   # optional; default zone for dating saves when the browser's is unknown
   ```

3. Run database migrations:
   ```bash
   uv run dotenv -f .env.dev run dbmate up
   ```

## Usage

### Enter values on the Accounts tab

Run the dashboard (below), open **Accounts**, type current amounts, and click **Save snapshot**. Every active account is written for today; saving again the same day replaces that day's snapshot.

- **Add** an asset or liability from the table header. A liability can be **computed**: `rate × (sum of chosen input accounts − cost basis)`. Cost basis is editable inline on the Accounts tab; rate and inputs live in the account's drawer.
- **Retire** an account from its drawer. If its last saved amount is not zero the page warns you and the button reads "Retire anyway"; from the next snapshot on it is no longer counted. The only hard rule: an account that feeds a computed account cannot be retired until that formula is edited or retired. History is kept; retired accounts are hidden behind a toggle and can be unretired.

### Generate HTML Report

Create an interactive HTML report with Plotly charts:
```bash
ENV=dev uv run sensibility report --workspace 1       # Opens in browser
ENV=dev uv run sensibility report --workspace 1 --output report.html --no-open
```

### Run Web Dashboard

Build the React app once, then start the server, which serves it at `/`:
```bash
cd frontend && npm ci && npm run build && cd ..
ENV=dev uv run sensibility serve
ENV=dev uv run sensibility serve --port 8080
```

For hot reload, run `npm run dev` in `frontend/` alongside the server and open Vite's port instead (`frontend/README.md`). The dashboard requires OAuth configuration (IDP_URL, CLIENT_ID, CLIENT_SECRET, SECRET_KEY).

### CLI Commands

```bash
# Show help
uv run sensibility --help

# Generate interactive HTML report
ENV=dev uv run sensibility report --workspace 1

# Run web dashboard locally
ENV=dev uv run sensibility serve

# Show version
uv run sensibility version
```

### Database Migrations

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

## Development

```bash
# Run tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=sensibility

# Type checking
uv run ty check src/sensibility

# Linting
uv run ruff check src tests

# Formatting
uv run ruff format src tests

# Browser tests (Playwright; builds frontend/ if needed)
uv run playwright install chromium   # once
uv run pytest -m browser

# The React app
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
```
