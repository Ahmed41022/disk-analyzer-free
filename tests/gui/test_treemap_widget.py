"""Treemap selection, zoom, tooltip, rendering lifetime, and accessibility."""

# ruff: noqa: PLR2004 -- fixed geometry, child counts, and exact UI labels are assertions.

import os
import threading
from collections.abc import Iterator
from importlib.util import find_spec
from math import ceil
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

if find_spec("PySide6") is None:
    if os.environ.get("DAFREE_REQUIRE_GUI") == "1":
        pytest.fail("PySide6 is required when DAFREE_REQUIRE_GUI=1", pytrace=False)
    pytest.skip("PySide6 is not installed", allow_module_level=True)

from PySide6.QtCore import QCoreApplication, QEvent, QLocale, QPoint, Qt
from PySide6.QtGui import QAccessible, QContextMenuEvent
from PySide6.QtWidgets import QApplication, QWidget

from dafree import api
from dafree.api.testing import MockEntry, MockSpec, make_mock_backend
from dafree.gui.controllers.task_runner import TaskRunner
from dafree.gui.main_window import MainWindow
from dafree.gui.views import tree_tab as tree_tab_module
from dafree.gui.views.tree_tab import TreeTab
from dafree.gui.views.treemap_tab import TreemapTab
from dafree.gui.widgets import treemap as treemap_widget_module
from dafree.gui.widgets.treemap import TreemapWidget
from dafree.paths import AppPaths
from dafree.settings import Settings, TreemapSettings

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def flush_deferred_qt_deletes(qapp: QApplication) -> Iterator[None]:
    """Run qtbot's queued deleteLater requests before the native module shuts down."""
    yield
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _make_tree(root: Path, *, count: int = 12, prefix: str = "file") -> api.Tree:
    entries = [
        MockEntry(root, api.EntryKind.DIR),
        MockEntry(root / "folder", api.EntryKind.DIR),
        MockEntry(root / "folder/nested.bin", size=7),
        MockEntry(root / "large.bin", size=100),
    ]
    entries.extend(
        MockEntry(root / f"{prefix}{index}.bin", size=index + 1) for index in range(count)
    )
    return api.scan(api.ScanRequest([root]), backend=make_mock_backend(MockSpec(entries))).tree


def _point_for(widget: TreemapWidget, node: int, *, directory_edge: bool = False) -> QPoint:
    """Find a point that hit-tests as the node, then convert it to Qt logical pixels."""
    assert widget.layout_result is not None
    rects = widget.layout_result.rects
    match = next(rect for rect in rects if int(rect["node"]) == node)
    scale = widget.devicePixelRatioF()
    if directory_edge:
        x = float(match["x"]) + float(match["w"]) / 2
        y = float(match["y"]) + 2.0
        point = QPoint(round(x / scale), ceil(y / scale))
    else:
        x = float(match["x"]) + float(match["w"]) / 2
        y = float(match["y"]) + float(match["h"]) / 2
        point = QPoint(round(x / scale), round(y / scale))
    assert widget.layout_result.hit_test(point.x() * scale, point.y() * scale) == node
    return point


@pytest.fixture
def treemap(qtbot: QtBot) -> Iterator[tuple[TreemapWidget, TaskRunner]]:
    runner = TaskRunner()
    widget = TreemapWidget(Settings(), runner)
    qtbot.addWidget(widget)
    widget.resize(640, 420)
    widget.show()
    yield widget, runner
    qtbot.waitUntil(lambda: not runner.busy, timeout=5000)
    runner.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _set_tree(widget: TreemapWidget, qtbot: QtBot, tree: api.Tree) -> None:
    with qtbot.waitSignal(widget.ready, timeout=5000):
        widget.set_tree(tree)


