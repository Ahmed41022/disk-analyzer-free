import enum
from collections.abc import Sequence

def version() -> str:
    """Return the installed package version."""

class UnitMode(enum.Enum):
    AUTO = 0

    BYTES = 1

    KILO = 2

    MEGA = 3

    GIGA = 4

    TERA = 5

    PETA = 6

    EXA = 7

class UnitSystem(enum.Enum):
    TRADITIONAL = 0

    IEC = 1

    SI = 2

class UnitStyle:
    def __init__(self, system: UnitSystem, decimal_separator: str) -> None: ...
    @property
    def system(self) -> UnitSystem: ...
    @system.setter
    def system(self, arg: UnitSystem, /) -> None: ...
    @property
    def decimal_separator(self) -> str: ...
    @decimal_separator.setter
    def decimal_separator(self, arg: str, /) -> None: ...

def format_size(bytes: int, mode: UnitMode, style: UnitStyle) -> str:
    """Format a byte count."""

def parse_size(text: str, style: UnitStyle) -> int:
    """Parse a byte count."""

class ScanMode(enum.Enum):
    AUTO = 0

    WALK = 1

    MFT = 2

class OwnerMode(enum.Enum):
    OFF = 0

    LAZY = 1

    EAGER = 2

class HardlinkMode(enum.Enum):
    DEDUP = 0

    COUNT_ALL = 1

class ScanModeUsed(enum.Enum):
    WALK = 0

    MFT = 1

    SFTP = 2

class ScanState(enum.Enum):
    RUNNING = 0

    PAUSED = 1

    FINALIZING = 2

    DONE = 3

    CANCELLED = 4

    FAILED = 5

class IssueKind(enum.Enum):
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

class EntryKind(enum.Enum):
    FILE = 0

    DIR = 1

    SYMLINK = 2

    JUNCTION = 3

    MOUNT_POINT = 4

    OTHER_REPARSE = 5

    OTHER = 6

class NoticeKind(enum.Enum):
    FAST_MODE_UNAVAILABLE = 0

    NETWORK_VOLUME = 1

    ROTATIONAL_DISK = 2

    HARDLINK_DEDUP_DISABLED = 3

class Backend:
    """Opaque filesystem backend; workers never call Python."""

    @property
    def read_dir_calls(self) -> int: ...
    @property
    def owner_resolution_calls(self) -> int: ...

class ExcludeRules:
    """Paths, globs, and attribute exclusions."""

    def __init__(self) -> None: ...
    @property
    def paths(self) -> list[str]: ...
    @paths.setter
    def paths(self, arg: Sequence[str], /) -> None: ...
    @property
    def globs(self) -> list[str]: ...
    @globs.setter
    def globs(self, arg: Sequence[str], /) -> None: ...
    @property
    def hidden(self) -> bool: ...
    @hidden.setter
    def hidden(self, arg: bool, /) -> None: ...
    @property
    def system(self) -> bool: ...
    @system.setter
    def system(self, arg: bool, /) -> None: ...

class ScanOptions:
    """Native scan input copied at start."""

    def __init__(self) -> None: ...
    @property
    def targets(self) -> list[str]: ...
    @targets.setter
    def targets(self, arg: Sequence[str], /) -> None: ...
    @property
    def mode(self) -> ScanMode: ...
    @mode.setter
    def mode(self, arg: ScanMode, /) -> None: ...
    @property
    def threads(self) -> int: ...
    @threads.setter
    def threads(self, arg: int, /) -> None: ...
    @property
    def follow_symlinks(self) -> bool: ...
    @follow_symlinks.setter
    def follow_symlinks(self, arg: bool, /) -> None: ...
    @property
    def cross_filesystems(self) -> bool: ...
    @cross_filesystems.setter
    def cross_filesystems(self, arg: bool, /) -> None: ...
    @property
    def exclude(self) -> ExcludeRules: ...
    @exclude.setter
    def exclude(self, arg: ExcludeRules, /) -> None: ...
    @property
    def owner(self) -> OwnerMode: ...
    @owner.setter
    def owner(self, arg: OwnerMode, /) -> None: ...
    @property
    def hardlinks(self) -> HardlinkMode: ...
    @hardlinks.setter
    def hardlinks(self, arg: HardlinkMode, /) -> None: ...
    @property
    def include_ads(self) -> bool: ...
    @include_ads.setter
    def include_ads(self, arg: bool, /) -> None: ...
    @property
    def show_ntfs_metafiles(self) -> bool: ...
    @show_ntfs_metafiles.setter
    def show_ntfs_metafiles(self, arg: bool, /) -> None: ...
    @property
    def progress_interval_ms(self) -> int: ...
    @progress_interval_ms.setter
    def progress_interval_ms(self, arg: int, /) -> None: ...

