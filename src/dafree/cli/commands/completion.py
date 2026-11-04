"""Generate shell registration scripts for the installed command."""

import click
from click.shell_completion import ShellComplete, get_completion_class

_SHELLS = ("bash", "zsh", "fish", "powershell")


@click.command("completion")
@click.argument("shell", type=click.Choice(_SHELLS))
@click.pass_context
def completion_command(ctx: click.Context, shell: str) -> None:
    """Write the completion script for SHELL to stdout."""
    implementation = get_completion_class(shell)
    if implementation is None:
        raise click.ClickException(f"Completion is unavailable for {shell}.")
    generator = implementation(ctx.find_root().command, {}, "dafree", "_DAFREE_COMPLETE")
    # Click's Bash override probes the current machine. Generation can target another host.
    source = ShellComplete.source(generator) if shell == "bash" else generator.source()
    click.echo(source.encode("utf-8"), nl=False)
