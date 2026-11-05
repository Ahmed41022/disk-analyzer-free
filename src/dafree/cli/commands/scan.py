"""Scan filesystem targets and write a report to stdout."""

from __future__ import annotations

import json
import signal
import sys
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic, perf_counter_ns
from typing import TYPE_CHECKING

import click
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.text import Text

from dafree import api
from dafree.api.testing import MockEntry, MockSpec, make_mock_backend
from dafree.cli.exit_codes import Exit
from dafree.cli.progress import set_active_scan

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import FrameType

    from dafree.cli.main import CliState


def _middle_ellipsize(name: str, width: int = 56) -> str:
    if len(name) <= width:
        return name
    left = (width - 1) // 2
    return f"{name[:left]}…{name[-(width - left - 1) :]}"


def _rows(
    tree: api.Tree, depth: int, sort: str, ascending: bool, files: bool
) -> Iterator[tuple[int, api.NodeInfo]]:
    def sort_key(node: api.NodeInfo) -> int | str:
        match sort:
            case "alloc":
                return node.alloc
            case "files":
                return node.files
            case "dirs":
                return node.dirs
            case "name":
                return tree.name(node.id).casefold()
            case "mtime":
                return node.mtime if node.mtime is not None else -1
            case _:
                return node.size

    def visible(ids: list[int] | range) -> list[api.NodeInfo]:
        nodes = (tree.node(node_id) for node_id in ids)
        return sorted(
            (
                node
                for node in nodes
                if not node.flags & api.NodeFlags.EXCLUDED
                and (files or node.flags & api.NodeFlags.DIR)
            ),
            key=sort_key,
            reverse=not ascending,
        )

    stack = [(0, iter(visible(tree.roots())))]
    while stack:
        level, siblings = stack[-1]
        node = next(siblings, None)
        if node is None:
            stack.pop()
            continue
        yield level, node
        if level < depth:
            stack.append((level + 1, iter(visible(tree.children(node.id)))))


def _table(rows: Iterator[tuple[int, api.NodeInfo]], tree: api.Tree, state: CliState) -> None:
    table = Table(box=None)
    for title in ("Size", "Alloc", "%", "Files", "Dirs", "Modified", "Name"):
        table.add_column(title, justify="right" if title not in {"Modified", "Name"} else "left")
    for level, node in rows:
        parent_size = 0 if node.parent in (None, 0) else tree.node(node.parent).size
        fraction = node.size / parent_size if parent_size else 0.0
        filled = min(10, round(fraction * 10))
        bar = "#" * filled + "-" * (10 - filled)
        modified = "" if node.mtime is None else datetime.fromtimestamp(node.mtime, UTC).isoformat()
        name = tree.name(node.id).encode("utf-8", "replace").decode("utf-8")
        table.add_row(
            api.format_size(node.size, state.units, state.unit_style),
            api.format_size(node.alloc, state.units, state.unit_style),
            f"{fraction:5.0%} [{bar}]",
            str(node.files),
            str(node.dirs),
            modified,
            Text("  " * level + _middle_ellipsize(name)),
        )
    Console(no_color=not state.color, markup=False, highlight=False).print(table)


def _wait(ctx: click.Context, handle: api.ScanHandle, show_progress: bool) -> api.ScanResult:
    console = Console(file=sys.stderr)
    terminal = show_progress and console.is_terminal
    live = Live(console=console, auto_refresh=False) if terminal else nullcontext()
    next_update = 0.0

    def ctrl_break(_signum: int, _frame: FrameType | None) -> None:
        raise KeyboardInterrupt

    break_signal = getattr(signal, "SIGBREAK", None)
    previous = signal.signal(break_signal, ctrl_break) if break_signal is not None else None
    set_active_scan(ctx, handle)
    try:
        with live:
            while True:
                now = monotonic()
                if show_progress and now >= next_update:
                    progress = handle.progress()
                    line = Text(
                        f"Scanning · {progress.files:,} files · {progress.dirs:,} directories"
                        f" · {progress.issues:,} issues"
                    )
                    if isinstance(live, Live):
                        live.update(line, refresh=True)
                    else:
                        console.print(line)
                    next_update = now + (0.25 if terminal else 5)
                if handle.wait(100):
                    break
    except KeyboardInterrupt:
        handle.cancel()
        while not handle.wait(100):
            pass
    finally:
        set_active_scan(ctx, None)
        if break_signal is not None and previous is not None:
            signal.signal(break_signal, previous)
    for notice in handle.drain_notices():
        if notice.kind is api.NoticeKind.FAST_MODE_UNAVAILABLE:
            click.echo(f"FastModeUnavailable: {notice.detail}", err=True)
    return handle.take_result()


