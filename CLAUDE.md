# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Asset Manager is a Python application for tracking personal financial assets and liabilities by fetching data from Google Sheets and storing it in PostgreSQL.

## Development Setup

This project uses uv for dependency management. To set up the development environment:

```bash
uv sync --extra dev
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
│       ├── sheets.py           # Google Sheets fetching
│       ├── py.typed            # PEP 561 marker
│       └── data/
│           └── config.ini      # Sheet ID and range
├── tests/
├── db/
│   └── migrations/
├── pyproject.toml
└── README.md
```

### Core Modules

- **`config.py`**: Environment configuration using pydantic-settings, loads from `.env.{ENV}` files
- **`models.py`**: Pydantic models for `Record` and `DailySummary`
- **`db.py`**: Database connection management using psycopg3
- **`repository.py`**: Database query functions (insert, fetch, summarize)
- **`sheets.py`**: Google Sheets API integration for fetching asset/liability data
- **`cli.py`**: Typer CLI with `fetch` and `version` commands

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

### Testing

Tests are organized by module with pytest:
- `test_sheets.py`: Google Sheets fetching and parsing tests
- `test_repository.py`: Database operations tests (uses testcontainers)
- `test_cli.py`: CLI command tests

The project uses:
- **testcontainers**: Spins up real PostgreSQL containers for database tests
- **hypothesis**: Property-based testing

To run tests: `uv run pytest`
