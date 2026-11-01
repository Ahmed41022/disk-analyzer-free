"""Typed public facade over the native core."""

from dataclasses import dataclass
from enum import IntEnum

from dafree import _core
from dafree.api.errors import DafreeError, ExcludeError, ScanError, ScanErrorCode
from dafree.api.scan import ScanHandle, ScanResult, scan, start_scan
from dafree.api.tree import Tree
from dafree.api.types import (
    Backend,
    EntryKind,
    ExcludeRules,
    ExtCategory,
    HardlinkMode,
    IssueKind,
    IssueSummary,
    MemoryReport,
    NodeFlags,
    NodeInfo,
    Notice,
    NoticeKind,
    OwnerMode,
    ScanMeta,
    ScanMode,
    ScanModeUsed,
    ScanProgress,
    ScanRequest,
    ScanState,
    ScanSummary,
    TimeField,
    VolumeInfo,
)
from dafree.api.view import (
    Cmp64,
    CmpOp,
    FilterKind,
    FilterSpec,
    Row,
    SortKey,
    TreeView,
    ViewOptions,
)

__version__ = _core.version()


class UnitMode(IntEnum):
    """Select automatic scaling, bytes, or a fixed unit power."""

    AUTO = 0
    BYTES = 1
    KILO = 2
    MEGA = 3
    GIGA = 4
    TERA = 5
    PETA = 6
    EXA = 7


class UnitSystem(IntEnum):
    """Select traditional binary labels, IEC labels, or SI units."""

    TRADITIONAL = 0
    IEC = 1
    SI = 2


@dataclass(frozen=True)
class UnitStyle:
    """Choose a unit system and a locale supplied decimal separator."""

    system: UnitSystem = UnitSystem.TRADITIONAL
    decimal_separator: str = "."


_DEFAULT_STYLE = UnitStyle()


def _native_style(style: UnitStyle) -> _core.UnitStyle:
    if len(style.decimal_separator) != 1:
        raise ValueError("decimal separator must be one character")
    return _core.UnitStyle(_core.UnitSystem(style.system.value), style.decimal_separator)


def format_size(
    bytes_: int, mode: UnitMode = UnitMode.AUTO, style: UnitStyle = _DEFAULT_STYLE
) -> str:
    """Format a byte count with the requested scale and decimal separator."""
    if bytes_ < 0 or bytes_ > (1 << 64) - 1:
        raise ValueError("byte count must fit in an unsigned 64-bit integer")
    return _core.format_size(bytes_, _core.UnitMode(mode.value), _native_style(style))


def parse_size(text: str, style: UnitStyle = _DEFAULT_STYLE) -> int:
    """Parse a human readable byte count using the selected unit style."""
    return _core.parse_size(text, _native_style(style))


__all__ = [
    "Backend",
    "Cmp64",
    "CmpOp",
    "DafreeError",
    "EntryKind",
    "ExcludeError",
    "ExcludeRules",
    "ExtCategory",
    "FilterKind",
    "FilterSpec",
    "HardlinkMode",
    "IssueKind",
    "IssueSummary",
    "MemoryReport",
    "NodeFlags",
    "NodeInfo",
    "Notice",
    "NoticeKind",
    "OwnerMode",
    "Row",
    "ScanError",
    "ScanErrorCode",
    "ScanHandle",
    "ScanMeta",
    "ScanMode",
    "ScanModeUsed",
    "ScanProgress",
    "ScanRequest",
    "ScanResult",
    "ScanState",
    "ScanSummary",
    "SortKey",
    "TimeField",
    "Tree",
    "TreeView",
    "UnitMode",
    "UnitStyle",
    "UnitSystem",
    "ViewOptions",
    "VolumeInfo",
    "__version__",
    "format_size",
    "parse_size",
    "scan",
    "start_scan",
]
