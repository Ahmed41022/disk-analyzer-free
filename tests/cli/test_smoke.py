"""Command line startup tests."""

import builtins

import pytest
from click.testing import CliRunner

from dafree.cli.exit_codes import ExitCode
from dafree.cli.main import cli


def test_cli_version() -> None:
    """The CLI reports the installed package version."""
    result = CliRunner().invoke(cli, ["--version"])

    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_gui_command_reports_missing_optional_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    """The GUI command exits as a usage error with an install hint when Qt is absent."""
    original_import = builtins.__import__

    def import_without_qt(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith("PySide6"):
            raise ImportError("simulated missing optional Qt dependency")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_qt)
    result = CliRunner().invoke(cli, ["gui"])

    assert result.exit_code == ExitCode.USAGE
    assert "disk-analyzer-free[gui]" in result.output