def test_click_selects_node_in_tree(qtbot: QtBot, tmp_path: Path) -> None:
    """A treemap click selects the corresponding node in the lazily built tree table."""
    root = tmp_path / "scan"
    tree = _make_tree(root)
    file_node = tree.find_path(root / "folder/nested.bin")
    root_file = tree.find_path(root / "large.bin")
    assert file_node is not None and root_file is not None
    window = MainWindow(
        paths=AppPaths(
            tmp_path / "config", tmp_path / "data", tmp_path / "logs", tmp_path / "snapshots", False
        ),
        settings=Settings(),
        scan_backend=make_mock_backend(
            MockSpec(
                [
                    MockEntry(root, api.EntryKind.DIR),
                    MockEntry(root / "folder", api.EntryKind.DIR),
                    MockEntry(root / "folder/nested.bin", size=7),
                    MockEntry(root / "large.bin", size=100),
                ]
                + [MockEntry(root / f"file{i}.bin", size=i + 1) for i in range(12)]
            )
        ),
        volume_provider=lambda: [],
    )

    def finish(widget: QWidget) -> None:
        widget.close()
        qtbot.waitUntil(
            lambda: not window.controller.running and not window.runner.busy, timeout=10_000
        )

    qtbot.addWidget(window, before_close_func=finish)
    window.show()
    with qtbot.waitSignal(window.controller.finished, timeout=5000):
        window.start_scan(api.ScanRequest([root], threads=1))
    tree_page = window._pages["tree"]
    assert isinstance(tree_page, TreeTab)
    qtbot.waitUntil(lambda: tree_page.table is not None, timeout=5000)
    window.show_tab("treemap")
    page = window._pages["treemap"]
    widget = page.widget
    qtbot.waitUntil(lambda: widget.layout_result is not None, timeout=5000)
    qtbot.mouseClick(widget, Qt.MouseButton.LeftButton, pos=_point_for(widget, file_node))
    qtbot.waitUntil(
        lambda: (
            tree_page.table is not None
            and tree_page.table.tree_model.node_at(tree_page.table.currentIndex().row())
            == file_node
        ),
        timeout=5000,
    )
    row = tree_page.table.tree_model.row_of(root_file)
    assert row is not None
    tree_page.table.setCurrentIndex(tree_page.table.tree_model.index(row, 0))
    qtbot.waitUntil(lambda: widget.selected_node == root_file, timeout=5000)


def test_double_click_zooms_and_breadcrumb_returns(qtbot: QtBot, tmp_path: Path) -> None:
    """Double-clicking a directory zooms in; its breadcrumb parent returns to the scan root."""
    tree = _make_tree(tmp_path / "zoom")
    directory = tree.find_path(tmp_path / "zoom/folder")
    assert directory is not None
    runner = TaskRunner()
    settings = Settings(treemap=TreemapSettings(header_px=12))
    tab = TreemapTab(settings, runner)
    qtbot.addWidget(tab)
    tab.resize(640, 420)
    tab.show()
    with qtbot.waitSignal(tab.widget.ready, timeout=5000):
        tab.set_tree(tree)
    qtbot.mouseDClick(
        tab.widget,
        Qt.MouseButton.LeftButton,
        pos=_point_for(tab.widget, directory, directory_edge=True),
    )
    qtbot.waitUntil(lambda: tab.widget.zoom_root == directory, timeout=5000)
    assert tab.breadcrumb.up.isEnabled()
    tab.breadcrumb.up.click()
    qtbot.waitUntil(lambda: tab.widget.zoom_root == tree.roots()[0], timeout=5000)
    qtbot.waitUntil(lambda: not runner.busy, timeout=5000)
    runner.deleteLater()


def test_tooltip_text(qtbot: QtBot, treemap, tmp_path: Path) -> None:
    """Tooltips identify the native filename, readable size, and zoom-root percentage."""
    widget, _runner = treemap
    tree = _make_tree(tmp_path / "tooltip")
    file_node = tree.find_path(tmp_path / "tooltip/folder/nested.bin")
    directory = tree.find_path(tmp_path / "tooltip/folder")
    assert file_node is not None and directory is not None
    _set_tree(widget, qtbot, tree)
    with qtbot.waitSignal(widget.ready, timeout=5000):
        widget.zoom_to(directory)
    expected = (
        f"{tree.name(file_node)}\nSize: {api.format_size(tree.node(file_node).size)}\n"
        f"{QLocale().toString(100.0, 'f', 1)}% of zoom root"
    )
    qtbot.mouseMove(widget, pos=_point_for(widget, file_node))
    assert widget.toolTip() == expected
    assert widget.tooltip_for(file_node) == expected


def test_accessible_children_count(qtbot: QtBot, treemap, tmp_path: Path) -> None:
    """Accessibility exposes at most the 50 largest real rectangles with useful names."""
    widget, _runner = treemap
    tree = _make_tree(tmp_path / "accessible", count=70)
    _set_tree(widget, qtbot, tree)
    interface = QAccessible.queryAccessibleInterface(widget)
    assert interface is not None
    assert interface.childCount() == 50
    accessible_names = [
        interface.child(index).text(QAccessible.Text.Name)
        for index in range(interface.childCount())
    ]
    expected_names = {
        f"{tree.name(node)}, {api.format_size(tree.node(node).size)}"
        for node in range(1, len(tree))
    }
    assert all(name in expected_names for name in accessible_names)
    assert all(", " in name for name in accessible_names)
    assert widget.layout_result is not None
    real = [
        rect
        for rect in widget.layout_result.rects
        if not int(rect["flags"]) & int(api.TmFlags.OTHER)
        and float(rect["w"]) > 0
        and float(rect["h"]) > 0
    ]
    ranked = sorted(real, key=lambda rect: -float(rect["w"]) * float(rect["h"]))[:50]
    expected_largest = {
        f"{tree.name(int(rect['node']))}, {api.format_size(tree.node(int(rect['node'])).size)}"
        for rect in ranked
    }
    assert set(accessible_names) == expected_largest
    largest = tree.find_path(tmp_path / "accessible/file69.bin")
    assert largest is not None
    assert f"{tree.name(largest)}, {api.format_size(tree.node(largest).size)}" in accessible_names


