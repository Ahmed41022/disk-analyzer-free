"""Top-N ranking, scope, background-result ownership, and tree integration."""

# ruff: noqa: PLR2004 -- fixed fixture counts, sizes, and column IDs are assertions.

import os
import threading
from collections.abc import Iterator
from importlib.util import find_spec
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

if find_spec("PySide6") is None:
    if os.environ.get("DAFREE_REQUIRE_GUI") == "1":
        pytest.fail("PySide6 is required when DAFREE_REQUIRE_GUI=1", pytrace=False)
    pytest.skip("PySide6 is not installed", allow_module_level=True)

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from dafree import api
from dafree.api.testing import MockEntry, MockSpec, make_mock_backend
from dafree.gui.controllers.task_runner import TaskRunner
from dafree.gui.main_window import MainWindow
from dafree.gui.views import top_tab as top_tab_module
from dafree.gui.views.top_tab import TopTab
from dafree.gui.views.tree_tab import TreeTab
from dafree.paths import AppPaths
from dafree.settings import Settings

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def flush_deferred_qt_deletes(qapp: QApplication) -> Iterator[None]:
    """Release qtbot's queued widgets before the native module shuts down."""
    yield
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def top_tab(qtbot: QtBot) -> Iterator[tuple[TopTab, TaskRunner]]:
    runner = TaskRunner()
    tab = TopTab(Settings(), runner)
    qtbot.addWidget(tab)
    tab.resize(900, 500)
    tab.show()
    yield tab, runner
    qtbot.waitUntil(lambda: not runner.busy, timeout=5000)
    runner.deleteLater()


def _entries(root: Path) -> list[MockEntry]:
    return [
        MockEntry(root, api.EntryKind.DIR),
        MockEntry(root / "branch", api.EntryKind.DIR),
        MockEntry(root / "branch/leaf", api.EntryKind.DIR),
        MockEntry(root / "branch/leaf/huge.bin", size=9000),
        MockEntry(root / "branch/direct.bin", size=1000),
        MockEntry(root / "other", api.EntryKind.DIR),
        MockEntry(root / "other/small.bin", size=10),
        MockEntry(root / "loose.bin", size=500),
    ]


def _make_tree(root: Path) -> api.Tree:
    return api.scan(
        api.ScanRequest([root], threads=1), backend=make_mock_backend(MockSpec(_entries(root)))
    ).tree


def _set_tree(tab: TopTab, qtbot: QtBot, tree: api.Tree) -> None:
    with qtbot.waitSignal(tab.ready, timeout=5000):
        tab.set_tree(tree)


def _paths(tab: TopTab) -> list[str]:
    assert tab.tree is not None
    return [tab.tree.path(tab.model.node_at(row)) for row in range(tab.model.rowCount())]


@pytest.mark.parametrize("limit", [20, 50, 100, 500])
def test_top_files_sorted_desc_n_rows(
    qtbot: QtBot, tmp_path: Path, top_tab: tuple[TopTab, TaskRunner], limit: int
) -> None:
    root = tmp_path / "ranked"
    count = 530
    entries = [MockEntry(root, api.EntryKind.DIR)] + [
        MockEntry(root / f"file{number}.bin", size=number, alloc=number * 2)
        for number in range(1, count + 1)
    ]
    tree = api.scan(
        api.ScanRequest([root], threads=1), backend=make_mock_backend(MockSpec(entries))
    ).tree
    tab, _ = top_tab
    tab.limit.setCurrentIndex(tab.limit.findData(limit))
    _set_tree(tab, qtbot, tree)
    assert tab.model.rowCount() == limit
    assert _paths(tab) == [
        str(root / f"file{number}.bin") for number in range(count, count - limit, -1)
    ]
    assert [tree.node(tab.model.node_at(row)).size for row in range(limit)] == list(
        range(count, count - limit, -1)
    )
    assert not tab.leaf_only.isEnabled()


