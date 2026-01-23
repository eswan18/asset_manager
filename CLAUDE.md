# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Asset Manager is a Python application for tracking personal financial assets and liabilities by fetching data from Google Sheets and storing it in PostgreSQL. The system generates daily snapshots and provides visualization capabilities through Jupyter notebooks.

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

1. **Apply migrations** to create the database schema:
   ```bash
   uv run dotenv -f .env.dev run dbmate up
   # Or for production:
   uv run dotenv -f .env.prod run dbmate up
   ```

2. **Migrate existing S3 data** (one-time, if you have historical data in S3):
   ```bash
   ENV=dev uv run python scripts/migrate_s3_to_postgres.py
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

### Data Operations
- **Fetch data from Google Sheets and save to database**:
  ```bash
  ENV=dev uv run python -m asset_manager.fetch
  ENV=prod uv run python -m asset_manager.fetch
  ```

### Development Commands
- **Run tests**: `uv run pytest`
- **Run tests with coverage**: `uv run pytest --cov=asset_manager`
- **Type checking**: `uv run ty check asset_manager`
- **Linting**: `uv run ruff check asset_manager`
- **Code formatting**: `uv run ruff format asset_manager`

## Architecture

### Core Modules

- **`config.py`**: Environment configuration using pydantic-settings, loads from `.env.{ENV}` files
- **`models.py`**: Pydantic models for `Record` and `DailySummary`
- **`db.py`**: Database connection management using psycopg3
- **`repository.py`**: Database query functions (insert, fetch, summarize)
- **`fetch.py`**: Main data fetching module that connects to Google Sheets API, extracts asset/liability data, and saves to PostgreSQL
- **`dashboard.py`**: Altair-based chart generation for financial data visualization
- **`s3.py`**: AWS S3 read-only wrapper (used only for migration script)

### Data Flow

1. Google Sheets contains asset/liability data in a specific format (columns 0-3 for assets, 4-6 for liabilities)
2. `fetch.py` extracts data using Google Sheets API and service account authentication
3. Data is cleaned and converted to Pydantic `Record` models
4. Records are inserted into PostgreSQL via `repository.py`
5. Jupyter notebook `Charts.ipynb` visualizes the data using charts from `dashboard.py`

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
- `test_fetch.py`: Google Sheets fetching and parsing tests
- `test_repository.py`: Database operations tests (uses testcontainers)
- `test_s3.py`: S3 operations tests

The project uses:
- **testcontainers**: Spins up real PostgreSQL containers for database tests
- **hypothesis**: Property-based testing
- Type stubs for external libraries

To run tests: `uv run pytest`