def _slow_backend(targets: tuple[Path, ...]) -> api.Backend:
    return make_mock_backend(
        MockSpec([MockEntry(path, api.EntryKind.DIR) for path in targets], delay_ms=1500)
    )


@click.command("scan")
@click.argument("paths", nargs=-1, required=True, type=click.Path(path_type=Path))
@click.option("--depth", type=click.IntRange(0, 65535), default=1, show_default=True)
@click.option(
    "--sort",
    type=click.Choice(["size", "alloc", "files", "dirs", "name", "mtime"]),
    default="size",
    show_default=True,
)
@click.option("--asc", is_flag=True)
@click.option("--files", is_flag=True)
@click.option("--exclude", multiple=True, metavar="GLOB")
@click.option("--exclude-path", multiple=True, type=click.Path(path_type=Path))
@click.option("--exclude-hidden", is_flag=True)
@click.option("--exclude-system", is_flag=True)
@click.option("--follow-symlinks", is_flag=True)
@click.option("--cross-fs", is_flag=True)
@click.option(
    "--mode", type=click.Choice(["auto", "walk", "mft"]), default="auto", show_default=True
)
@click.option(
    "--hardlinks", type=click.Choice(["dedup", "count-all"]), default="dedup", show_default=True
)
@click.option(
    "--owner", type=click.Choice(["off", "lazy", "eager"]), default="lazy", show_default=True
)
@click.option("--include-ads", is_flag=True)
@click.option("--stats-json", type=click.Path(dir_okay=False, path_type=Path), metavar="FILE")
@click.option("--strict", is_flag=True)
@click.option("--test-slow-backend", is_flag=True, hidden=True)
@click.pass_context
def scan_command(  # noqa: PLR0913 -- Click supplies independent scan options.
    ctx: click.Context,
    *,
    paths: tuple[Path, ...],
    depth: int,
    sort: str,
    asc: bool,
    files: bool,
    exclude: tuple[str, ...],
    exclude_path: tuple[Path, ...],
    exclude_hidden: bool,
    exclude_system: bool,
    follow_symlinks: bool,
    cross_fs: bool,
    mode: str,
    hardlinks: str,
    owner: str,
    include_ads: bool,
    stats_json: Path | None,
    strict: bool,
    test_slow_backend: bool,
) -> None:
    """Scan one or more paths and report their disk usage."""
    state: CliState = ctx.obj
    request = api.ScanRequest(
        paths,
        mode=api.ScanMode[mode.upper()],
        threads=state.threads,
        follow_symlinks=follow_symlinks,
        cross_filesystems=cross_fs,
        exclude=api.ExcludeRules(exclude_path, exclude, exclude_hidden, exclude_system),
        owner=api.OwnerMode[owner.upper()],
        hardlinks=api.HardlinkMode[hardlinks.upper().replace("-", "_")],
        include_ads=include_ads,
    )
    backend = _slow_backend(paths) if test_slow_backend else None
    stderr = sys.stderr
    show_progress = state.progress == "always" or (
        state.progress == "auto" and state.verbosity >= 0 and stderr.isatty()
    )
    started = perf_counter_ns()
    result = _wait(ctx, api.start_scan(request, backend=backend), show_progress)
    tree = result.tree
    try:
        if state.format == "table":
            _table(_rows(tree, depth, sort, asc, files), tree, state)
        else:
            stream = sys.stdout.buffer
            if state.format == "csv":
                api.write_csv(
                    tree, stream, depth=depth, include_files=files, include_owner=owner == "eager"
                )
            else:
                api.write_json(
                    tree,
                    stream,
                    depth=depth,
                    include_files=files,
                    ndjson=state.format == "ndjson",
                    include_owner=owner == "eager",
                )
            stream.flush()
        if stats_json is not None:
            stats = {
                "wall_ms": (perf_counter_ns() - started) / 1_000_000,
                "peak_rss_bytes": api.platform.peak_rss(),
                "nodes": len(tree) - 1,
                "mode": tree.meta().mode.name.lower(),
            }
            with stats_json.open("x", encoding="utf-8") as stats_file:
                json.dump(stats, stats_file)
                stats_file.write("\n")
    except OSError as error:
        raise click.ClickException(str(error)) from error

    if result.summary.cancelled:
        ctx.exit(Exit.INTERRUPTED)
    if strict and result.summary.issues.counts[api.IssueKind.ACCESS_DENIED]:
        ctx.exit(Exit.PARTIAL)
