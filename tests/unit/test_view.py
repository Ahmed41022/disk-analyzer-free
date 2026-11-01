"""The public view facade returns native tuple pages without walking trees in Python."""

# ruff: noqa: PLR2004 -- contract field counts and fixture metadata are literal expectations.

import gc
import os
import subprocess
import sys
import threading
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from dafree.api import (
    Cmp64,
    CmpOp,
    EntryKind,
    ExtCategory,
    FilterKind,
    FilterSpec,
    ScanRequest,
    SortKey,
    TimeField,
    Tree,
    TreeView,
    ViewOptions,
    scan,
)
from dafree.api.testing import MockEntry, MockSpec, make_mock_backend


def make_tree(root: Path, count: int = 3) -> Tree:
    """Make an entirely native synthetic scan rooted in this test's temp directory."""
    backend = make_mock_backend(
        MockSpec(
            [MockEntry(root, EntryKind.DIR)]
            + [MockEntry(root / f"file{i}.bin", size=i + 1) for i in range(count)]
        )
    )
    return scan(ScanRequest([root]), backend=backend).tree


def test_view_rows_are_native_tuples_with_stable_fields(tmp_path: Path) -> None:
    """The 15-field contract contains copied metadata, ratios, and category IDs."""
    tree = make_tree(tmp_path)
    view = TreeView(tree)
    assert view.row_count == 4
    rows = view.rows(0, 500)
    assert all(isinstance(row, tuple) and len(row) == 15 for row in rows)
    root, largest = rows[:2]
    assert root[:5] == (tree.roots()[0], 0, True, True, str(tmp_path))
    assert largest[1:11] == (1, False, False, "file2.bin", 3, 3, 0.5, 0, 0, 0)
    assert largest[11:] == (None, "bin", 0, ExtCategory.OTHER)
    assert view.index_of(largest[0]) == 1
    assert view.collapse(root[0]) == 3
    assert view.row_count == 1
    assert view.index_of(largest[0]) is None
    assert view.expand_to(largest[0]) == 1
    assert view.expand(root[0]) == 0
    # No Python Tree methods participate in retrieving native pages.
    tree.node = lambda _: pytest.fail("Python node walk")  # type: ignore[method-assign]
    assert view.rows(1, 1)[0] == largest


def test_view_keeps_native_tree_and_owner_context_alive(tmp_path: Path) -> None:
    """Dropping the original facade and backend cannot invalidate lazy lookups."""
    backend = make_mock_backend(
        MockSpec(
            [MockEntry(tmp_path, EntryKind.DIR), MockEntry(tmp_path / "owned", owner_uid=42)],
            owner_names={42: "Alice"},
        )
    )
    tree = scan(ScanRequest([tmp_path]), backend=backend).tree
    view = TreeView(tree, ViewOptions(resolve_owner=True))
    del tree, backend
    gc.collect()
    assert view.rows(1, 1)[0][11] == "Alice"
    assert view.rows(1, 1)[0][11] == "Alice"


def test_view_options_are_copied_and_filters_preserve_expansion(tmp_path: Path) -> None:
    """Sort changes preserve filters and failed filters leave the current view intact."""
    tree = make_tree(tmp_path)
    filter_ = FilterSpec(
        FilterKind.AND,
        (
            FilterSpec(FilterKind.SIZE, cmp=Cmp64(CmpOp.GE, 2)),
            FilterSpec(FilterKind.EXT, values=("BIN",)),
        ),
    )
    options = ViewOptions(filter=filter_, dirs_first=True)
    view = TreeView(tree, options)
    assert view.options == options
    assert [row[4] for row in view.rows(1, 500)] == ["file2.bin", "file1.bin"]
    with pytest.raises(FrozenInstanceError):
        view.options.descending = False  # type: ignore[misc]
    view.collapse(tree.roots()[0])
    ascending = replace(view.options, sort=SortKey.NAME, descending=False)
    view.set_options(ascending)
    assert view.row_count == 1
    view.expand(tree.roots()[0])
    before = view.rows(0, 500)
    with pytest.raises(ValueError):
        view.set_options(replace(ascending, filter=FilterSpec(FilterKind.REGEX, regex="[")))
    assert view.options == ascending
    assert view.rows(0, 500) == before


@pytest.mark.parametrize("key", list(SortKey))
@pytest.mark.parametrize("descending", [False, True])
def test_view_all_sort_keys_cross_the_binding(
    tmp_path: Path, key: SortKey, descending: bool
) -> None:
    """Every public sort enum maps to its native counterpart in both directions."""
    view = TreeView(make_tree(tmp_path), ViewOptions(sort=key, descending=descending))
    assert view.options.sort == key
    assert view.options.descending == descending
    assert len(view.rows(0, 500)) == 4


@pytest.mark.parametrize("field", list(TimeField))
def test_view_unknown_time_can_be_selected_explicitly(tmp_path: Path, field: TimeField) -> None:
    """Zero retains its explicit unknown-time meaning through filter conversion."""
    view = TreeView(
        make_tree(tmp_path),
        ViewOptions(filter=FilterSpec(FilterKind.TIME, cmp=Cmp64(CmpOp.EQ, 0), time_field=field)),
    )
    assert view.row_count == 4
    assert view.options.filter is not None
    assert view.options.filter.time_field == field


