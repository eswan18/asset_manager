"""CLI for asset_manager using Typer."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv

from . import __version__
from .db import get_connection_context
from .report import generate_report
from .repository import get_all_records
from .sheets import fetch_and_save

app = typer.Typer(
    name="asset-manager",
    help="Track personal financial assets and liabilities.",
    no_args_is_help=True,
)


@app.command()
def fetch() -> None:
    """Fetch data from Google Sheets and save to the database."""
    try:
        count = fetch_and_save()
    except Exception as exc:
        typer.echo(f"Error fetching data: {exc}", err=True)
        raise typer.Exit(code=1)

    if count > 0:
        typer.echo(f"Successfully saved {count} records.")
    else:
        raise typer.Exit(code=1)


@app.command()
def report(
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Save report to this file path"),
    ] = None,
    no_open: Annotated[
        bool,
        typer.Option("--no-open", help="Don't open report in browser"),
    ] = False,
) -> None:
    """Generate an interactive HTML report of your finances."""
    try:
        with get_connection_context() as conn:
            records = get_all_records(conn)
    except Exception as exc:
        typer.echo(f"Error connecting to database: {exc}", err=True)
        raise typer.Exit(code=1)

    if not records:
        typer.echo("No records found in database.", err=True)
        raise typer.Exit(code=1)

    path = generate_report(records, output_path=output, open_browser=not no_open)
    typer.echo(f"Report generated: {path}")


@app.command()
def serve(
    port: Annotated[
        int,
        typer.Option("--port", "-p", help="Port to run the server on"),
    ] = 8000,
    host: Annotated[
        str,
        typer.Option("--host", "-h", help="Host to bind to"),
    ] = "127.0.0.1",
) -> None:
    """Run the web dashboard locally for development."""
    import uvicorn

    typer.echo(f"Starting dashboard at http://{host}:{port}")
    uvicorn.run(
        "asset_manager.web.app:app",
        host=host,
        port=port,
        reload=True,
    )


@app.command()
def version() -> None:
    """Show the version and exit."""
    typer.echo(f"asset-manager {__version__}")


def main() -> None:
    """Entry point for the CLI."""
    # Load environment file based on ENV variable
    env = os.environ.get("ENV")
    if env:
        env_file = Path(f".env.{env}")
        if env_file.exists():
            load_dotenv(env_file)
        else:
            typer.echo(f"Warning: {env_file} not found", err=True)
    else:
        # Fall back to .env if it exists
        load_dotenv()

    app()


if __name__ == "__main__":
    main()
