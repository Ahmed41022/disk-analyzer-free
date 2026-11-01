"""Native-backed model notifications, paging, sorting, roles, and selection."""

# ruff: noqa: PLR2004 -- page/cache sizes and metadata positions are contract assertions.

import os
from collections.abc import Callable, Iterator
from dataclasses import replace
from importlib.util import find_spec
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

if find_spec("PySide6") is None:
    if os.environ.get("DAFREE_REQUIRE_GUI") == "1":
        pytest.fail("PySide6 is required when DAFREE_REQUIRE_GUI=1", pytrace=False)
    pytest.skip("PySide6 is not installed", allow_module_level=True)

from PySide6.QtCore import QCoreApplication, QEvent, QItemSelectionModel, QModelIndex, Qt
from PySide6.QtTest import QAbstractItemModelTester

from dafree import api
from dafree.api.testing import MockEntry, MockSpec, make_mock_backend
from dafree.gui.models.tree_model import TreeTableModel
from dafree.settings import ColumnId

pytestmark = pytest.mark.gui


def _make_model(root: Path, files: int = 3) -> TreeTableModel:
    """Build only in the test namespace, with native nested directory metadata."""
    entries = [
        MockEntry(root, api.EntryKind.DIR),
        MockEntry(root / "folder", api.EntryKind.DIR),
        MockEntry(root / "folder/nested", api.EntryKind.DIR),
        MockEntry(root / "folder/nested/leaf", size=7),
        MockEntry(root / "folder/child", size=9),
    ] + [MockEntry(root / f"file{i}.bin", size=i + 1) for i in range(files)]
    tree = api.scan(api.ScanRequest([root]), backend=make_mock_backend(MockSpec(entries))).tree
    return TreeTableModel(api.TreeView(tree), list(ColumnId))


type ModelFactory = Callable[..., TreeTableModel]


@pytest.fixture
def make_model(qtbot: QtBot, tmp_path: Path) -> Iterator[ModelFactory]:
    """Dispose signal connections and the strict tester before native leak auditing."""
    models: list[TreeTableModel] = []

    def create(files: int = 3) -> TreeTableModel:
        model = _make_model(tmp_path, files)
        models.append(model)
        return model

    yield create
    for model in models:
        model.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    models.clear()


def test_model_row_count_matches_view(make_model: ModelFactory) -> None:
    """Root shape, metadata lookups, and invalid/unsupported roles follow Qt contracts."""
    model = make_model()
    assert model.rowCount() == model.view.row_count == 5
    assert model.columnCount() == len(ColumnId)
    assert model.rowCount(model.index(0, 0)) == 0
    assert model.columnCount(model.index(0, 0)) == 0
    assert model.data(QModelIndex()) is None
    assert model.data(model.index(0, 0), Qt.ItemDataRole.DecorationRole) is None
    assert model.node_at(0) == model.view.tree.roots()[0]
    assert model.row_of(model.node_at(0)) == 0
    assert model.row_of(9999) is None
    with pytest.raises(IndexError):
        model.node_at(-1)


def test_toggle_inserts_and_removes_rows(make_model: ModelFactory, tmp_path: Path) -> None:
    """Strict Qt tester sees the old count before each native insertion/removal."""
    model = make_model()
    tester = QAbstractItemModelTester(
        model, QAbstractItemModelTester.FailureReportingMode.Fatal, model
    )
    assert tester.model() is model
    events: list[tuple[str, int, int, int]] = []
    model.rowsAboutToBeInserted.connect(
        lambda parent, first, last: events.append(("before+", first, last, model.rowCount()))
    )
    model.rowsInserted.connect(
        lambda parent, first, last: events.append(("after+", first, last, model.rowCount()))
    )
    model.rowsAboutToBeRemoved.connect(
        lambda parent, first, last: events.append(("before-", first, last, model.rowCount()))
    )
    model.rowsRemoved.connect(
        lambda parent, first, last: events.append(("after-", first, last, model.rowCount()))
    )
    folder = model.view.tree.find_path(tmp_path / "folder")
    assert folder is not None
    row = model.row_of(folder)
    assert row is not None
    model.toggle(row)
    assert events[:2] == [("before+", row + 1, row + 2, 5), ("after+", row + 1, row + 2, 7)]
    model.toggle(row)
    assert events[2:] == [("before-", row + 1, row + 2, 7), ("after-", row + 1, row + 2, 5)]
    # Retained nested expansion is counted correctly on the next insertion.
    model.expand_all_children(row)
    assert model.rowCount() == 8
    model.toggle(row)
    assert model.rowCount() == 5
    model.toggle(row)
    assert model.rowCount() == 8
    leaf_row = model.row_of(model.view.tree.find_path(tmp_path / "folder/child"))
    assert leaf_row is not None
    before = model.rowCount()
    model.toggle(leaf_row)
    assert model.rowCount() == before


