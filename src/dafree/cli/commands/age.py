"""Group scanned file totals by age."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import click

from dafree import api
from dafree.cli.output import write_analysis
from dafree.i18n import _

if TYPE_CHECKING:
    from dafree.cli.main import CliState

_COLUMNS = (("label", "Age"), ("files", "Files"), ("size", "Size"), ("alloc", "Alloc"))


def _buckets(spec: str | None) -> list[api.AgeBucket] | None:
    if spec is None:
        return None

    previous = ""
    previous_cutoff = 0
    buckets = []
    for item in map(str.strip, spec.split(",")):
        match = re.fullmatch(r"([1-9][0-9]*)([dy])", item, re.ASCII)
        if match is None:
            raise click.BadParameter("use positive intervals like 30d,1y", param_hint="--buckets")
        unit = 86_400 if match[2] == "d" else 365 * 86_400
        try:
            cutoff = int(match[1]) * unit
        except ValueError as error:
            raise click.BadParameter("duration is too large", param_hint="--buckets") from error
        if not previous_cutoff < cutoff < 1 << 64:
            raise click.BadParameter(
                "cutoffs must be strictly increasing and fit in 64 bits", param_hint="--buckets"
            )
        label = (
            _("{start}–{end}").format(start=previous, end=item)  # noqa: RUF001
            if previous
            else _("<{end}").format(end=item)
        )
        buckets.append(api.AgeBucket(label, cutoff))
        previous, previous_cutoff = item, cutoff
    buckets.append(api.AgeBucket(_("≥{start}").format(start=previous), None))
    return buckets


@click.command("age")
@click.argument("path", type=click.Path(path_type=Path))
@click.option(
    "--field",
    type=click.Choice(["modified", "created", "accessed"]),
    default="modified",
    show_default=True,
)
@click.option("--buckets", metavar="DURATIONS", help="Comma-separated cutoffs, such as 30d,1y.")
@click.option("--now", type=click.IntRange(0, (1 << 32) - 1), hidden=True)
@click.pass_obj
def age_command(
    state: CliState,
    path: Path,
    field: str,
    buckets: str | None,
    now: int | None,
) -> None:
    """Summarize the age of files below PATH."""
    intervals = _buckets(buckets)
    tree = api.scan(api.ScanRequest([path], threads=state.threads)).tree
    stats = api.age_histogram(tree, field=api.TimeField[field.upper()], buckets=intervals, now=now)
    rows: list[dict[str, str | int]] = [
        {"label": row.label, "files": row.files, "size": row.size, "alloc": row.alloc}
        for row in stats
    ]
    write_analysis(state, _COLUMNS, rows)
