"""Native accounting reports over a completed scan tree."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum, IntEnum
from time import time

from dafree import _core
from dafree.api.tree import Tree
from dafree.api.types import ExtCategory, TimeField
from dafree.api.view import SortKey
from dafree.i18n import N_, _

_DAY = 86_400


class TopKind(IntEnum):
    """Select files or directories for a largest-items report."""

    FILES = 0
    DIRS = 1


class ChartKind(Enum):
    """Select a direct-child, extension, or file-category chart report."""

    CHILDREN_BY_SIZE = "children_by_size"
    CHILDREN_BY_ALLOC = "children_by_alloc"
    CHILDREN_BY_FILES = "children_by_files"
    EXT_BY_SIZE = "ext_by_size"
    EXT_BY_COUNT = "ext_by_count"
    CATEGORY_BY_SIZE = "category_by_size"


@dataclass(frozen=True)
class ChartSlice:
    """One immutable chart value; ``node`` identifies selectable child slices."""

    label: str
    value: int
    node: int | None = None
    is_other: bool = False


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


_CATEGORY_LABELS = {
    ExtCategory.IMAGE: N_("Images"),
    ExtCategory.VIDEO: N_("Videos"),
    ExtCategory.AUDIO: N_("Audio"),
    ExtCategory.ARCHIVE: N_("Archives"),
    ExtCategory.DOCUMENT: N_("Documents"),
    ExtCategory.CODE: N_("Code"),
    ExtCategory.EXECUTABLE: N_("Executables"),
    ExtCategory.DISK_IMAGE: N_("Disk images"),
    ExtCategory.SYSTEM: N_("System files"),
    ExtCategory.OTHER: N_("Other file types"),
}


def chart_data(tree: Tree, scope: int, kind: ChartKind, top: int = 15) -> list[ChartSlice]:
    """Return nonzero chart slices, with at most ``top`` ranked rows plus Other.

    Child charts include only direct children. Byte remainders use the native core's
    saturated unsigned-64-bit accounting for byte totals and merged remainder slices.
    ``top=0`` combines every positive value into an Other slice.
    """
    if top < 0:
        raise ValueError("top must be non-negative")
    node_id = tree._id(scope)
    if not isinstance(kind, ChartKind):
        raise TypeError("kind must be a ChartKind")

    fields = {
        ChartKind.CHILDREN_BY_SIZE: _core.ChildChartField.SIZE,
        ChartKind.CHILDREN_BY_ALLOC: _core.ChildChartField.ALLOC,
        ChartKind.CHILDREN_BY_FILES: _core.ChildChartField.FILES,
    }
    if kind in fields:
        rows = _core.child_chart_data(tree._native, node_id, fields[kind], top)
        slices = []
        for child in rows:
            if child.other:
                slices.append(ChartSlice(_("Other"), child.value, None, True))
            else:
                slices.append(ChartSlice(tree.name(child.node), child.value, child.node))
        return slices

    report = ext_breakdown(tree, node_id)
    if kind in (ChartKind.EXT_BY_SIZE, ChartKind.EXT_BY_COUNT):
        value_key = "size" if kind is ChartKind.EXT_BY_SIZE else "files"
        ranked_rows = sorted(
            ((row.ext, getattr(row, value_key)) for row in report),
            key=lambda item: (-item[1], item[0]),
        )
        ranked = [(f".{ext}" if ext else _("No extension"), value) for ext, value in ranked_rows]
    else:
        totals: dict[ExtCategory, int] = {}
        for row in report:
            totals[row.category] = min((1 << 64) - 1, totals.get(row.category, 0) + row.size)
        ranked_categories = sorted(
            (
                (_(_CATEGORY_LABELS[category]), value, category.value)
                for category, value in totals.items()
            ),
            key=lambda item: (-item[1], item[2]),
        )
        ranked = [(label, value) for label, value, _category_id in ranked_categories]
    ranked = [(label, value) for label, value in ranked if value > 0]
    selected = ranked[:top]
    slices = [ChartSlice(label, value) for label, value in selected]
    remainder = min((1 << 64) - 1, sum(value for _, value in ranked[top:]))
    if remainder:
        slices.append(ChartSlice(_("Other"), remainder, None, True))
    return slices


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
