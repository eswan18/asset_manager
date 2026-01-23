# Asset Manager

[![CI Status](https://github.com/eswan18/asset_manager/workflows/Continuous%20Integration/badge.svg)](https://github.com/eswan18/asset_manager/actions)

A Python application for tracking personal financial assets and liabilities by fetching data from Google Sheets and storing it in PostgreSQL. Includes interactive reports and a web dashboard with OAuth authentication.

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
   ```

3. Run database migrations:
   ```bash
   uv run dotenv -f .env.dev run dbmate up
   ```

## Usage

### Fetch data from Google Sheets

Pull finances from Google Sheets and store in PostgreSQL:
```bash
ENV=dev uv run asset-manager fetch
ENV=prod uv run asset-manager fetch
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

## Deployment

The web dashboard can be deployed to Vercel as a Python serverless function:

1. Register an OAuth client with your IDP
2. Set environment variables in Vercel (DATABASE_URL, IDP_URL, CLIENT_ID, CLIENT_SECRET, SECRET_KEY)
3. Deploy with `vercel deploy`

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
