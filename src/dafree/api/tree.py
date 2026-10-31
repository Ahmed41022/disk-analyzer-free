"""Shared tree access with copied metadata and lossless native paths."""

from __future__ import annotations

import os
from collections.abc import Sequence

from dafree import _core
from dafree.api.types import MemoryReport, NodeFlags, NodeInfo, ScanMeta, _absolute, _meta


class Tree:
    """Keep the native scan tree alive independently of its scan handle."""

    def __init__(self, native: _core.Tree) -> None:
        self._native = native

    def __len__(self) -> int:
        return len(self._native)

    def _id(self, node_id: int) -> int:
        if not 0 <= node_id < len(self):
            raise IndexError(node_id)
        return node_id

    def node(self, node_id: int) -> NodeInfo:
        """Copy node metadata and aggregate descendant counts."""
        value = self._native.node(self._id(node_id))
        return NodeInfo(
            value.id,
            value.parent,
            NodeFlags(value.flags),
            value.size,
            value.alloc,
            value.files,
            value.dirs,
            value.mtime,
            value.btime,
            value.atime,
            value.owner,
            value.ext,
        )

    def name(self, node_id: int) -> str:
        """Return the exact name, preserving undecodable bytes and lone surrogates."""
        return self._native.name(self._id(node_id))

    def path(self, node_id: int) -> str:
        """Reconstruct the exact native path."""
        return self._native.path(self._id(node_id))

    def children(self, node_id: int) -> range:
        """Return a contiguous range of direct child IDs."""
        start, end = self._native.children(self._id(node_id))
        return range(start, end)

    def parent(self, node_id: int) -> int | None:
        """Return the parent ID, or None for the synthetic root."""
        return self._native.parent(self._id(node_id))

    def roots(self) -> list[int]:
        """Return the target node IDs below the synthetic root."""
        return self._native.roots()

    def find_path(self, path: str | os.PathLike[str]) -> int | None:
        """Find an absolute or relative native path in the scan."""
        return self._native.find_path(_absolute(path))

    def meta(self) -> ScanMeta:
        """Copy scan provenance and retained diagnostics."""
        return _meta(self._native.meta())

    def memory_usage(self) -> MemoryReport:
        """Return reserved storage bytes owned by the tree."""
        value = self._native.memory_usage()
        return MemoryReport(value.nodes, value.counts, value.names, value.interners)

    def resolve_owners(self, ids: Sequence[int]) -> None:
        """Resolve requested identities; nodes sharing an identity share its cached name."""
        self._native.resolve_owners([self._id(node_id) for node_id in ids])
