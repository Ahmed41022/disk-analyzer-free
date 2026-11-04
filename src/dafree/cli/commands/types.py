"""Group scanned files by extension."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import click

from dafree import api
from dafree.cli.output import write_analysis

if TYPE_CHECKING:
    from dafree.cli.main import CliState

_COLUMNS = (
    ("ext", "Extension"),
    ("files", "Files"),
    ("size", "Size"),
    ("alloc", "Alloc"),
    ("category", "Category"),
)


@click.command("types")
@click.argument("path", type=click.Path(path_type=Path))
@click.option("-n", type=click.IntRange(1), default=30, show_default=True)
@click.option("--by", type=click.Choice(["size", "count"]), default="size", show_default=True)
@click.pass_obj
def types_command(state: CliState, path: Path, n: int, by: str) -> None:
    """Summarize file types below PATH."""
    tree = api.scan(api.ScanRequest([path], threads=state.threads)).tree
    stats = api.ext_breakdown(tree)
    if by == "count":
        stats.sort(key=lambda row: (-row.files, row.ext))
    rows: list[dict[str, str | int]] = [
        {
            "ext": row.ext,
            "files": row.files,
            "size": row.size,
            "alloc": row.alloc,
            "category": row.category.name.lower(),
        }
        for row in stats[:n]
    ]
    write_analysis(state, _COLUMNS, rows)