class ScanIssue:
    """A recoverable scan issue."""

    @property
    def path(self) -> str: ...
    @property
    def kind(self) -> IssueKind: ...
    @property
    def message(self) -> str: ...

class IssueSummary:
    """Complete counts and the first 1,000 diagnostics."""

    @property
    def counts(self) -> list[int]: ...
    @property
    def first(self) -> list[ScanIssue]: ...
    @property
    def total(self) -> int: ...
    @property
    def overflow(self) -> int: ...

class Notice:
    """Informational volume or policy notice."""

    @property
    def kind(self) -> NoticeKind: ...
    @property
    def detail(self) -> str: ...

class VolumeInfo:
    """Capacity and scan-relevant volume properties."""

    def __init__(self) -> None: ...
    @property
    def mount(self) -> str: ...
    @mount.setter
    def mount(self, arg: str, /) -> None: ...
    @property
    def fs_type(self) -> str: ...
    @fs_type.setter
    def fs_type(self, arg: str, /) -> None: ...
    @property
    def label(self) -> str: ...
    @label.setter
    def label(self, arg: str, /) -> None: ...
    @property
    def serial(self) -> int: ...
    @serial.setter
    def serial(self, arg: int, /) -> None: ...
    @property
    def total(self) -> int: ...
    @total.setter
    def total(self, arg: int, /) -> None: ...
    @property
    def free(self) -> int: ...
    @free.setter
    def free(self, arg: int, /) -> None: ...
    @property
    def cluster_size(self) -> int: ...
    @cluster_size.setter
    def cluster_size(self, arg: int, /) -> None: ...
    @property
    def is_network(self) -> bool: ...
    @is_network.setter
    def is_network(self, arg: bool, /) -> None: ...
    @property
    def is_removable(self) -> bool: ...
    @is_removable.setter
    def is_removable(self, arg: bool, /) -> None: ...
    @property
    def supports_mft(self) -> bool: ...
    @supports_mft.setter
    def supports_mft(self, arg: bool, /) -> None: ...
    @property
    def is_rotational(self) -> bool | None: ...
    @is_rotational.setter
    def is_rotational(self, arg: bool | None, /) -> None: ...

class ScanMeta:
    """Copied scan provenance, options, and diagnostics."""

    @property
    def started_at(self) -> int: ...
    @property
    def finished_at(self) -> int: ...
    @property
    def mode(self) -> ScanModeUsed: ...
    @property
    def options(self) -> ScanOptions: ...
    @property
    def host(self) -> str: ...
    @property
    def os(self) -> str: ...
    @property
    def app_version(self) -> str: ...
    @property
    def volumes(self) -> list[VolumeInfo]: ...
    @property
    def issues(self) -> IssueSummary: ...
    @property
    def cancelled(self) -> bool: ...

class ScanProgress:
    """A non-blocking scan progress snapshot."""

    @property
    def files(self) -> int: ...
    @property
    def dirs(self) -> int: ...
    @property
    def bytes(self) -> int: ...
    @property
    def alloc(self) -> int: ...
    @property
    def issues(self) -> int: ...
    @property
    def current(self) -> str: ...
    @property
    def elapsed_ms(self) -> int: ...
    @property
    def state(self) -> ScanState: ...
    @property
    def est_total(self) -> int | None: ...
    @property
    def mode(self) -> ScanModeUsed: ...