def test_image_keeps_render_buffer_and_tracks_device_pixel_ratio(
    qtbot: QtBot, treemap, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The QImage remains backed by the widget-owned bytes at device-pixel dimensions."""
    widget, _runner = treemap
    widget.resize(320, 200)
    monkeypatch.setattr(TreemapWidget, "devicePixelRatioF", lambda _self: 2.0)
    tree = _make_tree(tmp_path / "buffer")
    _set_tree(widget, qtbot, tree)
    assert not widget.image.isNull()
    assert widget.render_buffer
    assert widget.image.sizeInBytes() == len(widget.render_buffer)
    assert bytes(widget.image.constBits()) == widget.render_buffer
    ratio = widget.devicePixelRatioF()
    assert abs(widget.image.width() - round(widget.width() * ratio)) <= 1
    assert abs(widget.image.height() - round(widget.height() * ratio)) <= 1
    assert widget.image.devicePixelRatio() == ratio
    node = tree.find_path(tmp_path / "buffer/large.bin")
    assert node is not None
    qtbot.mouseClick(widget, Qt.MouseButton.LeftButton, pos=_point_for(widget, node))
    assert widget.selected_node == node
    monkeypatch.setattr(TreemapWidget, "devicePixelRatioF", lambda _self: 1.5)
    with qtbot.waitSignal(widget.ready, timeout=5000):
        QCoreApplication.sendEvent(widget, QEvent(QEvent.Type.DevicePixelRatioChange))
    assert widget.image.devicePixelRatio() == 1.5
    assert widget.image.width() == 480
    assert widget.image.height() == 300


def test_flat_colours_disable_cushion_shading(qtbot: QtBot, tmp_path: Path) -> None:
    """The persisted flat-colours option removes cushion shading for identical input."""
    tree = _make_tree(tmp_path / "flat")
    settings = Settings(treemap=TreemapSettings(flat_colours=True))
    runner = TaskRunner()
    widget = TreemapWidget(settings, runner)
    qtbot.addWidget(widget)
    widget.resize(500, 300)
    widget.show()
    _set_tree(widget, qtbot, tree)
    flat = widget.render_buffer
    settings.treemap.flat_colours = False
    widget.refresh_settings()
    qtbot.waitUntil(lambda: widget.render_buffer != flat, timeout=5000)
    assert widget.render_buffer != flat
    qtbot.waitUntil(lambda: not runner.busy, timeout=5000)
    runner.deleteLater()


def test_resize_renders_latest_geometry_after_a_burst(
    qtbot: QtBot, treemap, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A resize burst triggers one render after the widget's 150 ms debounce."""
    widget, _runner = treemap
    _set_tree(widget, qtbot, _make_tree(tmp_path / "resize"))
    assert widget._resize_timer.interval() == 150
    render_calls: list[tuple[int, int]] = []
    original_render = treemap_widget_module._render

    def counting_render(request):
        render_calls.append((request.width, request.height))
        return original_render(request)

    monkeypatch.setattr(treemap_widget_module, "_render", counting_render)
    with qtbot.waitSignal(widget.ready, timeout=5000):
        widget.resize(720, 460)
        widget.resize(660, 420)
        widget.resize(540, 360)
    assert len(render_calls) == 1
    assert render_calls[0] == (
        round(widget.width() * widget.devicePixelRatioF()),
        round(widget.height() * widget.devicePixelRatioF()),
    )


def test_stale_tree_result_does_not_replace_latest_tree(
    qtbot: QtBot, treemap, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A queued render for an older scan cannot publish rectangles into the new node namespace."""
    widget, runner = treemap
    old_tree = _make_tree(tmp_path / "old", count=600, prefix="old")
    new_tree = _make_tree(tmp_path / "new", count=8, prefix="new")
    started, release = threading.Event(), threading.Event()
    worker_threads: list[int] = []
    original_render = treemap_widget_module._render

    def gated_render(request):
        worker_threads.append(threading.get_ident())
        if request.tree is old_tree:
            started.set()
            if not release.wait(5):
                raise TimeoutError("old render gate was not released")
        return original_render(request)

    monkeypatch.setattr(treemap_widget_module, "_render", gated_render)
    widget.set_tree(old_tree)
    qtbot.waitUntil(started.is_set, timeout=5000)
    widget.set_tree(new_tree)
    try:
        release.set()
        qtbot.waitUntil(
            lambda: (
                widget.tree is new_tree and widget.layout_result is not None and not runner.busy
            ),
            timeout=5000,
        )
    finally:
        release.set()
    assert widget.tree is new_tree
    assert worker_threads
    assert all(thread_id != threading.get_ident() for thread_id in worker_threads)
    assert widget.layout_result is not None
    expected = api.treemap_layout(
        new_tree,
        new_tree.roots()[0],
        widget.layout_result.width,
        widget.layout_result.height,
        api.TreemapOptions(),
    )
    assert widget.layout_result.rects.tolist() == expected.rects.tolist()
    widget.clear()
    assert widget.tree is None
    assert widget.layout_result is None
    assert widget.render_buffer == b""


def test_context_menu_forwards_node_and_global_position(qtbot: QtBot, tmp_path: Path) -> None:
    """Treemap context actions forward the real node and global pointer position."""
    tree = _make_tree(tmp_path / "menu")
    file_node = tree.find_path(tmp_path / "menu/large.bin")
    assert file_node is not None
    runner = TaskRunner()
    tab = TreemapTab(Settings(), runner)
    qtbot.addWidget(tab)
    tab.resize(640, 420)
    tab.show()
    with qtbot.waitSignal(tab.widget.ready, timeout=5000):
        tab.set_tree(tree)
    point = _point_for(tab.widget, file_node)
    global_point = tab.widget.mapToGlobal(point)
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, global_point)
    with qtbot.waitSignal(tab.contextMenuRequested, timeout=5000) as requested:
        QCoreApplication.sendEvent(tab.widget, event)
    assert requested.args == [tree, file_node, global_point]
    qtbot.waitUntil(lambda: not runner.busy, timeout=5000)
    runner.deleteLater()


@pytest.mark.parametrize("selection_route", ["treemap", "table"])
def test_latest_selection_wins_during_hidden_ancestor_expansion(
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    selection_route: str,
) -> None:
    """A newer visible selection supersedes a queued hidden-node expansion result."""
    root = tmp_path / "selection-race"
    backend = make_mock_backend(
        MockSpec(
            [
                MockEntry(root, api.EntryKind.DIR),
                MockEntry(root / "folder", api.EntryKind.DIR),
                MockEntry(root / "folder/nested.bin", size=7),
                MockEntry(root / "visible.bin", size=100),
            ]
        )
    )
    paths = AppPaths(
        tmp_path / "config", tmp_path / "data", tmp_path / "logs", tmp_path / "snapshots", False
    )
    window = MainWindow(
        paths=paths,
        settings=Settings(),
        scan_backend=backend,
        volume_provider=lambda: [],
    )

    def finish(widget: QWidget) -> None:
        widget.close()
        qtbot.waitUntil(
            lambda: not window.controller.running and not window.runner.busy, timeout=10_000
        )

    qtbot.addWidget(window, before_close_func=finish)
    window.show()
    with qtbot.waitSignal(window.controller.finished, timeout=5000):
        window.start_scan(api.ScanRequest([root], threads=1))
    tree_page = window._pages["tree"]
    assert isinstance(tree_page, TreeTab)
    qtbot.waitUntil(lambda: tree_page.table is not None, timeout=5000)
    tree = window._latest_tree
    assert tree is not None and tree_page.table is not None
    table = tree_page.table
    hidden = tree.find_path(root / "folder/nested.bin")
    visible = tree.find_path(root / "visible.bin")
    assert hidden is not None and visible is not None
    visible_row = table.tree_model.row_of(visible)
    assert visible_row is not None

    started, release = threading.Event(), threading.Event()
    original_tree_view = tree_tab_module.api.TreeView

    def gated_tree_view(tree_arg: api.Tree, options: api.ViewOptions) -> api.TreeView:
        started.set()
        if not release.wait(5):
            raise TimeoutError("tree-view preparation gate was not released")
        return original_tree_view(tree_arg, options)

    monkeypatch.setattr(tree_tab_module.api, "TreeView", gated_tree_view)
    if selection_route == "treemap":
        window._treemap_selected(tree, hidden)
    else:
        tree_page.select_node(hidden)
    qtbot.waitUntil(started.is_set, timeout=5000)
    try:
        if selection_route == "treemap":
            window._treemap_selected(tree, visible)
        else:
            table.setCurrentIndex(table.tree_model.index(visible_row, 0))
        release.set()
        qtbot.waitUntil(lambda: not window.runner.busy, timeout=5000)
    finally:
        release.set()
    current_table = tree_page.table
    assert current_table is not None
    selected_row = current_table.currentIndex().row()
    assert current_table.tree_model.node_at(selected_row) == visible
