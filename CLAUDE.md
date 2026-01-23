# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Asset Manager is a Python application for tracking personal financial assets and liabilities by fetching data from Google Sheets and storing it in PostgreSQL.

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
GOOGLE_APPLICATION_CREDENTIALS=credentials/asset-manager-369122-7861d911d7b5.json
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
# Fetch data from Google Sheets and save to database
ENV=dev uv run asset-manager fetch
ENV=prod uv run asset-manager fetch

# Generate interactive HTML report
ENV=dev uv run asset-manager report
ENV=dev uv run asset-manager report --output report.html --no-open

# Run web dashboard locally
ENV=dev uv run asset-manager serve
ENV=dev uv run asset-manager serve --port 8080

# Show version
uv run asset-manager version

# Or use python -m invocation
ENV=dev uv run python -m asset_manager fetch
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
│       ├── report.py           # Interactive HTML report generation
│       ├── sheets.py           # Google Sheets fetching
│       ├── py.typed            # PEP 561 marker
│       ├── data/
│       │   └── config.ini      # Sheet ID and range
│       └── web/                # Web dashboard
│           ├── __init__.py
│           ├── app.py          # FastAPI application
│           ├── auth.py         # OAuth/OIDC authentication
│           └── templates/
│               └── dashboard.html
├── tests/
├── db/
│   └── migrations/
├── pyproject.toml              # Includes Vercel app entrypoint
└── README.md
```

### Core Modules

- **`config.py`**: Environment configuration using pydantic-settings, loads from `.env.{ENV}` files
- **`models.py`**: Pydantic models for `Record` and `DailySummary`
- **`db.py`**: Database connection management using psycopg3
- **`repository.py`**: Database query functions (insert, fetch, summarize)
- **`sheets.py`**: Google Sheets API integration for fetching asset/liability data
- **`report.py`**: Interactive HTML report generation using Plotly
- **`cli.py`**: Typer CLI with `fetch`, `report`, `serve`, and `version` commands
- **`web/app.py`**: FastAPI web dashboard application
- **`web/auth.py`**: OAuth/OIDC authentication with PKCE support

### Data Flow

1. Google Sheets contains asset/liability data in a specific format (columns 0-3 for assets, 4-6 for liabilities)
2. `sheets.py` extracts data using Google Sheets API and service account authentication
3. Data is cleaned and converted to Pydantic `Record` models
4. Records are inserted into PostgreSQL via `repository.py`

### Database Schema

Migrations are managed by dbmate and stored in `db/migrations/`.

```sql
CREATE TABLE snapshots (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    type VARCHAR(10) NOT NULL CHECK (type IN ('asset', 'liability')),
    description TEXT NOT NULL,
    amount DECIMAL(15, 2) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Unique constraint prevents duplicate snapshots
CREATE UNIQUE INDEX idx_snapshots_unique ON snapshots(date, type, description);
```

### Configuration

- **`.env.dev` / `.env.prod`**: Database URL and Google credentials per environment
- **`data/config.ini`**: Contains Google Sheets ID and sheet range
- **Environment variable `ENV`**: Controls which `.env` file is loaded (default: `dev`)

#### Web Dashboard Environment Variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `IDP_URL` | OAuth identity provider URL (e.g., `https://identity.ethanswan.com`) |
| `CLIENT_ID` | OAuth client ID |
| `CLIENT_SECRET` | OAuth client secret |
| `SECRET_KEY` | Random secret for signing session cookies |
| `ENV` | Set to `dev` for local development (disables secure cookies)

### Testing

Tests are organized by module with pytest:
- `test_sheets.py`: Google Sheets fetching and parsing tests
- `test_repository.py`: Database operations tests (uses testcontainers)
- `test_cli.py`: CLI command tests

The project uses:
- **testcontainers**: Spins up real PostgreSQL containers for database tests
- **hypothesis**: Property-based testing

To run tests: `uv run pytest`
