# Asset Manager

[![CI Status](https://github.com/eswan18/asset_manager/workflows/Continuous%20Integration/badge.svg)](https://github.com/eswan18/asset_manager/actions)
[![codecov](https://codecov.io/gh/eswan18/asset_manager/branch/main/graph/badge.svg?token=JI0605RMSO)](https://codecov.io/gh/eswan18/asset_manager)

A Python application for tracking personal financial assets and liabilities by fetching data from Google Sheets and storing it in PostgreSQL.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) for Python dependency management
- [dbmate](https://github.com/amacneil/dbmate) for database migrations: `brew install dbmate`
- PostgreSQL database (local or hosted)

## Setup

1. Install Python dependencies:
   ```bash
   uv sync --extra dev
   ```

2. Configure environment variables by copying the example file:
   ```bash
   cp .env.example .env.dev   # For development
   cp .env.example .env.prod  # For production
   ```

   Edit the `.env.dev` and `.env.prod` files with your database credentials:
   ```
   DATABASE_URL=postgresql://user:password@host:5432/dbname
   GOOGLE_APPLICATION_CREDENTIALS=credentials/your-service-account.json
   ```

3. Run database migrations:
   ```bash
   uv run dotenv -f .env.dev run dbmate up
   ```

## Usage

### Fetch data from Google Sheets

Pull finances from Google Sheets and store in PostgreSQL:
```bash
ENV=dev uv run python -m asset_manager.fetch
ENV=prod uv run python -m asset_manager.fetch
```

### View finances

Open `Charts.ipynb` and run it to visualize your finances over time.

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

# Linting
uv run ruff check asset_manager

# Formatting
uv run ruff format asset_manager
```
