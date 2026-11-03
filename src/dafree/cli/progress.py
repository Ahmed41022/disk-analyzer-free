"""Keep interrupt handling independent of individual CLI commands."""

import sys
from typing import Protocol, cast

import click

_ACTIVE_SCAN = "dafree.active_scan"


class Cancellable(Protocol):
    """An active operation that accepts a cancellation request."""

    def cancel(self) -> None:
        """Request cancellation."""


def set_active_scan(ctx: click.Context, scan: Cancellable | None) -> None:
    """Register the current scan with the invocation, or clear it on completion."""
    if scan is None:
        ctx.meta.pop(_ACTIVE_SCAN, None)
    else:
        ctx.meta[_ACTIVE_SCAN] = scan


def interrupt(ctx: click.Context | None = None) -> None:
    """Cancel a registered scan once and flush output before exiting."""
    scan = None if ctx is None else cast("Cancellable | None", ctx.meta.pop(_ACTIVE_SCAN, None))
    try:
        if scan is not None:
            scan.cancel()
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
