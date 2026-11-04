"""Rank the largest files or directories in a scan."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import click

from dafree import api
from dafree.cli.output import write_analysis

if TYPE_CHECKING:
    from dafree.cli.main import CliState

_COLUMNS = (("size", "Size"), ("alloc", "Alloc"), ("path", "Path"))


@click.command("top")
@click.argument("path", type=click.Path(path_type=Path))
@click.option("--kind", type=click.Choice(["files", "dirs"]), default="files", show_default=True)
@click.option("-n", type=click.IntRange(1), default=20, show_default=True)
@click.option(
    "--leaf-only", is_flag=True, help="Keep directories with no substantial subdirectory."
)
@click.pass_obj
def top_command(state: CliState, path: Path, kind: str, n: int, leaf_only: bool) -> None:
    """List the largest files or directories below PATH."""
    if leaf_only and kind != "dirs":
        raise click.UsageError("--leaf-only requires --kind dirs.")
    tree = api.scan(api.ScanRequest([path], threads=state.threads)).tree
    rows: list[dict[str, str | int]] = []
    for node_id in api.top_n(tree, kind=api.TopKind[kind.upper()], n=n, leaf_only=leaf_only):
        node = tree.node(node_id)
        rows.append({"size": node.size, "alloc": node.alloc, "path": tree.path(node_id)})
    write_analysis(state, _COLUMNS, rows)
