"""Bounded lazy list metadata, Qt contracts, paths, and live unit formatting."""

# ruff: noqa: PLR2004 -- fixed page/cache sizes and column indexes are contract assertions.

import os
from collections.abc import Iterator
from dataclasses import replace
from importlib.util import find_spec
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

if find_spec("PySide6") is None:
    if os.environ.get("DAFREE_REQUIRE_GUI") == "1":
        pytest.fail("PySide6 is required when DAFREE_REQUIRE_GUI=1", pytrace=False)
    pytest.skip("PySide6 is not installed", allow_module_level=True)

from PySide6.QtCore import QCoreApplication, QEvent, QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtTest import QAbstractItemModelTester, QSignalSpy

from dafree import api
from dafree.api.testing import MockEntry, MockSpec, make_mock_backend
from dafree.gui import _display_text, _format_size
from dafree.gui.models.list_models import NodeListModel
from dafree.settings import Settings

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def flush_deferred_qt_deletes(qtbot: QtBot) -> Iterator[None]:
    """Release model/tester objects before native module shutdown."""
    yield
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _tree(root: Path, files: int = 3) -> api.Tree:
    entries = [MockEntry(root, api.EntryKind.DIR)] + [
        MockEntry(root / f"file{i}.bin", size=(i + 1) * 1024, alloc=(i + 1) * 4096)
        for i in range(files)
    ]
    return api.scan(api.ScanRequest([root]), backend=make_mock_backend(MockSpec(entries))).tree


def _nodes(tree: api.Tree) -> list[int]:
    return api.top_n(tree, n=600)


def test_node_list_model_qt_contract_and_rank_order(tmp_path: Path) -> None:
    tree = _tree(tmp_path / "model")
    nodes = _nodes(tree)
    model = NodeListModel(tree, nodes, Settings())
    tester = QAbstractItemModelTester(
        model, QAbstractItemModelTester.FailureReportingMode.Fatal, model
    )
    assert tester.model() is model
    assert model.rowCount() == 3
    assert model.columnCount() == 4
    assert [model.node_at(i) for i in range(3)] == nodes
    assert model.data(model.index(0, 0)) == "file2.bin"
    assert model.data(model.index(0, 3)) == _display_text(tree.path(nodes[0]))
    assert model.data(model.index(0, 0), Qt.ItemDataRole.ToolTipRole) == tree.path(nodes[0])
    assert model.rowCount(model.index(0, 0)) == 0
    assert model.columnCount(model.index(0, 0)) == 0
    assert not model.flags(model.index(0, 0)) & Qt.ItemFlag.ItemIsEditable
    assert not model.setData(model.index(0, 0), "changed")
    assert model.data(QModelIndex()) is None
    assert model.data(model.index(0, 0), Qt.ItemDataRole.DecorationRole) is None
    assert model.headerData(-1, Qt.Orientation.Horizontal) is None
    assert model.headerData(4, Qt.Orientation.Horizontal) is None
    assert model.headerData(0, Qt.Orientation.Vertical) is None
    assert model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole) is None
    assert [model.headerData(i, Qt.Orientation.Horizontal) for i in range(4)] == [
        "Name",
        "Size",
        "Allocated",
        "Path",
    ]
    with pytest.raises(IndexError):
        model.node_at(-1)
    with pytest.raises(IndexError):
        model.node_at(3)
    other = NodeListModel(None, [], Settings())
    assert model.data(other.createIndex(0, 0)) is None
    other.deleteLater()
    model.deleteLater()


def test_node_list_model_fetches_and_evicts_bounded_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = _tree(tmp_path / "pages", files=600)
    nodes = _nodes(tree)
    calls: list[int] = []
    original = tree.node

    def counted(node: int) -> api.NodeInfo:
        calls.append(node)
        return original(node)

    monkeypatch.setattr(tree, "node", counted)
    model = NodeListModel(tree, nodes, Settings())
    assert not calls
    assert model.node_at(0) == nodes[0]
    assert model.rowCount() == 600
    assert model.data(model.index(0, 0), Qt.ItemDataRole.DecorationRole) is None
    assert model.data(model.index(0, 1), Qt.ItemDataRole.TextAlignmentRole) is not None
    assert not calls
    for column in range(4):
        assert model.data(model.index(0, column)) is not None
    assert calls == nodes[:64]
    assert model.data(model.index(63, 0)) is not None
    assert len(calls) == 64
    for row in range(64, 512, 64):
        model.data(model.index(row, 0))
    assert len(model._pages) == 8
    model.data(model.index(0, 0))  # Keep page zero recent.
    model.data(model.index(512, 0))
    assert len(model._pages) == 8
    assert len(calls) == 576
    model.data(model.index(0, 0))
    assert len(calls) == 576
    model.data(model.index(64, 0))  # Page one was evicted.
    assert len(calls) == 640
    model.deleteLater()


def test_node_list_model_reset_releases_old_scan_pages_and_copies_ranking(tmp_path: Path) -> None:
    first, second = _tree(tmp_path / "first"), _tree(tmp_path / "second")
    nodes = _nodes(first)
    model = NodeListModel(first, nodes, Settings())
    nodes.clear()
    assert model.rowCount() == 3
    assert "first" in model.data(model.index(0, 3))
    current = QPersistentModelIndex(model.index(0, 0))
    resets = QSignalSpy(model.modelReset)
    model.set_nodes(second, list(reversed(_nodes(second))))
    assert resets.count() == 1
    assert not current.isValid()
    assert not model._pages
    assert model.tree is second
    assert model.data(model.index(0, 0)) == "file0.bin"
    assert "second" in model.data(model.index(0, 3))
    with pytest.raises(IndexError):
        model.set_nodes(second, [len(second)])
    assert model.rowCount() == 3
    model.set_nodes(None, [])
    assert model.tree is None
    assert model.rowCount() == 0
    assert not model._pages
    with pytest.raises(IndexError):
        model.set_nodes(None, [0])
    model.deleteLater()


def test_node_list_model_refreshes_units_without_fetching_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = _tree(tmp_path / "units")
    settings = Settings(units=api.UnitMode.BYTES)
    original = tree.node

    def approximate(node: int) -> api.NodeInfo:
        info = original(node)
        return replace(info, flags=info.flags | api.NodeFlags.ALLOC_UNRELIABLE)

    monkeypatch.setattr(tree, "node", approximate)
    model = NodeListModel(tree, _nodes(tree), settings)
    info = tree.node(model.node_at(0))
    assert model.data(model.index(0, 1)) == _format_size(
        info.size, settings.units, settings.unit_style
    )
    assert model.data(model.index(0, 2)) == "≈" + _format_size(
        info.alloc, settings.units, settings.unit_style
    )
    cached = tuple(model._pages.values())
    events, headers = QSignalSpy(model.dataChanged), QSignalSpy(model.headerDataChanged)
    settings.units = api.UnitMode.KILO
    model.refresh_settings()
    assert events.count() == headers.count() == 1
    assert tuple(model._pages.values()) == cached
    assert model.data(model.index(0, 1)) == _format_size(
        info.size, settings.units, settings.unit_style
    )
    label = model.data(model.index(0, 0), Qt.ItemDataRole.AccessibleTextRole)
    assert tree.name(info.id) in label
    assert tree.path(info.id) in label
    assert _format_size(info.size, settings.units, settings.unit_style) in label
    model.deleteLater()
