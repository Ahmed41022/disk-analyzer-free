"""Command line entry point for Disk Analyzer Free."""

import click

from dafree import __version__
from dafree.cli.commands.config import config_command


@click.group()
@click.version_option(version=__version__, prog_name="dafree")
def cli() -> None:
    """Inspect disk usage from the command line or desktop interface."""


@cli.command("gui")
def gui_command() -> None:
    """Launch the desktop interface."""
    try:
        # Keep the optional Qt dependency out of CLI startup unless requested.
        from dafree.gui.app import main  # noqa: PLC0415

        exit_code = main()
    except ImportError as error:
        raise click.UsageError(
            'GUI dependencies are not installed. Install "disk-analyzer-free[gui]".'
        ) from error

    click.get_current_context().exit(exit_code)


cli.add_command(config_command)
