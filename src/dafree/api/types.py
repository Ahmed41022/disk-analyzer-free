"""Public scan inputs and immutable result values."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import IntEnum, IntFlag

from dafree import _core


class ScanMode(IntEnum):
    """Requested enumeration strategy."""

    AUTO = 0
    WALK = 1
    MFT = 2


class OwnerMode(IntEnum):
    """Owner lookup policy."""

    OFF = 0
    LAZY = 1
    EAGER = 2


class HardlinkMode(IntEnum):
    """Byte accounting for additional hard links."""

    DEDUP = 0
    COUNT_ALL = 1


class ScanModeUsed(IntEnum):
    """Strategy actually used by a scan."""

    WALK = 0
    MFT = 1
    SFTP = 2


class ScanState(IntEnum):
    """Observable scan lifecycle."""

    RUNNING = 0
    PAUSED = 1
    FINALIZING = 2
    DONE = 3
    CANCELLED = 4
    FAILED = 5


class IssueKind(IntEnum):
    """Classification of a recoverable filesystem failure."""

    ACCESS_DENIED = 0
    NOT_FOUND = 1
    PATH_TOO_LONG = 2
    INVALID_NAME = 3
    IO = 4
    TIMEOUT = 5
    SYMLINK_LOOP = 6
    ORPHANED = 7
    CHANGED = 8
    OTHER = 9


class NoticeKind(IntEnum):
    """Informational volume or policy notice."""

    FAST_MODE_UNAVAILABLE = 0
    NETWORK_VOLUME = 1
    ROTATIONAL_DISK = 2
    HARDLINK_DEDUP_DISABLED = 3


class EntryKind(IntEnum):
    """Filesystem entry type in a synthetic backend."""

    FILE = 0
    DIR = 1
    SYMLINK = 2
    JUNCTION = 3
    MOUNT_POINT = 4
    OTHER_REPARSE = 5
    OTHER = 6


class NodeFlags(IntFlag):
    """Attributes and scan status retained on a tree node."""

    DIR = 1 << 0
    SYMLINK = 1 << 1
    REPARSE = 1 << 2
    MOUNT_POINT = 1 << 3
    HARDLINK_DUP = 1 << 4
    HIDDEN = 1 << 5
    SYSTEM = 1 << 6
    ACCESS_DENIED = 1 << 7
    PARTIAL = 1 << 8
    SPARSE = 1 << 9
    COMPRESSED = 1 << 10
    CLOUD_PLACEHOLDER = 1 << 11
    EXCLUDED = 1 << 12
    ERROR = 1 << 13
    ALLOC_UNRELIABLE = 1 << 14
    SYNTHETIC = 1 << 15


@dataclass
class ExcludeRules:
    """Paths, globs, and attributes excluded from a scan."""

    paths: Sequence[str | os.PathLike[str]] = ()
    globs: Sequence[str] = ()
    hidden: bool = False
    system: bool = False


@dataclass
class ScanRequest:
    """Scan targets and traversal policies, copied when a scan starts."""

    targets: Sequence[str | os.PathLike[str]]
    mode: ScanMode = ScanMode.AUTO
    threads: int = 0
    follow_symlinks: bool = False
    cross_filesystems: bool = False
    exclude: ExcludeRules = field(default_factory=ExcludeRules)
    owner: OwnerMode = OwnerMode.LAZY
    hardlinks: HardlinkMode = HardlinkMode.DEDUP
    include_ads: bool = False
    show_ntfs_metafiles: bool = True


@dataclass(frozen=True)
class ScanIssue:
    """A recoverable issue associated with a native path."""

    path: str
    kind: IssueKind
    message: str


@dataclass(frozen=True)
class IssueSummary:
    """Complete counts and the first 1,000 diagnostics."""

    counts: tuple[int, ...]
    first: tuple[ScanIssue, ...]
    total: int
    overflow: int


@dataclass(frozen=True)
class Notice:
    """An informational policy or volume message."""

    kind: NoticeKind
    detail: str


@dataclass(frozen=True)
class VolumeInfo:
    """Volume identity, capacity, and relevant filesystem capabilities."""

    mount: str = ""
    fs_type: str = ""
    label: str = ""
    serial: int = 0
    total: int = 0
    free: int = 0
    cluster_size: int = 0
    is_network: bool = False
    is_removable: bool = False
    supports_mft: bool = False
    is_rotational: bool | None = None


@dataclass(frozen=True)
class ScanMeta:
    """Scan provenance and retained diagnostics."""

    started_at: int
    finished_at: int
    mode: ScanModeUsed
    options: ScanRequest
    host: str
    os: str
    app_version: str
    volumes: tuple[VolumeInfo, ...]
    issues: IssueSummary
    cancelled: bool


@dataclass(frozen=True)
class ScanProgress:
    """A non-blocking snapshot of scan progress."""

    files: int
    dirs: int
    bytes: int
    alloc: int
    issues: int
    current: str
    elapsed_ms: int
    state: ScanState
    est_total: int | None
    mode: ScanModeUsed


@dataclass(frozen=True)
class ScanSummary:
    """Final scan totals and cancellation status."""

    files: int
    dirs: int
    bytes: int
    alloc: int
    elapsed_ms: int
    issues: IssueSummary
    cancelled: bool


@dataclass(frozen=True)
class NodeInfo:
    """Copied node metadata; directory sizes and counts include descendants."""

    id: int
    parent: int | None
    flags: NodeFlags
    size: int
    alloc: int
    files: int
    dirs: int
    mtime: int | None
    btime: int | None
    atime: int | None
    owner: str | None
    ext: str | None


@dataclass(frozen=True)
class MemoryReport:
    """Reserved storage bytes owned by a tree."""

    nodes: int
    counts: int
    names: int
    interners: int


class Backend:
    """Opaque native backend; worker threads never invoke Python callbacks."""

    def __init__(self, native: _core.Backend) -> None:
        self._native = native

    @property
    def read_dir_calls(self) -> int:
        """Return the number of synthetic directory read attempts."""
        return self._native.read_dir_calls

    @property
    def owner_resolution_calls(self) -> int:
        """Return the number of synthetic owner lookup attempts."""
        return self._native.owner_resolution_calls


def _native_request(req: ScanRequest) -> _core.ScanOptions:
    if req.threads < 0:
        raise ValueError("threads must be non-negative")
    native = _core.ScanOptions()
    native.targets = [_absolute(path) for path in req.targets]
    native.mode = _core.ScanMode(req.mode.value)
    native.threads = req.threads
    native.follow_symlinks = req.follow_symlinks
    native.cross_filesystems = req.cross_filesystems
    rules = _core.ExcludeRules()
    rules.paths = [_absolute(path) for path in req.exclude.paths]
    rules.globs = list(req.exclude.globs)
    rules.hidden, rules.system = req.exclude.hidden, req.exclude.system
    native.exclude = rules
    native.owner = _core.OwnerMode(req.owner.value)
    native.hardlinks = _core.HardlinkMode(req.hardlinks.value)
    native.include_ads = req.include_ads
    native.show_ntfs_metafiles = req.show_ntfs_metafiles
    return native


def _request(value: _core.ScanOptions) -> ScanRequest:
    return ScanRequest(
        tuple(value.targets),
        ScanMode(value.mode.value),
        value.threads,
        value.follow_symlinks,
        value.cross_filesystems,
        ExcludeRules(
            tuple(value.exclude.paths),
            tuple(value.exclude.globs),
            value.exclude.hidden,
            value.exclude.system,
        ),
        OwnerMode(value.owner.value),
        HardlinkMode(value.hardlinks.value),
        value.include_ads,
        value.show_ntfs_metafiles,
    )


def _issue(value: _core.ScanIssue) -> ScanIssue:
    return ScanIssue(value.path, IssueKind(value.kind.value), value.message)


def _issues(value: _core.IssueSummary) -> IssueSummary:
    return IssueSummary(
        tuple(value.counts), tuple(map(_issue, value.first)), value.total, value.overflow
    )


def _progress(value: _core.ScanProgress) -> ScanProgress:
    return ScanProgress(
        value.files,
        value.dirs,
        value.bytes,
        value.alloc,
        value.issues,
        value.current,
        value.elapsed_ms,
        ScanState(value.state.value),
        value.est_total,
        ScanModeUsed(value.mode.value),
    )


def _volume(value: _core.VolumeInfo) -> VolumeInfo:
    return VolumeInfo(
        value.mount,
        value.fs_type,
        value.label,
        value.serial,
        value.total,
        value.free,
        value.cluster_size,
        value.is_network,
        value.is_removable,
        value.supports_mft,
        value.is_rotational,
    )


def _meta(value: _core.ScanMeta) -> ScanMeta:
    return ScanMeta(
        value.started_at,
        value.finished_at,
        ScanModeUsed(value.mode.value),
        _request(value.options),
        value.host,
        value.os,
        value.app_version,
        tuple(map(_volume, value.volumes)),
        _issues(value.issues),
        value.cancelled,
    )


def _absolute(path: str | os.PathLike[str]) -> str:
    # Normalize lexically: Path.resolve would follow links before scan policy applies.
    return os.path.abspath(os.fspath(path))  # noqa: PTH100
