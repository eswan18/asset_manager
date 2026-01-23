"""CLI for asset_manager using Typer."""
from __future__ import annotations

import typer

from . import __version__
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
def version() -> None:
    """Show the version and exit."""
    typer.echo(f"asset-manager {__version__}")


def main() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
