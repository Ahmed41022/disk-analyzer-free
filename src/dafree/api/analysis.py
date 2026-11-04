"""Native accounting reports over a completed scan tree."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import IntEnum
from time import time

from dafree import _core
from dafree.api.tree import Tree
from dafree.api.types import ExtCategory, TimeField
from dafree.api.view import SortKey
from dafree.i18n import _

_DAY = 86_400


class TopKind(IntEnum):
    """Select files or directories for a largest-items report."""

    FILES = 0
    DIRS = 1


@dataclass(frozen=True)
class ExtStat:
    """File counts and byte totals for one normalized extension."""

    ext: str
    files: int
    size: int
    alloc: int
    category: ExtCategory


@dataclass(frozen=True)
class AgeBucket:
    """A labeled interval with an exclusive upper limit in seconds."""

    label: str
    max_age_secs: int | None


@dataclass(frozen=True)
class AgeStat:
    """A labeled count and byte total for one age interval."""

    bucket: int
    label: str
    files: int
    size: int
    alloc: int


def default_age_buckets() -> tuple[AgeBucket, ...]:
    """Return localized default intervals, using 365 days for a year."""
    return (
        AgeBucket(_("<30d"), 30 * _DAY),
        AgeBucket(_("30–90d"), 90 * _DAY),  # noqa: RUF001 -- Deliberate range punctuation.
        AgeBucket(_("90–180d"), 180 * _DAY),  # noqa: RUF001 -- Deliberate range punctuation.
        AgeBucket(_("180d–1y"), 365 * _DAY),  # noqa: RUF001 -- Deliberate range punctuation.
        AgeBucket(_("1–2y"), 730 * _DAY),  # noqa: RUF001 -- Deliberate range punctuation.
        AgeBucket(_("2–5y"), 1825 * _DAY),  # noqa: RUF001 -- Deliberate range punctuation.
        AgeBucket(_(">5y"), None),
    )


def top_n(  # noqa: PLR0913 -- Mirror the independent native ranking options.
    tree: Tree,
    scope: int = 0,
    kind: TopKind = TopKind.FILES,
    n: int = 20,
    by: SortKey = SortKey.SIZE,
    *,
    leaf_only: bool = False,
) -> list[int]:
    """Return ranked node IDs below scope zero (all roots) or a selected node."""
    if n < 0:
        raise ValueError("top count must be non-negative")
    return _core.top_n(
        tree._native,
        tree._id(scope),
        _core.TopKind(kind.value),
        n,
        _core.SortKey(by.value),
        leaf_only,
    )


def ext_breakdown(tree: Tree, scope: int = 0) -> list[ExtStat]:
    """Return file totals by extension, ordered by descending logical size."""
    rows = _core.ext_breakdown(tree._native, tree._id(scope))
    return [
        ExtStat(row.ext, row.files, row.size, row.alloc, ExtCategory(row.category.value))
        for row in rows
    ]


def age_histogram(
    tree: Tree,
    scope: int = 0,
    field: TimeField = TimeField.MODIFIED,
    buckets: Sequence[AgeBucket] | None = None,
    now: int | None = None,
) -> list[AgeStat]:
    """Return age buckets and an extra localized row if timestamps are missing."""
    selected = default_age_buckets() if buckets is None else buckets
    clock = int(time()) if now is None else now
    if not 0 <= clock <= (1 << 32) - 1:
        raise ValueError("now must fit in an unsigned 32-bit timestamp")
    native = [_core.AgeBucket(item.label, item.max_age_secs) for item in selected]
    rows = _core.age_histogram(
        tree._native, tree._id(scope), _core.TimeField(field.value), native, clock
    )
    labels = [item.label for item in selected]
    labels.append(_("Unknown"))
    return [AgeStat(row.bucket, labels[row.bucket], row.files, row.size, row.alloc) for row in rows]