class ScanSummary:
    """Final scan entry and byte totals."""

    @property
    def files(self) -> int: ...
    @property
    def dirs(self) -> int: ...
    @property
    def bytes(self) -> int: ...
    @property
    def alloc(self) -> int: ...
    @property
    def elapsed_ms(self) -> int: ...
    @property
    def issues(self) -> IssueSummary: ...
    @property
    def cancelled(self) -> bool: ...

class MemoryReport:
    """Reserved tree storage bytes."""

    @property
    def nodes(self) -> int: ...
    @property
    def counts(self) -> int: ...
    @property
    def names(self) -> int: ...
    @property
    def interners(self) -> int: ...

class NodeInfo:
    """Copied node metadata and descendant counts."""

    @property
    def id(self) -> int: ...
    @property
    def parent(self) -> int | None: ...
    @property
    def flags(self) -> int: ...
    @property
    def size(self) -> int: ...
    @property
    def alloc(self) -> int: ...
    @property
    def files(self) -> int: ...
    @property
    def dirs(self) -> int: ...
    @property
    def mtime(self) -> int | None: ...
    @property
    def btime(self) -> int | None: ...
    @property
    def atime(self) -> int | None: ...
    @property
    def owner(self) -> str | None: ...
    @property
    def ext(self) -> str | None: ...

class Tree:
    """A shared tree with coherent reader locking."""

    def __len__(self) -> int: ...
    def node(self, id: int) -> NodeInfo:
        """Copy node metadata."""

    def name(self, id: int) -> str:
        """Return a lossless native entry name."""

    def path(self, id: int) -> str:
        """Reconstruct a lossless native path."""

    def children(self, id: int) -> tuple[int, int]:
        """Return the half-open contiguous child range."""

    def parent(self, id: int) -> int | None:
        """Return the parent ID, or None for the synthetic root."""

    def roots(self) -> list[int]:
        """Return scan target node IDs."""

    def find_path(self, path: str) -> int | None:
        """Find a native path within the scan."""

    def meta(self) -> ScanMeta:
        """Copy scan provenance and diagnostics."""

    def memory_usage(self) -> MemoryReport:
        """Return reserved tree storage bytes."""

    def resolve_owners(self, ids: Sequence[int]) -> None:
        """Resolve requested identities with the GIL released."""

class TimeField(enum.Enum):
    MODIFIED = 0

    CREATED = 1

    ACCESSED = 2

class ExtCategory(enum.Enum):
    IMAGE = 0

    VIDEO = 1

    AUDIO = 2

    ARCHIVE = 3

    DOCUMENT = 4

    CODE = 5

    EXECUTABLE = 6

    DISK_IMAGE = 7

    SYSTEM = 8

    OTHER = 9

class SortKey(enum.Enum):
    NAME = 0

    SIZE = 1

    ALLOC = 2

    PCT_PARENT = 3

    FILES = 4

    DIRS = 5

    MTIME = 6

    OWNER = 7

    EXT = 8

class CmpOp(enum.Enum):
    LT = 0

    LE = 1

    EQ = 2

    GE = 3

    GT = 4

class Cmp64:
    """Unsigned numeric filter comparison."""

    def __init__(self) -> None: ...
    @property
    def op(self) -> CmpOp: ...
    @op.setter
    def op(self, arg: CmpOp, /) -> None: ...
    @property
    def v(self) -> int: ...
    @v.setter
    def v(self, arg: int, /) -> None: ...

class FilterKind(enum.Enum):
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

