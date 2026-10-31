"""Native scan bindings preserve paths, exceptions, ownership, and Python scheduling."""

import os
import sys
import threading
from pathlib import Path

import pytest

from dafree.api import ScanRequest, ScanState, scan, start_scan
from dafree.api.errors import ExcludeError, ScanError, ScanErrorCode
from dafree.api.testing import MockEntry, MockSpec, make_mock_backend
from dafree.api.types import EntryKind, ExcludeRules, NodeFlags
from tests.testkit import Fixture, oracle, small_mixed


def test_scan_small_mixed_matches_oracle(tmp_path: Path) -> None:
    """Every subtree agrees with independently computed fixture totals."""
    with Fixture.create(small_mixed(), tmp_path) as fixture:
        progress = []
        result = scan(ScanRequest([fixture.root]), on_progress=progress.append)
        tree = result.tree
        for relative, expected in oracle(small_mixed()).items():
            node_id = tree.find_path(fixture.root / relative)
            assert node_id is not None
            node = tree.node(node_id)
            # Tree counts are descendants; the oracle includes a file itself.
            files = node.files if node.flags & NodeFlags.DIR else 1
            assert (node.size, files, node.dirs) == (
                expected.size,
                expected.files,
                expected.dirs,
            )
        assert progress[-1].state == ScanState.DONE
        assert result.summary.bytes == oracle(small_mixed())[""].size
        assert tree.meta().options.targets == (str(fixture.root),)
        assert tree.memory_usage().nodes > 0
        assert tree.parent(0) is None
        assert tree.roots() == list(tree.children(0))
        with pytest.raises(IndexError):
            tree.node(-1)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="POSIX byte filenames")
def test_paths_roundtrip_invalid_utf8(tmp_path: Path) -> None:
    """Surrogateescape returns exactly the original filename bytes."""
    path = tmp_path / os.fsdecode(b"bad-\xff\xfe")
    path.write_bytes(b"abc")
    tree = scan(ScanRequest([tmp_path])).tree
    node_id = tree.find_path(path)
    assert node_id is not None
    assert os.fsencode(tree.name(node_id)) == b"bad-\xff\xfe"
    assert tree.path(node_id) == str(path)
    assert scan(ScanRequest([path])).summary.bytes == path.stat().st_size


@pytest.mark.skipif(sys.platform != "win32", reason="Windows WTF-8 filenames")
def test_paths_roundtrip_lone_surrogate(tmp_path: Path) -> None:
    """Unpaired UTF-16 surrogates survive a real scan and subsequent lookup."""
    path = tmp_path / "bad-\ud800"
    path.write_bytes(b"abc")
    tree = scan(ScanRequest([tmp_path])).tree
    node_id = tree.find_path(path)
    assert node_id is not None
    assert tree.name(node_id) == path.name
    assert tree.path(node_id) == str(path)
    assert scan(ScanRequest([path])).summary.bytes == path.stat().st_size


def test_scan_errors_map_to_python_exceptions(tmp_path: Path) -> None:
    """Native validation and OS failures have stable public exception types."""
    with pytest.raises(ScanError) as empty:
        start_scan(ScanRequest([]))
    assert empty.value.code == ScanErrorCode.NO_TARGETS
    missing = tmp_path / "missing"
    with pytest.raises(ScanError) as absent:
        start_scan(ScanRequest([missing]))
    assert absent.value.code == ScanErrorCode.TARGET_NOT_FOUND
    assert absent.value.path == str(missing)
    with pytest.raises(ScanError) as overlap:
        start_scan(ScanRequest([tmp_path, tmp_path / "child"]))
    assert overlap.value.code == ScanErrorCode.OVERLAPPING_TARGETS
    with pytest.raises(ExcludeError) as bad_glob:
        start_scan(ScanRequest([tmp_path], exclude=ExcludeRules(globs=["[oops"])))
    assert bad_glob.value.pattern == "[oops"
    handle = start_scan(ScanRequest([tmp_path]))
    assert handle.wait(5000)
    result = handle.take_result()
    with pytest.raises(ScanError) as consumed:
        handle.take_result()
    assert consumed.value.code == ScanErrorCode.ALREADY_TAKEN
    del handle
    assert result.tree.find_path(tmp_path) is not None


def test_wait_releases_gil(tmp_path: Path) -> None:
    """A Python thread makes progress throughout a blocking native wait."""
    backend = make_mock_backend(
        MockSpec(
            [
                MockEntry(tmp_path, EntryKind.DIR),
                MockEntry(tmp_path / "sub", EntryKind.DIR),
                MockEntry(tmp_path / "sub" / "file", size=1),
            ],
            delay_ms=150,
        )
    )
    handle = start_scan(ScanRequest([tmp_path], threads=1), backend=backend)
    stopped = threading.Event()
    ready = threading.Event()
    count = [0]

    def increment() -> None:
        ready.set()
        while not stopped.is_set():
            count[0] += 1

    thread = threading.Thread(target=increment)
    thread.start()
    try:
        assert ready.wait(2)
        before = count[0]
        assert handle.wait(5000)
        assert count[0] > before
    finally:
        stopped.set()
        thread.join()
    assert handle.take_result().summary.bytes == 1