def test_folder_toggle_and_leaf_filter_preserve_native_ranking(
    qtbot: QtBot, tmp_path: Path, top_tab: tuple[TopTab, TaskRunner]
) -> None:
    root = tmp_path / "folders"
    tree = _make_tree(root)
    tab, _ = top_tab
    _set_tree(tab, qtbot, tree)
    with qtbot.waitSignal(tab.ready, timeout=5000):
        tab.kind.setCurrentIndex(tab.kind.findData(api.TopKind.DIRS))
    assert tab.leaf_only.isEnabled()
    assert _paths(tab) == [
        str(root),
        str(root / "branch"),
        str(root / "branch/leaf"),
        str(root / "other"),
    ]
    with qtbot.waitSignal(tab.ready, timeout=5000):
        tab.leaf_only.setChecked(True)
    assert _paths(tab) == [str(root / "branch/leaf"), str(root / "other")]
    with qtbot.waitSignal(tab.ready, timeout=5000):
        tab.kind.setCurrentIndex(tab.kind.findData(api.TopKind.FILES))
    assert not tab.leaf_only.isEnabled()
    assert _paths(tab) == [
        str(root / "branch/leaf/huge.bin"),
        str(root / "branch/direct.bin"),
        str(root / "loose.bin"),
        str(root / "other/small.bin"),
    ]


def test_scope_includes_descendants_and_selected_file_uses_parent(
    qtbot: QtBot, tmp_path: Path, top_tab: tuple[TopTab, TaskRunner]
) -> None:
    root = tmp_path / "scope"
    tree = _make_tree(root)
    branch = tree.find_path(root / "branch")
    nested_file = tree.find_path(root / "branch/leaf/huge.bin")
    leaf = tree.find_path(root / "branch/leaf")
    assert branch is not None and nested_file is not None and leaf is not None
    tab, _ = top_tab
    _set_tree(tab, qtbot, tree)
    with qtbot.waitSignal(tab.ready, timeout=5000):
        tab.select_node(branch)
    assert tab.scope == branch
    assert _paths(tab) == [str(root / "branch/leaf/huge.bin"), str(root / "branch/direct.bin")]
    with qtbot.waitSignal(tab.ready, timeout=5000):
        tab.select_node(nested_file)
    assert tab.scope == leaf
    assert _paths(tab) == [str(root / "branch/leaf/huge.bin")]


def test_empty_scope_and_clear_remove_prior_results(
    qtbot: QtBot, tmp_path: Path, top_tab: tuple[TopTab, TaskRunner]
) -> None:
    tab, _ = top_tab
    _set_tree(tab, qtbot, _make_tree(tmp_path / "populated"))
    root = tmp_path / "empty"
    tree = api.scan(
        api.ScanRequest([root]),
        backend=make_mock_backend(MockSpec([MockEntry(root, api.EntryKind.DIR)])),
    ).tree
    _set_tree(tab, qtbot, tree)
    assert tab.model.rowCount() == 0
    tab.clear()
    assert tab.tree is None and tab.scope is None
    assert tab.model.rowCount() == 0


def test_path_and_units_follow_settings_without_replacing_results(
    qtbot: QtBot, tmp_path: Path
) -> None:
    settings = Settings()
    runner = TaskRunner()
    tab = TopTab(settings, runner)
    qtbot.addWidget(tab)
    tree = _make_tree(tmp_path / "units")
    _set_tree(tab, qtbot, tree)
    nodes = [tab.model.node_at(row) for row in range(tab.model.rowCount())]
    assert tab.model.data(tab.model.index(0, 3)) == tree.path(nodes[0])
    settings.units = api.UnitMode.BYTES
    tab.refresh_settings()
    assert tab.model.data(tab.model.index(0, 1)) == api.format_size(
        9000, settings.units, settings.unit_style
    )
    assert [tab.model.node_at(row) for row in range(tab.model.rowCount())] == nodes
    qtbot.waitUntil(lambda: not runner.busy, timeout=5000)
    runner.deleteLater()


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter])
def test_keyboard_activation_emits_ranked_node_identity(
    qtbot: QtBot, tmp_path: Path, top_tab: tuple[TopTab, TaskRunner], key: Qt.Key
) -> None:
    tab, _ = top_tab
    tree = _make_tree(tmp_path / "keyboard")
    _set_tree(tab, qtbot, tree)
    tab.table.setCurrentIndex(tab.model.index(1, 0))
    tab.table.setFocus()
    emissions = QSignalSpy(tab.nodeSelected)
    with qtbot.waitSignal(tab.nodeSelected, timeout=5000) as activated:
        qtbot.keyClick(tab.table, key)
    assert activated.args == [tree, tab.model.node_at(1)]
    assert emissions.count() == 1


