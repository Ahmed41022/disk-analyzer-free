"""Resolve stream output and color defaults for CLI commands."""

from __future__ import annotations

import csv
import io
import json
import os
import sys
from typing import TYPE_CHECKING, Literal

import click
from rich.console import Console
from rich.table import Table
from rich.text import Text

from dafree import api

if TYPE_CHECKING:
    from dafree.cli.main import CliState

type OutputFormat = Literal["table", "json", "ndjson", "csv"]


def output_format(requested: OutputFormat | None) -> OutputFormat:
    """Use the requested format or select table output for a terminal."""
    if requested is not None:
        return requested
    return "table" if sys.stdout.isatty() else "json"


def use_color(format_: OutputFormat, no_color: bool) -> bool:
    """Enable color only for table output on a terminal that permits it."""
    return (
        format_ == "table"
        and not no_color
        and not os.environ.get("NO_COLOR")
        and sys.stdout.isatty()
    )


def write_analysis(
    state: CliState,
    columns: tuple[tuple[str, str], ...],
    rows: list[dict[str, str | int]],
) -> None:
    """Render aggregate rows in the selected CLI format."""
    if state.format == "json":
        click.echo(json.dumps(rows, ensure_ascii=True))
        return
    if state.format == "ndjson":
        for row in rows:
            click.echo(json.dumps(row, ensure_ascii=True))
        return
    if state.format == "csv":
        keys = [key for key, _ in columns]
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
        sys.stdout.buffer.write(buffer.getvalue().encode("utf-8", "replace"))
        return

    table = Table(box=None)
    for key, title in columns:
        table.add_column(title, justify="right" if key in {"size", "alloc", "files"} else "left")
    for row in rows:
        cells = []
        for key, _ in columns:
            value = row[key]
            if isinstance(value, int) and key in {"size", "alloc"}:
                value = api.format_size(value, state.units, state.unit_style)
            display = str(value).encode("utf-8", "replace").decode("utf-8")
            cells.append(Text(display))
        table.add_row(*cells)
    Console(no_color=not state.color, markup=False, highlight=False).print(table)
