"""Walk real temporary filesystems and compare independent expected totals."""

import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from dafree.api import HardlinkMode, IssueKind, NodeFlags, ScanRequest, scan
from dafree.api.testing import MockEntry, MockSpec, make_mock_backend
from dafree.api.types import EntryKind
from tests.testkit import (
    Dir,
    File,
    Fixture,
    HardLink,
    deep,
    dupes_mix,
    junction,
    long_paths,
    oracle,
    permission_denied,
    small_mixed,
    sparse_big,
    symlink_loop,
    unicode_zoo,
    wide,
)
from tests.testkit.windows_token import without_backup_privileges

LINK_BYTES = 10_000_000
DUPLICATE_LINKS = 2
LOOP_TIMEOUT_SECONDS = 5
LOOP_NODES = 4
ACCESSIBLE_BYTES = 7
KEPT_BYTES = 3


def _assert_root(fixture: Fixture, *, hardlinks: HardlinkMode = HardlinkMode.DEDUP) -> None:
    expected = oracle(
        fixture.spec, hardlinks="dedup" if hardlinks == HardlinkMode.DEDUP else "count_all"
    )[""]
    result = scan(ScanRequest([fixture.root], hardlinks=hardlinks))
    node = result.tree.node(result.tree.roots()[0])
    assert (node.size, node.files, node.dirs) == (expected.size, expected.files, expected.dirs)
    assert result.summary.issues.total == 0


@pytest.mark.parametrize("preset", [small_mixed, dupes_mix, unicode_zoo])
def test_presets_match_oracle(tmp_path: Path, preset: Callable[[], Dir]) -> None:
    """Ordinary presets retain their independent logical totals."""
    with Fixture.create(preset(), tmp_path) as fixture:
        _assert_root(fixture)


def test_unicode_names_roundtrip(tmp_path: Path) -> None:
    """Each fixture name is found exactly, including undecodable Linux bytes."""
    with Fixture.create(unicode_zoo(), tmp_path) as fixture:
        tree = scan(ScanRequest([fixture.root])).tree
        pending = [(fixture.root, fixture.spec)]
        while pending:
            parent, spec = pending.pop()
            for child in spec.children:
                path = parent / child.name
                node_id = tree.find_path(path)
                assert node_id is not None
                assert tree.name(node_id) == child.name
                assert tree.path(node_id) == str(path)
                if isinstance(child, Dir):
                    pending.append((path, child))


def _links() -> Dir:
    return Dir(
        "root", (File("original", LINK_BYTES), HardLink("a", "original"), HardLink("b", "original"))
    )


def test_hardlinks_counted_once(tmp_path: Path) -> None:
    """Three ten-megabyte entries contribute ten megabytes and two duplicate flags."""
    with Fixture.create(_links(), tmp_path) as fixture:
        fixture.caps.require("hardlink")
        tree = scan(ScanRequest([fixture.root])).tree
        assert tree.node(tree.roots()[0]).size == LINK_BYTES
        duplicates = sum(
            bool(tree.node(i).flags & NodeFlags.HARDLINK_DUP) for i in range(len(tree))
        )
        assert duplicates == DUPLICATE_LINKS
        _assert_root(fixture)


def test_hardlink_mode_count_all(tmp_path: Path) -> None:
    """Count-all retains every link's byte contribution and no duplicate flags."""
    with Fixture.create(_links(), tmp_path) as fixture:
        fixture.caps.require("hardlink")
        result = scan(ScanRequest([fixture.root], hardlinks=HardlinkMode.COUNT_ALL))
        assert result.summary.bytes == LINK_BYTES * (DUPLICATE_LINKS + 1)
        assert not any(
            result.tree.node(i).flags & NodeFlags.HARDLINK_DUP for i in range(len(result.tree))
        )
        _assert_root(fixture, hardlinks=HardlinkMode.COUNT_ALL)


def test_symlink_loop_terminates_with_follow(tmp_path: Path) -> None:
    """Global directory identities stop a real link back to the selected root."""
    with Fixture.create(symlink_loop(), tmp_path) as fixture:
        fixture.caps.require("symlink")
        started = time.monotonic()
        result = scan(ScanRequest([fixture.root], follow_symlinks=True))
        assert time.monotonic() - started < LOOP_TIMEOUT_SECONDS
        assert len(result.tree) == LOOP_NODES
        assert result.summary.bytes == 0


def test_symlink_not_followed_default(tmp_path: Path) -> None:
    """An unfollowed directory link is a zero-byte file entry without children."""
    with Fixture.create(symlink_loop(), tmp_path) as fixture:
        fixture.caps.require("symlink")
        tree = scan(ScanRequest([fixture.root])).tree
        node_id = tree.find_path(fixture.root / "child" / "back")
        assert node_id is not None
        assert tree.node(node_id).flags & NodeFlags.SYMLINK
        assert not tree.children(node_id)
        _assert_root(fixture)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions")
def test_junction_not_followed_default(tmp_path: Path) -> None:
    """A junction remains visible without traversing its target twice."""
    with Fixture.create(junction(), tmp_path) as fixture:
        fixture.caps.require("junction")
        tree = scan(ScanRequest([fixture.root])).tree
        node_id = tree.find_path(fixture.root / "junction")
        assert node_id is not None
        assert tree.node(node_id).flags & NodeFlags.REPARSE
        assert not tree.children(node_id)
        _assert_root(fixture)


