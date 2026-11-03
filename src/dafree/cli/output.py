"""Resolve stream output and color defaults for CLI commands."""

import os
import sys
from typing import Literal

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