def test_page_cache_limits_calls(make_model: ModelFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Aligned pages fetch once, LRU hits refresh recency, changes invalidate all pages."""
    model = make_model(files=10_200)
    calls: list[tuple[int, int]] = []
    rows = model.view.rows

    def counted(start: int, count: int) -> list[api.Row]:
        calls.append((start, count))
        return rows(start, count)

    monkeypatch.setattr(model.view, "rows", counted)
    for row in range(200):
        for column in range(model.columnCount()):
            assert model.data(model.index(row, column)) is not None
    assert calls == [(0, 200)]
    for row in range(0, 10_000, 200):
        model.data(model.index(row, 0))
    assert len(calls) == 50
    model.data(model.index(0, 0))  # Keep the first page recent.
    model.data(model.index(10_000, 0))
    assert len(model._pages) == 50
    model.data(model.index(0, 0))
    assert len(calls) == 51
    model.data(model.index(200, 0))  # Oldest page was evicted.
    assert len(calls) == 52
    model.sort(0)
    assert not model._pages
    model.data(model.index(0, 0), Qt.ItemDataRole.DecorationRole)
    assert not model._pages
    model.toggle(0)
    assert not model._pages


@pytest.mark.parametrize("descending", [False, True])
def test_sort_by_every_column(make_model: ModelFactory, descending: bool) -> None:
    """All nine columns map to native keys without discarding other policy."""
    model = make_model()
    options = replace(model.view.options, dirs_first=True, filter=api.FilterSpec())
    model.set_options(options)
    keys = [
        api.SortKey.NAME,
        api.SortKey.SIZE,
        api.SortKey.PCT_PARENT,
        api.SortKey.ALLOC,
        api.SortKey.FILES,
        api.SortKey.DIRS,
        api.SortKey.MTIME,
        api.SortKey.OWNER,
        api.SortKey.EXT,
    ]
    for column, key in enumerate(keys):
        model.sort(
            column, Qt.SortOrder.DescendingOrder if descending else Qt.SortOrder.AscendingOrder
        )
        assert model.view.options == replace(options, sort=key, descending=descending)
        expected = api.TreeView(model.view.tree, model.view.options).rows(0, 200)
        assert [model.node_at(i) for i in range(model.rowCount())] == [row[0] for row in expected]


def test_reset_restores_selected_node_ids_and_handles_failure(make_model: ModelFactory) -> None:
    """Selection follows IDs through sorting, while filtered nodes are dropped."""
    model = make_model()
    selection = QItemSelectionModel(model)
    model.bind_selection_model(selection)
    selected = [model.node_at(2), model.node_at(3)]
    for row in (2, 3):
        selection.select(
            model.index(row, 0), selection.SelectionFlag.Select | selection.SelectionFlag.Rows
        )
    selection.setCurrentIndex(model.index(2, 4), selection.SelectionFlag.NoUpdate)
    model.sort(0)
    assert {model.node_at(i.row()) for i in selection.selectedRows()} == set(selected)
    assert model.node_at(selection.currentIndex().row()) == selected[0]
    assert selection.currentIndex().column() == 4
    before = model.view.options
    with pytest.raises(ValueError):
        model.set_options(replace(before, filter=api.FilterSpec(api.FilterKind.REGEX, regex="[")))
    assert model.view.options == before
    assert {model.node_at(i.row()) for i in selection.selectedRows()} == set(selected)
    model.set_options(
        replace(before, filter=api.FilterSpec(api.FilterKind.NAME_GLOB, values=("missing*",)))
    )
    assert not selection.selectedRows()
    assert not selection.currentIndex().isValid()


def test_roles_cross_qt_without_losing_metadata(make_model: ModelFactory, tmp_path: Path) -> None:
    """Native uint64 sizes survive ROW_ROLE and surrogate display is explicit."""
    model = make_model()
    original = model.view.rows
    values = list(original(0, 200)[0])
    values[4], values[5] = "bad-\ud800", (1 << 64) - 1
    row = tuple(values)
    model.view.rows = lambda start, count: [row]  # type: ignore[method-assign,return-value]
    index = model.index(0, 0)
    assert model.data(index, model.ROW_ROLE) == row
    assert index.data(model.ROW_ROLE) == row
    assert index.data() == "bad-\\ud800"
    assert "folder" in index.data(Qt.ItemDataRole.AccessibleTextRole)
    assert index.data(Qt.ItemDataRole.ToolTipRole) == str(tmp_path)
    assert model.headerData(0, Qt.Orientation.Horizontal) == "Name"
    assert model.headerData(0, Qt.Orientation.Vertical) is None