def test_view_page_bounds_and_invalid_ids(tmp_path: Path) -> None:
    """Huge counts are capped before conversion; invalid IDs cannot wrap uint32."""
    view = TreeView(make_tree(tmp_path, 710))
    assert len(view.rows(0, 1 << 100)) == 500
    assert len(view.rows(700, 500)) == 11
    assert view.rows(1 << 100, 10) == []
    assert view.rows(0, 0) == []
    for start, count in [(-1, 1), (0, -1)]:
        with pytest.raises(ValueError):
            view.rows(start, count)
    for node_id in [-1, 1 << 100]:
        assert view.index_of(node_id) is None
        for operation in [view.expand, view.collapse, view.expand_to]:
            with pytest.raises(IndexError):
                operation(node_id)


@pytest.mark.parametrize(
    "filter_",
    [
        FilterSpec(FilterKind.SIZE, cmp=Cmp64(CmpOp.EQ, -1)),
        FilterSpec(FilterKind.SIZE, cmp=Cmp64(CmpOp.EQ, 1 << 64)),
        FilterSpec(FilterKind.FLAG, flag=1 << 16),
        FilterSpec(FilterKind.REGEX, regex="a" * ((1 << 20) + 1)),
    ],
)
def test_view_rejects_out_of_range_filters(tmp_path: Path, filter_: FilterSpec) -> None:
    """Reject invalid values before native narrowing or expensive compilation."""
    with pytest.raises(ValueError):
        TreeView(make_tree(tmp_path), ViewOptions(filter=filter_))


def test_view_rejects_excessively_deep_filters(tmp_path: Path) -> None:
    """The expression depth guard applies before recursive binding conversion."""
    filter_ = FilterSpec(FilterKind.EXT, values=("bin",))
    for _ in range(32):
        filter_ = FilterSpec(FilterKind.NOT, children=(filter_,))
    with pytest.raises(ValueError, match="32 levels"):
        TreeView(make_tree(tmp_path), ViewOptions(filter=filter_))


def test_view_lossless_names_and_filter_values(tmp_path: Path) -> None:
    """POSIX surrogateescape and Windows WTF-8 survive row and filter conversions."""
    name = "bad-\ud800.bin" if sys.platform == "win32" else os.fsdecode(b"bad-\xff.bin")
    path = tmp_path / name
    if sys.platform == "darwin":
        # APFS rejects invalid UTF-8 names. Views must still render names from
        # imported/remote trees, so exercise the same native codec via MockBackend.
        backend = make_mock_backend(
            MockSpec([MockEntry(tmp_path, EntryKind.DIR), MockEntry(path, size=3)])
        )
        tree = scan(ScanRequest([tmp_path]), backend=backend).tree
    else:
        path.write_bytes(b"abc")
        tree = scan(ScanRequest([tmp_path])).tree
    filter_ = FilterSpec(FilterKind.NAME_GLOB, values=(name,))
    view = TreeView(tree, ViewOptions(filter=filter_))
    assert view.options.filter == filter_
    assert view.rows(1, 1)[0][4] == name
    view.set_options(ViewOptions(filter=FilterSpec(FilterKind.REGEX, regex=r"\.bin$")))
    assert view.rows(1, 1)[0][4] == name


def test_view_native_operations_release_gil(tmp_path: Path) -> None:
    """Python work progresses during native filtering and sorting."""
    tree = make_tree(tmp_path, 20_000)
    ready = threading.Event()
    stop = threading.Event()
    ticks = [0]

    def heartbeat() -> None:
        ready.set()
        while not stop.is_set():
            ticks[0] += 1

    worker = threading.Thread(target=heartbeat)
    worker.start()
    assert ready.wait(5)
    before = ticks[0]
    try:
        view = TreeView(tree, ViewOptions(filter=FilterSpec(FilterKind.REGEX, regex="file.*")))
        view.set_options(replace(view.options, sort=SortKey.NAME))
        assert view.row_count > 0
        assert ticks[0] > before
    finally:
        stop.set()
        worker.join(timeout=5)
    assert not worker.is_alive()


def test_view_analysis_workers_stop_before_python_exits(tmp_path: Path) -> None:
    """A populated shared pool must not deadlock Windows DLL unload after tests pass."""
    script = """
import sys
from pathlib import Path
from dafree.api import EntryKind, FilterSpec, ScanRequest, TreeView, ViewOptions, scan
from dafree.api.testing import MockEntry, MockSpec, make_mock_backend
root = Path(sys.argv[1])
backend = make_mock_backend(MockSpec(
    [MockEntry(root, EntryKind.DIR)] +
    [MockEntry(root / str(i), size=1) for i in range(9000)]))
tree = scan(ScanRequest([root]), backend=backend).tree
view = TreeView(tree, ViewOptions(filter=FilterSpec()))
assert view.row_count == 9001
print('view complete', flush=True)
"""
    result = subprocess.run(  # noqa: S603 -- fixed script and test-owned temporary root.
        [sys.executable, "-c", script, str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert result.stdout.strip() == "view complete"
