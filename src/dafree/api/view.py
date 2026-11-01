"""Native sorting, expression filtering, and bounded windows of visible tree rows."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from dafree import _core
from dafree.api.tree import Tree
from dafree.api.types import TimeField


class SortKey(IntEnum):
    """Sibling sort keys; ties use natural name order and stable node IDs."""

    NAME = 0
    SIZE = 1
    ALLOC = 2
    PCT_PARENT = 3
    FILES = 4
    DIRS = 5
    MTIME = 6
    OWNER = 7
    EXT = 8


class CmpOp(IntEnum):
    """Unsigned numeric comparison operators."""

    LT = 0
    LE = 1
    EQ = 2
    GE = 3
    GT = 4


class FilterKind(IntEnum):
    """Predicates evaluated natively, with inexpensive AND terms first."""

    AND = 0
    OR = 1
    NOT = 2
    SIZE = 3
    ALLOC = 4
    EXT = 5
    NAME_GLOB = 6
    PATH_GLOB = 7
    REGEX = 8
    OWNER = 9
    TIME = 10
    TYPE = 11
    FILES = 12
    FLAG = 13


@dataclass(frozen=True)
class Cmp64:
    """Compare metadata against an unsigned 64-bit value."""

    op: CmpOp = CmpOp.LT
    v: int = 0


@dataclass(frozen=True)
class FilterSpec:
    """Filter expression, copied into C++; this API does not parse query text."""

    kind: FilterKind = FilterKind.AND
    children: tuple[FilterSpec, ...] = ()
    cmp: Cmp64 = Cmp64()
    time_field: TimeField = TimeField.MODIFIED
    values: tuple[str, ...] = ()
    regex: str = ""
    flag: int = 0
    type_dir: bool = False


@dataclass(frozen=True)
class ViewOptions:
    """Display policy; changing it retains the user's expanded paths."""

    sort: SortKey = SortKey.SIZE
    descending: bool = True
    dirs_first: bool = False
    show_files: bool = True
    filter: FilterSpec | None = None
    resolve_owner: bool = False


# Native bindings build these tuples directly, avoiding a Python object per node.
type Row = tuple[
    int, int, bool, bool, str, int, int, float, int, int, int, str | None, str | None, int, int
]

_MAX_FILTER_DEPTH = 32
_DEFAULT_OPTIONS = ViewOptions()


def _native_filter(value: FilterSpec, depth: int = 0) -> _core.FilterSpec:
    if depth >= _MAX_FILTER_DEPTH:
        raise ValueError("filter expression exceeds 32 levels")
    if not 0 <= value.cmp.v < 1 << 64:
        raise ValueError("filter comparison must fit in an unsigned 64-bit integer")
    if not 0 <= value.flag < 1 << 16:
        raise ValueError("filter flag must fit in an unsigned 16-bit integer")
    if len(value.regex) > 1 << 20:
        raise ValueError("regex exceeds 1 MiB compile limit")
    native = _core.FilterSpec()
    native.kind = _core.FilterKind(value.kind.value)
    native.children = [_native_filter(child, depth + 1) for child in value.children]
    comparison = _core.Cmp64()
    comparison.op = _core.CmpOp(value.cmp.op.value)
    comparison.v = value.cmp.v
    native.cmp = comparison
    native.time_field = _core.TimeField(value.time_field.value)
    native.values = list(value.values)
    native.regex = value.regex
    native.flag = value.flag
    native.type_dir = value.type_dir
    return native


def _filter(value: _core.FilterSpec) -> FilterSpec:
    return FilterSpec(
        FilterKind(value.kind.value),
        tuple(_filter(child) for child in value.children),
        Cmp64(CmpOp(value.cmp.op.value), value.cmp.v),
        TimeField(value.time_field.value),
        tuple(value.values),
        value.regex,
        value.flag,
        value.type_dir,
    )


def _native_options(value: ViewOptions) -> _core.ViewOptions:
    native = _core.ViewOptions()
    native.sort = _core.SortKey(value.sort.value)
    native.descending = value.descending
    native.dirs_first = value.dirs_first
    native.show_files = value.show_files
    native.filter = _native_filter(value.filter) if value.filter is not None else None
    native.resolve_owner = value.resolve_owner
    return native


class TreeView:
    """Keep a native tree alive and retrieve visible rows without Python tree walks."""

    def __init__(self, tree: Tree, options: ViewOptions = _DEFAULT_OPTIONS) -> None:
        self._tree = tree
        self._node_count = len(tree)
        self._native = _core.TreeView(tree._native, _native_options(options))

    @property
    def tree(self) -> Tree:
        """Retain the source facade for individual path and parent lookups."""
        return self._tree

    @property
    def row_count(self) -> int:
        """Number of visible rows, excluding the synthetic root."""
        return self._native.row_count

    @property
    def options(self) -> ViewOptions:
        """Copy active options so changing sort preserves unrelated display policy."""
        native = self._native.options
        return ViewOptions(
            SortKey(native.sort.value),
            native.descending,
            native.dirs_first,
            native.show_files,
            _filter(native.filter) if native.filter is not None else None,
            native.resolve_owner,
        )

    def rows(self, start: int, count: int) -> list[Row]:
        """Return ≤500 tuples: id, depth, children, expanded, name, size, alloc, pct,
        files, dirs, mtime, owner, ext, flags, ext_cat. Unknown owners/extensions are None.
        """
        if start < 0 or count < 0:
            raise ValueError("row start and count must be nonnegative")
        if start >= 1 << 32:
            return []
        return self._native.rows(start, min(count, 500))

    def _id(self, node_id: int) -> int:
        if not 0 <= node_id < self._node_count:
            raise IndexError(node_id)
        return node_id

    def expand(self, node_id: int) -> int:
        """Expand a directory and return the number of inserted visible rows."""
        return self._native.expand(self._id(node_id))

    def collapse(self, node_id: int) -> int:
        """Collapse a directory and return the number of removed rows."""
        return self._native.collapse(self._id(node_id))

    def expansion_count(self, node_id: int) -> int:
        """Preview insertions before a GUI model announces its structural change."""
        return self._native.expansion_count(self._id(node_id))

    def collapse_count(self, node_id: int) -> int:
        """Preview removals without changing rows or expansion preferences."""
        return self._native.collapse_count(self._id(node_id))

    def expand_children(self, node_id: int) -> None:
        """Expand this directory and its immediate child directories in C++."""
        self._native.expand_children(self._id(node_id))

    def expand_to(self, node_id: int) -> int:
        """Expand ancestors and return the requested visible row index."""
        return self._native.expand_to(self._id(node_id))

    def index_of(self, node_id: int) -> int | None:
        """Return a visible index, or None when absent, filtered, or invalid."""
        if not 0 <= node_id < self._node_count:
            return None
        return self._native.index_of(node_id)

    def set_options(self, options: ViewOptions) -> None:
        """Apply a copied policy, preserving options and rows if validation fails."""
        self._native.set_options(_native_options(options))