def test_context_menu_uses_clicked_ranked_node(
    qtbot: QtBot, tmp_path: Path, top_tab: tuple[TopTab, TaskRunner]
) -> None:
    tab, _ = top_tab
    tree = _make_tree(tmp_path / "menu")
    _set_tree(tab, qtbot, tree)
    point = tab.table.visualRect(tab.model.index(2, 0)).center()
    global_point = tab.table.viewport().mapToGlobal(point)
    menu = QSignalSpy(tab.contextMenuRequested)
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, global_point)
    QApplication.sendEvent(tab.table.viewport(), event)
    assert menu.count() == 1
    args = menu.at(0)
    assert args[0] is tree
    assert args[1] == tab.model.node_at(2)
    assert args[2] == global_point


def test_old_scan_result_cannot_replace_new_scan(
    qtbot: QtBot,
    tmp_path: Path,
    top_tab: tuple[TopTab, TaskRunner],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tab, runner = top_tab
    old_tree = _make_tree(tmp_path / "old")
    new_root = tmp_path / "new"
    new_tree = _make_tree(new_root)
    started, release = threading.Event(), threading.Event()
    original = top_tab_module._prepare

    def gated_prepare(tree, scope, kind, n, leaf_only):
        if tree is old_tree:
            started.set()
            if not release.wait(5):
                raise TimeoutError("top preparation gate was not released")
        return original(tree, scope, kind, n, leaf_only)

    monkeypatch.setattr(top_tab_module, "_prepare", gated_prepare)
    ready = QSignalSpy(tab.ready)
    tab.set_tree(old_tree)
    qtbot.waitUntil(started.is_set, timeout=5000)
    try:
        tab.set_tree(new_tree)
        with qtbot.waitSignal(tab.ready, timeout=5000):
            release.set()
        qtbot.waitUntil(lambda: not runner.busy, timeout=5000)
    finally:
        release.set()
    assert ready.count() == 1
    assert tab.tree is new_tree
    assert _paths(tab)[0] == str(new_root / "branch/leaf/huge.bin")


def test_clear_discards_inflight_result(
    qtbot: QtBot,
    tmp_path: Path,
    top_tab: tuple[TopTab, TaskRunner],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tab, runner = top_tab
    tree = _make_tree(tmp_path / "cleared")
    started, release = threading.Event(), threading.Event()
    original = top_tab_module._prepare

    def gated_prepare(tree, scope, kind, n, leaf_only):
        started.set()
        if not release.wait(5):
            raise TimeoutError("top preparation gate was not released")
        return original(tree, scope, kind, n, leaf_only)

    monkeypatch.setattr(top_tab_module, "_prepare", gated_prepare)
    ready = QSignalSpy(tab.ready)
    tab.set_tree(tree)
    qtbot.waitUntil(started.is_set, timeout=5000)
    try:
        tab.clear()
        release.set()
        qtbot.waitUntil(lambda: not runner.busy, timeout=5000)
    finally:
        release.set()
    assert ready.count() == 0
    assert tab.tree is None and tab.scope is None
    assert tab.model.rowCount() == 0


def test_rapid_scope_and_option_changes_only_publish_latest_request(
    qtbot: QtBot,
    tmp_path: Path,
    top_tab: tuple[TopTab, TaskRunner],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tab, runner = top_tab
    root = tmp_path / "coalesced"
    tree = _make_tree(root)
    branch = tree.find_path(root / "branch")
    assert branch is not None
    started, release = threading.Event(), threading.Event()
    original = top_tab_module._prepare
    calls = []

    def gated_prepare(tree, scope, kind, n, leaf_only):
        calls.append((tree, scope, kind, n, leaf_only))
        if len(calls) == 1:
            started.set()
            if not release.wait(5):
                raise TimeoutError("top preparation gate was not released")
        return original(tree, scope, kind, n, leaf_only)

    monkeypatch.setattr(top_tab_module, "_prepare", gated_prepare)
    ready = QSignalSpy(tab.ready)
    tab.set_tree(tree)
    qtbot.waitUntil(started.is_set, timeout=5000)
    try:
        tab.select_node(branch)
        tab.kind.setCurrentIndex(tab.kind.findData(api.TopKind.DIRS))
        tab.leaf_only.setChecked(True)
        tab.limit.setCurrentIndex(tab.limit.findData(50))
        with qtbot.waitSignal(tab.ready, timeout=5000):
            release.set()
        qtbot.waitUntil(lambda: not runner.busy, timeout=5000)
    finally:
        release.set()
    assert len(calls) == 2
    assert calls[-1] == (tree, branch, api.TopKind.DIRS, 50, True)
    assert ready.count() == 1
    assert tab.scope == branch
    assert _paths(tab) == [str(root / "branch/leaf")]


def test_worker_failure_is_reported_and_next_request_recovers(
    qtbot: QtBot,
    tmp_path: Path,
    top_tab: tuple[TopTab, TaskRunner],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tab, runner = top_tab
    tree = _make_tree(tmp_path / "recovery")
    original = top_tab_module._prepare
    calls = 0

    def fail_first(tree, scope, kind, n, leaf_only):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("deliberate preparation failure")
        return original(tree, scope, kind, n, leaf_only)

    monkeypatch.setattr(top_tab_module, "_prepare", fail_first)
    ready = QSignalSpy(tab.ready)
    tab.set_tree(tree)
    qtbot.waitUntil(lambda: not runner.busy, timeout=5000)
    assert "deliberate preparation failure" in tab.message.text()
    assert tab.message.isVisible()
    assert tab.model.rowCount() == 0
    assert ready.count() == 0
    with qtbot.waitSignal(tab.ready, timeout=5000):
        tab.limit.setCurrentIndex(tab.limit.findData(50))
    assert tab.model.rowCount() == 4
    assert not tab.message.isVisible()
    assert ready.count() == 1


def test_multiple_targets_start_at_combined_root_and_breadcrumb_returns(
    qtbot: QtBot, tmp_path: Path, top_tab: tuple[TopTab, TaskRunner]
) -> None:
    tab, _ = top_tab
    roots = [tmp_path / "first", tmp_path / "second"]
    tree = api.scan(
        api.ScanRequest(roots, threads=1),
        backend=make_mock_backend(MockSpec(_entries(roots[0]) + _entries(roots[1]))),
    ).tree
    _set_tree(tab, qtbot, tree)
    assert tab.scope == 0
    assert tab.model.rowCount() == 8
    first_root = tree.find_path(roots[0])
    assert first_root is not None
    with qtbot.waitSignal(tab.ready, timeout=5000):
        tab.select_node(first_root)
    assert tab.model.rowCount() == 4
    with qtbot.waitSignal(tab.ready, timeout=5000):
        tab.breadcrumb.up.click()
    assert tab.scope == 0
    assert tab.model.rowCount() == 8


def test_main_window_top_is_lazy_and_tree_selection_sets_scope(
    qtbot: QtBot, tmp_path: Path
) -> None:
    root = tmp_path / "main-window"
    window = MainWindow(
        paths=AppPaths(
            tmp_path / "config", tmp_path / "data", tmp_path / "logs", tmp_path / "snapshots", False
        ),
        settings=Settings(),
        scan_backend=make_mock_backend(MockSpec(_entries(root))),
        volume_provider=lambda: [],
    )

    def finish(widget) -> None:
        widget.close()
        qtbot.waitUntil(
            lambda: not window.controller.running and not window.runner.busy, timeout=10_000
        )

    qtbot.addWidget(window, before_close_func=finish)
    assert "top" not in window._pages
    window.show()
    with qtbot.waitSignal(window.controller.finished, timeout=5000):
        window.start_scan(api.ScanRequest([root], threads=1))
    tree_page = window._pages["tree"]
    assert isinstance(tree_page, TreeTab)
    qtbot.waitUntil(lambda: tree_page.table is not None, timeout=5000)
    window.show_tab("top")
    tab = window._pages["top"]
    assert isinstance(tab, TopTab)
    qtbot.waitUntil(lambda: tab.model.rowCount() == 4, timeout=5000)
    tree = tab.tree
    assert tree is not None
    branch = tree.find_path(root / "branch")
    assert branch is not None
    with qtbot.waitSignal(tab.ready, timeout=5000):
        tree_page.select_node(branch)
    assert tab.scope == branch
    assert _paths(tab) == [str(root / "branch/leaf/huge.bin"), str(root / "branch/direct.bin")]
    file_node = tab.model.node_at(0)
    tab.table.setCurrentIndex(tab.model.index(0, 0))
    qtbot.keyClick(tab.table, Qt.Key.Key_Return)

    def current_tree_node() -> int | None:
        table = tree_page.table
        if table is None or not table.currentIndex().isValid():
            return None
        return table.tree_model.node_at(table.currentIndex().row())

    qtbot.waitUntil(lambda: current_tree_node() == file_node, timeout=5000)
    qtbot.waitUntil(lambda: not window.runner.busy, timeout=5000)
    with qtbot.waitSignal(tab.ready, timeout=5000):
        tab.select_node(0)
    assert tab.scope == 0
    window.units.setCurrentIndex(1)
    window.show_tab("tree")
    window.show_tab("top")
    assert tab.scope == 0
