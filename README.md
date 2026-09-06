# Asset Manager

[![CI Status](https://github.com/eswan18/asset_manager/workflows/Continuous%20Integration/badge.svg)](https://github.com/eswan18/asset_manager/actions)

A Python application for tracking personal financial assets and liabilities. Values are entered on the web dashboard's Accounts tab and saved as dated snapshots in PostgreSQL. Liabilities such as deferred tax can be computed from other accounts by a formula. A legacy `fetch` command still imports from a Google Sheet during the cutover.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) for Python dependency management
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
   GOOGLE_APPLICATION_CREDENTIALS=credentials/your-service-account.json

   # For web dashboard (optional)
   IDP_URL=https://your-idp.example.com
   CLIENT_ID=your-oauth-client-id
   CLIENT_SECRET=your-oauth-client-secret
   SECRET_KEY=random-secret-for-session-signing
   ALLOWED_EMAILS=you@example.com   # optional; comma-separated allowlist for login
   ```

3. Run database migrations:
   ```bash
   uv run dotenv -f .env.dev run dbmate up
   ```

## Usage

### Enter values on the Accounts tab

Run the dashboard (below), open **Accounts**, type current amounts, and click **Save snapshot**. Every active account is written for today; saving again the same day replaces that day's snapshot.

- **Add** an asset or liability from the table header. A liability can be **computed**: `rate × (sum of chosen input accounts − cost basis)`. Cost basis is editable inline on the Accounts tab; rate and inputs live on the account's edit page.
- **Retire** an account from its edit page once its latest saved amount is zero and no computed account uses it as an input. History is kept; retired accounts are hidden behind a toggle and can be unretired.

### Import from Google Sheets (legacy)

Still works during the cutover. Rows are matched to accounts by name; unknown names create plain accounts and retired accounts are skipped.
```bash
ENV=dev uv run asset-manager fetch            # writes today's snapshot
ENV=dev uv run asset-manager fetch --dry-run  # shows what would be created or skipped
```

### Generate HTML Report

Create an interactive HTML report with Plotly charts:
```bash
ENV=dev uv run asset-manager report                    # Opens in browser
ENV=dev uv run asset-manager report --output report.html --no-open
```

### Run Web Dashboard

Start the local development server:
```bash
ENV=dev uv run asset-manager serve
ENV=dev uv run asset-manager serve --port 8080
```

The dashboard requires OAuth configuration (IDP_URL, CLIENT_ID, CLIENT_SECRET, SECRET_KEY).

### CLI Commands

```bash
# Show help
uv run asset-manager --help

# Fetch data from Google Sheets
ENV=dev uv run asset-manager fetch

# Generate interactive HTML report
ENV=dev uv run asset-manager report

# Run web dashboard locally
ENV=dev uv run asset-manager serve

# Show version
uv run asset-manager version
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
uv run pytest --cov=asset_manager

# Type checking
uv run ty check src/asset_manager

# Linting
uv run ruff check src tests

# Formatting
uv run ruff format src tests
```
