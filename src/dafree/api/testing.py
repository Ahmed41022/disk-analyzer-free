"""Deterministic native backends for scanner tests and benchmarks."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dafree import _core
from dafree.api.tree import Tree
from dafree.api.types import Backend, EntryKind, IssueKind, _absolute


class TreeBuilder:
    """Construct large in-memory native fixtures without Python loops or MockBackend."""

    @staticmethod
    def flat(root: str | os.PathLike[str], visible_rows: int) -> Tree:
        """Build a target root and descending-size files, making exactly this many rows."""
        if not 1 <= visible_rows < (1 << 32) - 1:
            raise ValueError("visible row count must be between 1 and 4294967294")
        return Tree(_core.testing.TreeBuilder.flat(_absolute(root), visible_rows))


@dataclass
class MockEntry:
    """Synthetic entry metadata; zero inode IDs are assigned stable distinct IDs."""

    path: str | os.PathLike[str]
    kind: EntryKind = EntryKind.FILE
    size: int = 0
    alloc: int | None = None
    dev: int = 1
    ino_lo: int = 0
    ino_hi: int = 0
    nlink: int = 1
    owner_uid: int | None = None
    hidden: bool = False
    system: bool = False
    sparse: bool = False
    compressed: bool = False
    cloud: bool = False
    access_denied: bool = False


@dataclass
class MockSpec:
    """An immutable native filesystem is built from these copied inputs."""

    entries: list[MockEntry]
    errors: dict[str, IssueKind] = field(default_factory=dict)
    vanish_after_listing: list[str] = field(default_factory=list)
    delay_ms: int = 0
    symlink_targets: dict[str, str] = field(default_factory=dict)
    owner_names: dict[int, str] = field(default_factory=dict)


def make_mock_backend(spec: MockSpec) -> Backend:
    """Copy synthetic entries into a thread-safe C++ backend without Python callbacks."""
    native = _core.MockSpec()
    entries: list[_core.MockEntry] = []
    for value in spec.entries:
        raw = _core.RawEntry()
        raw.kind = _core.EntryKind(value.kind.value)
        raw.size, raw.alloc = value.size, value.size if value.alloc is None else value.alloc
        raw.dev, raw.ino_lo, raw.ino_hi, raw.nlink = (
            value.dev,
            value.ino_lo,
            value.ino_hi,
            value.nlink,
        )
        raw.owner_uid = value.owner_uid
        raw.hidden, raw.system, raw.sparse = value.hidden, value.system, value.sparse
        raw.compressed, raw.cloud = value.compressed, value.cloud
        raw.access_denied = value.access_denied
        entry = _core.MockEntry()
        entry.path, entry.entry = _absolute(value.path), raw
        entries.append(entry)
    native.entries = entries
    native.errors = {_absolute(p): _core.IssueKind(k.value) for p, k in spec.errors.items()}
    native.vanish_after_listing = list(map(_absolute, spec.vanish_after_listing))
    native.delay_ms = spec.delay_ms
    native.symlink_targets = {_absolute(p): _absolute(t) for p, t in spec.symlink_targets.items()}
    native.owner_names = spec.owner_names
    return Backend(_core.make_mock_backend(native))
