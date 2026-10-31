"""Asynchronous scanning and a blocking polling helper."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from dafree import _core
from dafree.api.tree import Tree
from dafree.api.types import (
    Backend,
    Notice,
    NoticeKind,
    ScanIssue,
    ScanProgress,
    ScanRequest,
    ScanSummary,
    _issue,
    _issues,
    _native_request,
    _progress,
)

__all__ = ["ScanHandle", "ScanRequest", "ScanResult", "scan", "start_scan"]


@dataclass(frozen=True)
class ScanResult:
    """A completed tree and its final summary."""

    tree: Tree
    summary: ScanSummary


class ScanHandle:
    """Control a scan whose native workers never call Python."""

    def __init__(self, native: _core.ScanHandle) -> None:
        self._native = native

    def progress(self) -> ScanProgress:
        """Return a non-blocking progress snapshot."""
        return _progress(self._native.progress())

    def drain_issues(self, max: int = 1000) -> list[ScanIssue]:
        """Consume up to max live diagnostics; retained totals are unaffected."""
        if max < 0:
            raise ValueError("max must be non-negative")
        return list(map(_issue, self._native.drain_issues(max)))

    def drain_notices(self) -> list[Notice]:
        """Consume policy and volume notices."""
        return [Notice(NoticeKind(v.kind.value), v.detail) for v in self._native.drain_notices()]

    def pause(self) -> None:
        """Pause between directory reads."""
        self._native.pause()

    def resume(self) -> None:
        """Resume directory reads."""
        self._native.resume()

    def cancel(self) -> None:
        """Request cancellation and retain a partial result."""
        self._native.cancel()

    def wait(self, timeout_ms: int) -> bool:
        """Wait at most timeout_ms with the GIL released; return completion status."""
        return self._native.wait(timeout_ms)

    def partial_tree(self) -> Tree | None:
        """Request a throttled immutable snapshot when available."""
        value = self._native.partial_tree()
        return None if value is None else Tree(value)

    def take_result(self) -> ScanResult:
        """Consume a completed result once; its tree outlives this handle."""
        result = self._native.take_result()
        value = result.summary
        return ScanResult(
            Tree(result.tree),
            ScanSummary(
                value.files,
                value.dirs,
                value.bytes,
                value.alloc,
                value.elapsed_ms,
                _issues(value.issues),
                value.cancelled,
            ),
        )


def start_scan(req: ScanRequest, *, backend: Backend | None = None) -> ScanHandle:
    """Copy a request and start scanning native paths without blocking Python workers."""
    return ScanHandle(
        _core.start_scan(_native_request(req), None if backend is None else backend._native)
    )


def scan(
    req: ScanRequest,
    *,
    on_progress: Callable[[ScanProgress], None] | None = None,
    poll_ms: int = 250,
    backend: Backend | None = None,
) -> ScanResult:
    """Poll to completion; invoke progress callbacks only on the calling Python thread."""
    if poll_ms <= 0:
        raise ValueError("poll_ms must be positive")
    handle = start_scan(req, backend=backend)
    try:
        while True:
            done = handle.wait(poll_ms)
            if on_progress is not None:
                on_progress(handle.progress())
            if done:
                return handle.take_result()
    except BaseException:
        handle.cancel()
        while not handle.wait(poll_ms):
            pass
        raise