class FilterSpec:
    """Copied native filter expression."""

    def __init__(self) -> None: ...
    @property
    def kind(self) -> FilterKind: ...
    @kind.setter
    def kind(self, arg: FilterKind, /) -> None: ...
    @property
    def children(self) -> list[FilterSpec]: ...
    @children.setter
    def children(self, arg: Sequence[FilterSpec], /) -> None: ...
    @property
    def cmp(self) -> Cmp64: ...
    @cmp.setter
    def cmp(self, arg: Cmp64, /) -> None: ...
    @property
    def time_field(self) -> TimeField: ...
    @time_field.setter
    def time_field(self, arg: TimeField, /) -> None: ...
    @property
    def values(self) -> list[str]: ...
    @values.setter
    def values(self, arg: Sequence[str], /) -> None: ...
    @property
    def regex(self) -> str: ...
    @regex.setter
    def regex(self, arg: str, /) -> None: ...
    @property
    def flag(self) -> int: ...
    @flag.setter
    def flag(self, arg: int, /) -> None: ...
    @property
    def type_dir(self) -> bool: ...
    @type_dir.setter
    def type_dir(self, arg: bool, /) -> None: ...

class ViewOptions:
    """Copied view display options."""

    def __init__(self) -> None: ...
    @property
    def sort(self) -> SortKey: ...
    @sort.setter
    def sort(self, arg: SortKey, /) -> None: ...
    @property
    def descending(self) -> bool: ...
    @descending.setter
    def descending(self, arg: bool, /) -> None: ...
    @property
    def dirs_first(self) -> bool: ...
    @dirs_first.setter
    def dirs_first(self, arg: bool, /) -> None: ...
    @property
    def show_files(self) -> bool: ...
    @show_files.setter
    def show_files(self, arg: bool, /) -> None: ...
    @property
    def filter(self) -> FilterSpec | None: ...
    @filter.setter
    def filter(self, arg: FilterSpec | None, /) -> None: ...
    @property
    def resolve_owner(self) -> bool: ...
    @resolve_owner.setter
    def resolve_owner(self, arg: bool, /) -> None: ...

class TreeView:
    """Paged native visible tree."""

    def __init__(self, tree: Tree, options: ViewOptions) -> None: ...
    @property
    def row_count(self) -> int: ...
    @property
    def options(self) -> ViewOptions: ...
    def rows(
        self, start: int, count: int
    ) -> list[
        tuple[
            int,
            int,
            bool,
            bool,
            str,
            int,
            int,
            float,
            int,
            int,
            int,
            str | None,
            str | None,
            int,
            int,
        ]
    ]:
        """
        Return at most 500 native tuples:
        (id, depth, has_children, expanded, name, size, alloc, pct,
         files, dirs, mtime, owner, ext, flags, ext_cat).
        """

    def expand(self, id: int) -> int: ...
    def expansion_count(self, id: int) -> int: ...
    def collapse_count(self, id: int) -> int: ...
    def expand_children(self, id: int) -> None: ...
    def collapse(self, id: int) -> int: ...
    def expand_to(self, id: int) -> int: ...
    def set_options(self, options: ViewOptions) -> None: ...
    def index_of(self, id: int) -> int | None: ...

class ScanResult:
    """An immutable tree and final scan summary."""

    @property
    def tree(self) -> Tree: ...
    @property
    def summary(self) -> ScanSummary: ...

class ScanHandle:
    """Asynchronous scan control; native threads never enter Python."""

    def progress(self) -> ScanProgress:
        """Return a progress snapshot."""

    def drain_issues(self, max: int = 1000) -> list[ScanIssue]:
        """Drain live diagnostics."""

    def drain_notices(self) -> list[Notice]:
        """Drain policy notices."""

    def pause(self) -> None:
        """Pause between directory reads."""

    def resume(self) -> None:
        """Resume directory reads."""

    def cancel(self) -> None:
        """Request cancellation."""

    def wait(self, timeout_ms: int) -> bool:
        """Wait with the GIL released."""

    def partial_tree(self) -> Tree:
        """Request a throttled immutable snapshot."""

    def take_result(self) -> ScanResult:
        """Consume the completed result once."""

def start_scan(options: ScanOptions, backend: Backend | None = None) -> ScanHandle:
    """Start an asynchronous scan."""

