"""Read and update the shared preferences file."""

import json
from typing import Any

import click

from dafree.i18n import _
from dafree.paths import AppPaths, detect
from dafree.settings import _encode, get_dotted, load_settings, save_settings, set_dotted


@click.group("config", help=_("Read and update shared preferences."))
def config_command() -> None:
    """Group the settings commands without pulling forward T2.1 globals."""


def _failure(error: OSError | ValueError) -> click.ClickException:
    return click.ClickException(_("Cannot access preferences: {error}").format(error=error))


def _paths() -> AppPaths:
    try:
        return detect()
    except NotImplementedError as error:
        raise click.UsageError(str(error)) from error


@config_command.command("get", help=_("Print a setting as JSON."))
@click.argument("key")
def get_command(key: str) -> None:
    """Print a typed preference using its dotted field name."""
    try:
        settings = load_settings(_paths())
    except (OSError, ValueError) as error:
        raise _failure(error) from error
    try:
        value: Any = get_dotted(settings, key)
    except ValueError as error:
        raise click.UsageError(str(error)) from error
    click.echo(json.dumps(_encode(value), ensure_ascii=True, allow_nan=False))


@config_command.command("set", help=_("Validate and save a setting."))
@click.argument("key")
@click.argument("raw")
def set_command(key: str, raw: str) -> None:
    """Accept JSON scalars/containers or a bare string, then save atomically."""
    paths = _paths()
    try:
        settings = load_settings(paths)
    except (OSError, ValueError) as error:
        raise _failure(error) from error
    try:
        updated = set_dotted(settings, key, raw)
    except ValueError as error:
        raise click.UsageError(str(error)) from error
    try:
        save_settings(updated, paths)
    except OSError as error:
        raise _failure(error) from error


@config_command.command("path", help=_("Print the preferences file path."))
def path_command() -> None:
    """Show the selected settings path without creating directories."""
    click.echo(str(_paths().config / "settings.json"))
