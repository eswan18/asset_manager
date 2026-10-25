"""Tests for the CLI module."""

from typer.testing import CliRunner

from asset_manager import __version__
from asset_manager.cli import app

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "fetch" not in result.stdout
    assert "report" in result.stdout
    assert "version" in result.stdout