def test_permission_denied_flagged_scan_continues(tmp_path: Path) -> None:
    """Denied directories produce flags and issues while accessible siblings scan."""
    spec = permission_denied()
    spec = Dir(spec.name, (*spec.children, File("accessible", ACCESSIBLE_BYTES)))
    with Fixture.create(spec, tmp_path) as fixture:
        fixture.caps.require("permission_denied")
        with without_backup_privileges():
            result = scan(ScanRequest([fixture.root]))
        node_id = result.tree.find_path(fixture.root / "private")
        assert node_id is not None
        assert result.tree.node(node_id).flags & NodeFlags.ACCESS_DENIED
        assert result.summary.issues.counts[IssueKind.ACCESS_DENIED] > 0
        root_node = result.tree.node(result.tree.roots()[0])
        assert root_node.size == ACCESSIBLE_BYTES


def test_deep_300_levels(tmp_path: Path) -> None:
    """Three hundred nested levels enumerate without recursive scanner calls."""
    with Fixture.create(deep(300), tmp_path) as fixture:
        _assert_root(fixture)


@pytest.fixture
def wide_fixture(tmp_path: Path) -> Iterator[Fixture]:
    """Keep filesystem setup and cleanup outside the scan's execution timeout."""
    with Fixture.create(wide(100_000), tmp_path) as fixture:
        yield fixture


@pytest.mark.timeout(300, func_only=True)
@pytest.mark.main_only
def test_wide_100k_files(wide_fixture: Fixture) -> None:
    """A hundred thousand siblings preserve totals and contiguous child access."""
    _assert_root(wide_fixture)


def test_sparse_alloc_lt_size(tmp_path: Path) -> None:
    """A five-GiB sparse file reports logical length above allocated storage."""
    with Fixture.create(sparse_big(), tmp_path) as fixture:
        fixture.caps.require("sparse")
        result = scan(ScanRequest([fixture.root]))
        assert result.summary.alloc < result.summary.bytes
        _assert_root(fixture)


def test_long_paths(tmp_path: Path) -> None:
    """Paths beyond the platform's ordinary path limit retain their terminal file."""
    with Fixture.create(long_paths(), tmp_path) as fixture:
        fixture.caps.require("long_paths")
        result = scan(ScanRequest([fixture.root]))
        leaf = next(i for i in range(len(result.tree)) if result.tree.name(i) == "data.bin")
        minimum = 4200 if sys.platform.startswith("linux") else 400
        assert len(os.fsencode(result.tree.path(leaf))) >= minimum
        assert result.tree.find_path(result.tree.path(leaf)) == leaf
        _assert_root(fixture)


def test_empty_target_dir(tmp_path: Path) -> None:
    """An empty selected directory remains visible with zero descendants."""
    with Fixture.create(Dir("root"), tmp_path) as fixture:
        _assert_root(fixture)


def test_target_is_file(tmp_path: Path) -> None:
    """A selected regular file has one file contribution below the synthetic root."""
    path = tmp_path / "file"
    path.write_bytes(b"hello")
    result = scan(ScanRequest([path]))
    assert result.summary.bytes == len(b"hello")
    assert result.summary.files == 1
    assert result.tree.path(result.tree.roots()[0]) == str(path)


def test_file_vanishes_during_scan(tmp_path: Path) -> None:
    """A native mock injects a disappearance at listing time and retains its issue."""
    vanished = str(tmp_path / "vanished")
    backend = make_mock_backend(
        MockSpec(
            [
                MockEntry(tmp_path, EntryKind.DIR),
                MockEntry(vanished, size=9),
                MockEntry(tmp_path / "kept", size=KEPT_BYTES),
            ],
            vanish_after_listing=[vanished],
        )
    )
    result = scan(ScanRequest([tmp_path]), backend=backend)
    assert result.summary.bytes == KEPT_BYTES
    assert result.summary.issues.counts[IssueKind.NOT_FOUND] == 1
    assert result.tree.find_path(vanished) is None


@pytest.fixture
def mounted_tree(tmp_path: Path) -> Iterator[Path]:
    """Mount tmpfs only below this test's temporary directory and always unmount it."""
    mount = shutil.which("mount")
    umount = shutil.which("umount")
    sudo = shutil.which("sudo")
    if not mount or not umount or not sudo:
        if os.environ.get("CI"):
            raise AssertionError("mount, umount, and sudo are required in Linux CI")
        pytest.skip("mount tools unavailable")
    target = tmp_path / "mounted"
    target.mkdir()
    options = f"size=1m,uid={os.getuid()},gid={os.getgid()},mode=0700"
    command = [sudo, "-n", mount, "-t", "tmpfs", "-o", options, "tmpfs", str(target)]
    mounted = subprocess.run(command, capture_output=True, check=False)  # noqa: S603
    if mounted.returncode:
        if os.environ.get("CI"):
            raise AssertionError(mounted.stderr.decode())
        pytest.skip("tmpfs mount privileges unavailable")
    try:
        (target / "inside").write_bytes(b"mounted")
        yield tmp_path
    finally:
        subprocess.run([sudo, "-n", umount, str(target)], check=True)  # noqa: S603


@pytest.mark.needs_mounts
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux tmpfs")
def test_mount_point_not_crossed(mounted_tree: Path) -> None:
    """Default traversal retains the mount directory without entering its volume."""
    result = scan(ScanRequest([mounted_tree]))
    assert result.summary.bytes == 0
    assert result.tree.find_path(mounted_tree / "mounted" / "inside") is None


@pytest.mark.needs_mounts
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux tmpfs")
def test_mount_point_crossed_when_enabled(mounted_tree: Path) -> None:
    """Explicit cross-filesystem traversal includes the mounted file."""
    result = scan(ScanRequest([mounted_tree], cross_filesystems=True))
    assert result.summary.bytes == len(b"mounted")
    assert result.tree.find_path(mounted_tree / "mounted" / "inside") is not None
