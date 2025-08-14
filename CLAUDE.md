# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Asset Manager is a Python application for tracking personal financial assets and liabilities by fetching data from Google Sheets and storing it in AWS S3. The system generates daily snapshots and provides visualization capabilities through Jupyter notebooks.

## Development Setup

This project uses uv for dependency management. To set up the development environment:

```bash
uv sync --extra dev
```

## Common Commands

### Data Operations
- **Fetch data from Google Sheets**: `GOOGLE_APPLICATION_CREDENTIALS="credentials/asset-manager-369122-7861d911d7b5.json" uv run python -m asset_manager.fetch`
- **Consolidate yearly data**: `uv run python scripts/consolidate_by_year.py <year>`

### Development Commands
- **Run tests**: `uv run pytest`
- **Run tests with coverage**: `uv run pytest --cov=asset_manager`
- **Type checking**: `uv run mypy asset_manager`
- **Linting**: `uv run flake8 asset_manager`
- **Code formatting**: `uv run black asset_manager`

## Architecture

### Core Modules

- **`fetch.py`**: Main data fetching module that connects to Google Sheets API using service account credentials, extracts asset/liability data, and saves to S3
- **`s3.py`**: AWS S3 wrapper providing read/write operations for storing CSV data
- **`datastore.py`**: Data access layer that abstracts S3 operations and handles both daily and yearly data consolidation
- **`clean.py`**: Data cleaning utilities for processing raw spreadsheet data (removing blank rows, converting dollar strings to floats)
- **`dashboard.py`**: Altair-based chart generation for financial data visualization

### Data Flow

1. Google Sheets contains asset/liability data in a specific format (columns 0-3 for assets, 4-6 for liabilities)
2. `fetch.py` extracts data using Google Sheets API and service account authentication
3. Data is cleaned and transformed into DataFrames with Type (asset/liability) and Date columns
4. Daily snapshots are saved as CSV files in S3 with naming pattern `summaries_YYYY_MM_DD.csv`
5. Yearly consolidation scripts can merge daily files into `summaries_YYYY.csv` format
6. `datastore.py` provides unified access to both daily and yearly data
7. Jupyter notebook `Charts.ipynb` visualizes the data using charts from `dashboard.py`

### Configuration

- **`data/config.ini`**: Contains Google Sheets ID, S3 bucket name, and sheet range
- **Environment variables**: `GOOGLE_APPLICATION_CREDENTIALS` must point to service account JSON file
- **uv dependencies**: Defined in `pyproject.toml` with separate dev dependencies for testing and type checking

### Testing

Tests are organized by module with pytest:
- `test_clean.py`: Data cleaning function tests
- `test_fetch.py`: Google Sheets fetching tests (requires `GOOGLE_APPLICATION_CREDENTIALS` or set `CI=true` to skip)
- `test_s3.py`: S3 operations tests

The project uses hypothesis for property-based testing and includes type stubs for external libraries. To run tests in CI environment without Google credentials, use `CI=true uv run pytest`.