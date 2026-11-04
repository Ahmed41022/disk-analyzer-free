"""Typed public facade over the native core."""

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from enum import IntEnum

from dafree import _core
from dafree.api.analysis import (
    AgeBucket,
    AgeStat,
    ExtStat,
    TopKind,
    age_histogram,
    default_age_buckets,
    ext_breakdown,
    top_n,
)
from dafree.api.errors import (
    Cancelled,
    DafreeError,
    ExcludeError,
    ScanError,
    ScanErrorCode,
    Unsupported,
)
from dafree.api.export import write_csv, write_json
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
    _volume,
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


class platform:
    """Native host services with typed errors for unavailable operations."""

    @staticmethod
    def volumes() -> list[VolumeInfo]:
        """Copy native mounted-volume metadata without enumerating user files."""
        return [_volume(value) for value in _core.platform.volumes()]

    @staticmethod
    def peak_rss() -> int:
        """Return the peak process resident set size in bytes."""
        if sys.platform == "win32":
            value = _core.platform.peak_rss()
            if value is None:
                raise Unsupported("Peak process memory is unavailable")
            return value

        import resource  # noqa: PLC0415 -- unavailable on Windows

        maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return maxrss if sys.platform == "darwin" else maxrss * 1024

    @staticmethod
    def is_elevated() -> bool:
        """Return the process privilege level, or raise Unsupported if it cannot be queried."""
        return _core.platform.is_elevated()

    @staticmethod
    def relaunch_elevated(args: Sequence[str]) -> None:
        """Relaunch the current executable with explicit arguments, excluding its name.

        Windows requests consent and raises Cancelled if the user declines. POSIX
        raises Unsupported. The caller controls when to exit the original process.
        """
        _core.platform.relaunch_elevated(list(args))


__all__ = [
    "AgeBucket",
    "AgeStat",
    "Backend",
    "Cancelled",
    "Cmp64",
    "CmpOp",
    "DafreeError",
    "EntryKind",
    "ExcludeError",
    "ExcludeRules",
    "ExtCategory",
    "ExtStat",
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
    "TopKind",
    "Tree",
    "TreeView",
    "UnitMode",
    "UnitStyle",
    "UnitSystem",
    "Unsupported",
    "ViewOptions",
    "VolumeInfo",
    "__version__",
    "age_histogram",
    "default_age_buckets",
    "ext_breakdown",
    "format_size",
    "parse_size",
    "platform",
    "scan",
    "start_scan",
    "top_n",
    "write_csv",
    "write_json",
]
