"""Command line entry point for Disk Analyzer Free."""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import click
from click.core import ParameterSource

from dafree import __version__, api, i18n
from dafree.cli.commands.config import config_command
from dafree.cli.exit_codes import Exit
from dafree.cli.output import OutputFormat, output_format, use_color
from dafree.cli.progress import interrupt
from dafree.paths import detect


@dataclass(frozen=True)
class CliState:
    """Resolved global options shared by commands in one invocation."""

    format: OutputFormat
    units: api.UnitMode
    unit_style: api.UnitStyle
    color: bool
    locale: str
    verbosity: int
    progress: Literal["auto", "always", "never"]
    threads: int
    config: Path | None
    portable: bool


_UNITS = dict(
    auto=api.UnitMode.AUTO,
    b=api.UnitMode.BYTES,
    kb=api.UnitMode.KILO,
    mb=api.UnitMode.MEGA,
    gb=api.UnitMode.GIGA,
    tb=api.UnitMode.TERA,
)


def _config_defaults(ctx: click.Context, param: click.Parameter, path: Path | None) -> Path | None:
    if path is None or ctx.resilient_parsing:
        return path
    try:
        with path.open("rb") as stream:
            values = tomllib.load(stream)
    except (OSError, ValueError) as error:
        raise click.BadParameter(str(error), ctx=ctx, param=param) from error
    options = {
        flag.removeprefix("--"): option.name
        for option in ctx.command.params
        if isinstance(option, click.Option) and not option.is_eager
        for flag in option.opts
        if flag.startswith("--") and option.name is not None
    }
    if unknown := values.keys() - options.keys():
        keys = ", ".join(sorted(unknown))
        raise click.BadParameter(f"unknown global option(s): {keys}", ctx=ctx, param=param)
    ctx.default_map = dict(ctx.default_map or {}) | {
        options[key]: value for key, value in values.items()
    }
    return path


class _CliGroup(click.Group):
    def invoke(self, ctx: click.Context) -> object:
        try:
            return super().invoke(ctx)
        except api.DafreeError as error:
            raise click.ClickException(str(error)) from error
        except KeyboardInterrupt:
            interrupt(ctx)
            ctx.exit(Exit.INTERRUPTED)


@click.group(cls=_CliGroup)
@click.version_option(version=__version__, prog_name="dafree")
@click.option("--format", "format_", type=click.Choice(["table", "json", "ndjson", "csv"]))
@click.option("--units", type=click.Choice(list(_UNITS)), default="auto", show_default=True)
@click.option("--si", is_flag=True, help="Use decimal SI units.")
@click.option("--iec-labels", is_flag=True, help="Use IEC binary unit labels.")
@click.option("--no-color", is_flag=True, help="Disable colored output.")
@click.option("--locale", metavar="TAG", help="Select an output locale.")
@click.option("-q", "--quiet", count=True, help="Decrease verbosity.")
@click.option("-v", "--verbose", count=True, help="Increase verbosity.")
@click.option(
    "--progress", type=click.Choice(["auto", "always", "never"]), default="auto", show_default=True
)
@click.option("--threads", type=click.IntRange(0), default=0, help="Worker count, or 0 for auto.")
@click.option(
    "--config",
    type=click.Path(dir_okay=False, path_type=Path),
    is_eager=True,
    callback=_config_defaults,
    help="Read global defaults from a TOML file.",
)
@click.option("--portable", is_flag=True, help="Request portable mode.")
@click.pass_context
def cli(  # noqa: PLR0913 -- Click supplies each declared global option by name.
    ctx: click.Context,
    *,
    format_: OutputFormat | None,
    units: str,
    si: bool,
    iec_labels: bool,
    no_color: bool,
    locale: str | None,
    quiet: int,
    verbose: int,
    progress: Literal["auto", "always", "never"],
    threads: int,
    config: Path | None,
    portable: bool,
) -> None:
    """Inspect disk usage from the command line or desktop interface."""
    if si and iec_labels:
        explicit_si = ctx.get_parameter_source("si") == ParameterSource.COMMANDLINE
        explicit_iec = ctx.get_parameter_source("iec_labels") == ParameterSource.COMMANDLINE
        if explicit_si == explicit_iec:
            raise click.UsageError("--si and --iec-labels cannot be combined.")
        si, iec_labels = explicit_si, explicit_iec
    if portable:
        try:
            detect(cli_flag=True)
        except NotImplementedError as error:
            raise click.UsageError(str(error)) from error
    selected_locale = i18n.setup(locale)
    resolved_format = output_format(format_)
    color = use_color(resolved_format, no_color)
    system = (
        api.UnitSystem.SI
        if si
        else api.UnitSystem.IEC
        if iec_labels
        else api.UnitSystem.TRADITIONAL
    )
    ctx.color = color
    ctx.obj = CliState(
        resolved_format,
        _UNITS[units],
        api.UnitStyle(system),
        color,
        selected_locale,
        verbose - quiet,
        progress,
        threads,
        config,
        portable,
    )


@cli.command("gui")
def gui_command() -> None:
    """Launch the desktop interface."""
    try:
        # Keep the optional Qt dependency out of CLI startup unless requested.
        from dafree.gui.app import main as gui_main  # noqa: PLC0415

        exit_code = gui_main([])
    except ImportError as error:
        raise click.UsageError(
            'GUI dependencies are not installed. Install "disk-analyzer-free[gui]".'
        ) from error

    click.get_current_context().exit(exit_code)


cli.add_command(config_command)


def main() -> int:
    """Run the command and preserve exit 130 even if interrupted during parsing."""
    try:
        return int(cli.main(standalone_mode=False) or Exit.OK)
    except click.ClickException as error:
        error.show()
        return error.exit_code
    except click.Abort as error:
        if isinstance(error.__cause__, KeyboardInterrupt):
            interrupt()
            return Exit.INTERRUPTED
        click.echo("Aborted!", err=True)
        return Exit.RUNTIME