class testing:
    """Native test fixture namespace."""

    class TreeBuilder:
        """MockBackend-free synthetic trees."""

        @staticmethod
        def flat(root: str, visible_rows: int) -> Tree:
            """
            Build exactly visible_rows rows entirely in native memory; never read the filesystem.
            """

class RawEntry:
    """Synthetic native entry metadata."""

    def __init__(self) -> None: ...
    @property
    def kind(self) -> EntryKind: ...
    @kind.setter
    def kind(self, arg: EntryKind, /) -> None: ...
    @property
    def size(self) -> int: ...
    @size.setter
    def size(self, arg: int, /) -> None: ...
    @property
    def alloc(self) -> int: ...
    @alloc.setter
    def alloc(self, arg: int, /) -> None: ...
    @property
    def dev(self) -> int: ...
    @dev.setter
    def dev(self, arg: int, /) -> None: ...
    @property
    def ino_lo(self) -> int: ...
    @ino_lo.setter
    def ino_lo(self, arg: int, /) -> None: ...
    @property
    def ino_hi(self) -> int: ...
    @ino_hi.setter
    def ino_hi(self, arg: int, /) -> None: ...
    @property
    def nlink(self) -> int: ...
    @nlink.setter
    def nlink(self, arg: int, /) -> None: ...
    @property
    def hidden(self) -> bool: ...
    @hidden.setter
    def hidden(self, arg: bool, /) -> None: ...
    @property
    def system(self) -> bool: ...
    @system.setter
    def system(self, arg: bool, /) -> None: ...
    @property
    def sparse(self) -> bool: ...
    @sparse.setter
    def sparse(self, arg: bool, /) -> None: ...
    @property
    def compressed(self) -> bool: ...
    @compressed.setter
    def compressed(self, arg: bool, /) -> None: ...
    @property
    def cloud(self) -> bool: ...
    @cloud.setter
    def cloud(self, arg: bool, /) -> None: ...
    @property
    def access_denied(self) -> bool: ...
    @access_denied.setter
    def access_denied(self, arg: bool, /) -> None: ...
    @property
    def owner_uid(self) -> int | None: ...
    @owner_uid.setter
    def owner_uid(self, arg: int | None, /) -> None: ...

class MockEntry:
    """A path and its synthetic metadata."""

    def __init__(self) -> None: ...
    @property
    def path(self) -> str: ...
    @path.setter
    def path(self, arg: str, /) -> None: ...
    @property
    def entry(self) -> RawEntry: ...
    @entry.setter
    def entry(self, arg: RawEntry, /) -> None: ...

class MockSpec:
    """Deterministic native-only test backend inputs."""

    def __init__(self) -> None: ...
    @property
    def entries(self) -> list[MockEntry]: ...
    @entries.setter
    def entries(self, arg: Sequence[MockEntry], /) -> None: ...
    @property
    def volume(self) -> VolumeInfo | None: ...
    @volume.setter
    def volume(self, arg: VolumeInfo | None, /) -> None: ...
    @property
    def vanish_after_listing(self) -> list[str]: ...
    @vanish_after_listing.setter
    def vanish_after_listing(self, arg: Sequence[str], /) -> None: ...
    @property
    def delay_ms(self) -> int: ...
    @delay_ms.setter
    def delay_ms(self, arg: int, /) -> None: ...
    @property
    def errors(self) -> dict[str, IssueKind]: ...
    @errors.setter
    def errors(self, arg: dict[str, IssueKind], /) -> None: ...
    @property
    def symlink_targets(self) -> dict[str, str]: ...
    @symlink_targets.setter
    def symlink_targets(self, arg: dict[str, str], /) -> None: ...
    @property
    def owner_names(self) -> dict[int, str]: ...
    @owner_names.setter
    def owner_names(self, arg: dict[int, str], /) -> None: ...

def make_mock_backend(spec: MockSpec) -> Backend:
    """Build an immutable native test backend."""
