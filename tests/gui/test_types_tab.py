"""Extension totals, bounded charts, scoped requests, and Find handoff."""

# ruff: noqa: PLR2004 -- fixed fixture sizes, report counts, and column IDs are assertions.

import json
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

from PySide6.QtCore import QCoreApplication, QEvent, QLocale, Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from dafree import api
from dafree.api.testing import MockEntry, MockSpec, make_mock_backend
from dafree.gui import _number_translation
from dafree.gui.controllers.task_runner import TaskRunner
from dafree.gui.main_window import MainWindow
from dafree.gui.views import types_tab as types_tab_module
from dafree.gui.views.types_tab import TypesTab
from dafree.paths import AppPaths
from dafree.settings import Settings

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def flush_deferred_qt_deletes(qapp: QApplication) -> Iterator[None]:
    """Release queued widget deletions before the native module shuts down."""
    yield
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def types_tab(qtbot: QtBot) -> Iterator[tuple[TypesTab, TaskRunner]]:
    runner = TaskRunner()
    tab = TypesTab(Settings(), runner)
    qtbot.addWidget(tab)
    tab.resize(1000, 700)
    tab.show()
    yield tab, runner
    qtbot.waitUntil(lambda: not runner.busy, timeout=5000)
    runner.deleteLater()


def _entries(root: Path) -> list[MockEntry]:
    return [
        MockEntry(root, api.EntryKind.DIR),
        MockEntry(root / "sub", api.EntryKind.DIR),
        MockEntry(root / "sub/nested.TXT", size=300, alloc=512),
        MockEntry(root / "readme.txt", size=100, alloc=128),
        MockEntry(root / "photo.JPG", size=600, alloc=1024),
        MockEntry(root / "noextension", size=0, alloc=4096),
        MockEntry(root / "zero.bin", size=0, alloc=0),
    ]


def _scan(root: Path, entries: list[MockEntry] | None = None) -> api.Tree:
    return api.scan(
        api.ScanRequest([root], threads=1),
        backend=make_mock_backend(MockSpec(_entries(root) if entries is None else entries)),
    ).tree


def _set_tree(tab: TypesTab, qtbot: QtBot, tree: api.Tree) -> None:
    with qtbot.waitSignal(tab.ready, timeout=5000):
        tab.set_tree(tree)


def _rows(tab: TypesTab) -> dict[str, api.ExtStat]:
    return {
        tab.model.report_row(row).ext: tab.model.report_row(row)
        for row in range(tab.model.rowCount())
    }


def _percent(tab: TypesTab, row: int) -> float:
    text = tab.model.data(tab.model.index(row, 5))
    assert isinstance(text, str)
    value, valid = QLocale().toDouble(text.removesuffix(QLocale().percent()).strip())
    assert valid
    return value


def test_extension_table_groups_case_and_shows_counts_sizes_allocation_and_scope_share(
    qtbot: QtBot, tmp_path: Path, types_tab: tuple[TypesTab, TaskRunner]
) -> None:
    tab, _ = types_tab
    tree = _scan(tmp_path / "grouped")
    _set_tree(tab, qtbot, tree)
    assert tab.model.columnCount() == 6
    assert {ext: (row.files, row.size, row.alloc) for ext, row in _rows(tab).items()} == {
        "jpg": (1, 600, 1024),
        "txt": (2, 400, 640),
        "": (1, 0, 4096),
        "bin": (1, 0, 0),
    }
    assert _rows(tab)["jpg"].category == api.ExtCategory.IMAGE
    assert _rows(tab)["txt"].category == api.ExtCategory.DOCUMENT
    assert [tab.model.report_row(row).size for row in range(tab.model.rowCount())] == [
        600,
        400,
        0,
        0,
    ]
    for index in range(tab.model.rowCount()):
        report = tab.model.report_row(index)
        assert _percent(tab, index) == pytest.approx(report.size / 10)
    assert sum(item.value for item in tab.bar.slices) == 1000


def test_many_extensions_keep_full_table_and_fifteen_chart_groups_plus_other(
    qtbot: QtBot, tmp_path: Path, types_tab: tuple[TypesTab, TaskRunner]
) -> None:
    root = tmp_path / "wide"
    tree = _scan(
        root,
        [MockEntry(root, api.EntryKind.DIR)]
        + [MockEntry(root / f"file.ext{index}", size=index) for index in range(1, 21)],
    )
    tab, _ = types_tab
    _set_tree(tab, qtbot, tree)
    assert tab.model.rowCount() == 20
    assert len(tab.bar.slices) == 16
    other = [item for item in tab.bar.slices if item.is_other]
    assert len(other) == 1 and other[0].value == 15
    assert [item.value for item in tab.bar.slices if not item.is_other] == list(range(20, 5, -1))
    assert sum(item.value for item in tab.bar.slices) == 210


def test_zero_size_groups_have_zero_percent_and_no_invalid_bars(
    qtbot: QtBot, tmp_path: Path, types_tab: tuple[TypesTab, TaskRunner]
) -> None:
    root = tmp_path / "zero"
    tree = _scan(
        root,
        [
            MockEntry(root, api.EntryKind.DIR),
            MockEntry(root / "zero.txt", size=0, alloc=4096),
            MockEntry(root / "zero.bin", size=0, alloc=0),
        ],
    )
    tab, _ = types_tab
    _set_tree(tab, qtbot, tree)
    assert tab.model.rowCount() == 2
    assert [_percent(tab, row) for row in range(tab.model.rowCount())] == [0.0, 0.0]
    assert _rows(tab)["txt"].files == 1
    assert _rows(tab)["txt"].alloc == 4096
    assert tab.bar.slices == ()


def test_file_selection_scopes_to_parent_and_breadcrumb_returns(
    qtbot: QtBot, tmp_path: Path, types_tab: tuple[TypesTab, TaskRunner]
) -> None:
    root = tmp_path / "scope"
    tree = _scan(root)
    nested = tree.find_path(root / "sub/nested.TXT")
    parent = tree.find_path(root / "sub")
    assert nested is not None and parent is not None
    tab, _ = types_tab
    _set_tree(tab, qtbot, tree)
    with qtbot.waitSignal(tab.ready, timeout=5000):
        tab.select_node(nested)
    assert tab.scope == parent
    assert {ext: row.size for ext, row in _rows(tab).items()} == {"txt": 300}
    assert _percent(tab, 0) == 100
    with qtbot.waitSignal(tab.ready, timeout=5000):
        tab.breadcrumb.up.click()
    assert tab.scope == tree.roots()[0]
    assert tab.model.rowCount() == 4


def test_units_reformat_without_running_extension_report_again(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings()
    runner = TaskRunner()
    tab = TypesTab(settings, runner)
    qtbot.addWidget(tab)
    tree = _scan(tmp_path / "units")
    original = types_tab_module._prepare
    calls = 0

    def counting_prepare(tree, scope):
        nonlocal calls
        calls += 1
        return original(tree, scope)

    monkeypatch.setattr(types_tab_module, "_prepare", counting_prepare)
    _set_tree(tab, qtbot, tree)
    settings.units = api.UnitMode.BYTES
    tab.refresh_settings()
    assert tab.model.data(tab.model.index(0, 3)) == api.format_size(
        600, settings.units, settings.unit_style
    )
    assert tab.model.data(tab.model.index(0, 4)) == api.format_size(
        1024, settings.units, settings.unit_style
    )
    assert api.format_size(600, settings.units, settings.unit_style) in tab.bar.slice_labels()[0]
    assert calls == 1
    qtbot.waitUntil(lambda: not runner.busy, timeout=5000)
    runner.deleteLater()


@pytest.mark.parametrize("extension", ["txt", "", "or"])
@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter])
def test_activate_extension_opens_find_with_query(
    qtbot: QtBot, tmp_path: Path, extension: str, key: Qt.Key
) -> None:
    root = tmp_path / "find-handoff"
    filename = "file" + (f".{extension}" if extension else "")
    window = MainWindow(
        paths=AppPaths(
            tmp_path / "config", tmp_path / "data", tmp_path / "logs", tmp_path / "snapshots", False
        ),
        settings=Settings(),
        scan_backend=make_mock_backend(
            MockSpec([MockEntry(root, api.EntryKind.DIR), MockEntry(root / filename, size=42)])
        ),
        volume_provider=lambda: [],
    )

    def finish(widget) -> None:
        widget.close()
        qtbot.waitUntil(
            lambda: not window.controller.running and not window.runner.busy, timeout=10_000
        )

    qtbot.addWidget(window, before_close_func=finish)
    window.show()
    with qtbot.waitSignal(window.controller.finished, timeout=5000):
        window.start_scan(api.ScanRequest([root], threads=1))
    assert "types" not in window._pages
    window.show_tab("types")
    tab = window._pages["types"]
    assert isinstance(tab, TypesTab)
    qtbot.waitUntil(lambda: tab.model.rowCount() == 1, timeout=5000)
    tree, scope = tab.tree, tab.scope
    assert tree is not None and scope is not None
    tab.table.setCurrentIndex(tab.model.index(0, 0))
    qtbot.keyClick(tab.table, key)
    assert window._tab_keys[window.tabs.currentIndex()] == "find"
    expected = extension if extension == "txt" else json.dumps(extension)
    assert window.find_query.text() == f"ext:{expected}"
    assert window.find_tree is tree
    assert window.find_scope == scope


@pytest.mark.parametrize("extension", ["odd ext", 'odd"ext', "a:b"])
def test_unsafe_extension_query_is_json_quoted(
    qtbot: QtBot,
    tmp_path: Path,
    types_tab: tuple[TypesTab, TaskRunner],
    monkeypatch: pytest.MonkeyPatch,
    extension: str,
) -> None:
    """Exercise defensive quoting without changing native extension classification.

    ExtInterner deliberately treats whitespace-containing suffixes as no extension.
    A synthetic report lets the UI's query boundary cover unusual supplied values.
    """
    tab, _ = types_tab
    tree = _scan(tmp_path / "quoted")
    report = types_tab_module._TypesReport(
        (api.ExtStat(extension, 1, 42, 42, api.ExtCategory.OTHER),), (), 42, False
    )
    monkeypatch.setattr(types_tab_module, "_prepare", lambda tree, scope: report)
    _set_tree(tab, qtbot, tree)
    tab.table.setCurrentIndex(tab.model.index(0, 0))
    with qtbot.waitSignal(tab.findRequested, timeout=5000) as requested:
        qtbot.keyClick(tab.table, Qt.Key.Key_Return)
    assert requested.args == [tree, tree.roots()[0], "ext:" + json.dumps(extension)]


def test_large_file_count_approximate_allocation_and_scope_denominator(
    qtbot: QtBot,
    tmp_path: Path,
    types_tab: tuple[TypesTab, TaskRunner],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tab, _ = types_tab
    maximum = (1 << 64) - 1
    tree = _scan(tmp_path / "wide-count")
    report = types_tab_module._TypesReport(
        (api.ExtStat("txt", maximum, 100, 200, api.ExtCategory.DOCUMENT),), (), 1000, True
    )
    monkeypatch.setattr(types_tab_module, "_prepare", lambda tree, scope: report)
    _set_tree(tab, qtbot, tree)
    expected_count = str(maximum).translate(_number_translation(QLocale().name(), "."))
    assert tab.model.data(tab.model.index(0, 2)) == expected_count
    assert tab.model.data(tab.model.index(0, 4)) == "≈" + api.format_size(200)
    assert _percent(tab, 0) == 10


@pytest.mark.parametrize("replacement", ["scan", "tree"])
def test_pending_find_is_cleared_and_old_tree_handoff_rejected(
    qtbot: QtBot, tmp_path: Path, replacement: str
) -> None:
    root = tmp_path / "find-identity"
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
    window.show()
    with qtbot.waitSignal(window.controller.finished, timeout=5000):
        window.start_scan(api.ScanRequest([root], threads=1))
    old_tree = window._latest_tree
    assert old_tree is not None
    scope = old_tree.roots()[0]
    window.show_find(old_tree, scope, "ext:txt")
    assert window.find_tree is old_tree
    assert window.find_query.text() == "ext:txt"
    assert window.find_query.isReadOnly()
    if replacement == "scan":
        with qtbot.waitSignal(window.controller.finished, timeout=5000):
            window.start_scan(api.ScanRequest([root], threads=1))
            assert window.find_tree is None and window.find_scope is None
            window.show_find(old_tree, scope, "ext:stale")
            assert window.find_tree is None
    else:
        window._tree_ready(_scan(tmp_path / "replacement"))
    assert window.find_tree is None and window.find_scope is None
    assert window.find_query.text() == ""
    assert window.find_query_value == ""
    assert not window.tabs.isTabEnabled(window._tab_keys.index("find"))
    window.show_find(old_tree, scope, "ext:stale")
    assert window.find_tree is None
    assert window.find_query.text() == ""


def test_new_scan_supersedes_old_extension_result(
    qtbot: QtBot,
    tmp_path: Path,
    types_tab: tuple[TypesTab, TaskRunner],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tab, runner = types_tab
    old_tree = _scan(tmp_path / "old")
    new_root = tmp_path / "new"
    new_tree = _scan(
        new_root,
        [MockEntry(new_root, api.EntryKind.DIR), MockEntry(new_root / "only.new", size=42)],
    )
    original = types_tab_module._prepare
    started, release = threading.Event(), threading.Event()

    def gated_prepare(tree, scope):
        if tree is old_tree:
            started.set()
            if not release.wait(5):
                raise TimeoutError("extension preparation gate was not released")
        return original(tree, scope)

    monkeypatch.setattr(types_tab_module, "_prepare", gated_prepare)
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
    assert {ext: row.size for ext, row in _rows(tab).items()} == {"new": 42}
    assert sum(item.value for item in tab.bar.slices) == 42


def test_clear_discards_extension_result_inflight(
    qtbot: QtBot,
    tmp_path: Path,
    types_tab: tuple[TypesTab, TaskRunner],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tab, runner = types_tab
    tree = _scan(tmp_path / "cleared")
    original = types_tab_module._prepare
    started, release = threading.Event(), threading.Event()

    def gated_prepare(tree, scope):
        started.set()
        if not release.wait(5):
            raise TimeoutError("extension preparation gate was not released")
        return original(tree, scope)

    monkeypatch.setattr(types_tab_module, "_prepare", gated_prepare)
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
    assert tab.bar.slices == ()


def test_rapid_scope_changes_only_publish_latest_extension_report(
    qtbot: QtBot,
    tmp_path: Path,
    types_tab: tuple[TypesTab, TaskRunner],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tab, runner = types_tab
    root = tmp_path / "coalesced"
    tree = _scan(root)
    sub = tree.find_path(root / "sub")
    assert sub is not None
    original = types_tab_module._prepare
    started, release = threading.Event(), threading.Event()
    calls = []

    def gated_prepare(tree, scope):
        calls.append((tree, scope))
        if len(calls) == 1:
            started.set()
            if not release.wait(5):
                raise TimeoutError("extension preparation gate was not released")
        return original(tree, scope)

    monkeypatch.setattr(types_tab_module, "_prepare", gated_prepare)
    ready = QSignalSpy(tab.ready)
    tab.set_tree(tree)
    qtbot.waitUntil(started.is_set, timeout=5000)
    try:
        tab.select_node(0)
        tab.select_node(tree.roots()[0])
        tab.select_node(sub)
        with qtbot.waitSignal(tab.ready, timeout=5000):
            release.set()
        qtbot.waitUntil(lambda: not runner.busy, timeout=5000)
    finally:
        release.set()
    assert calls == [(tree, tree.roots()[0]), (tree, sub)]
    assert ready.count() == 1
    assert tab.scope == sub
    assert {ext: row.size for ext, row in _rows(tab).items()} == {"txt": 300}


def test_failed_extension_report_recovers_on_next_scope(
    qtbot: QtBot,
    tmp_path: Path,
    types_tab: tuple[TypesTab, TaskRunner],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tab, runner = types_tab
    root = tmp_path / "failure"
    tree = _scan(root)
    sub = tree.find_path(root / "sub")
    assert sub is not None
    original = types_tab_module._prepare
    calls = 0

    def fail_first(tree, scope):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("deliberate extension failure")
        return original(tree, scope)

    monkeypatch.setattr(types_tab_module, "_prepare", fail_first)
    ready = QSignalSpy(tab.ready)
    tab.set_tree(tree)
    qtbot.waitUntil(lambda: not runner.busy, timeout=5000)
    assert "deliberate extension failure" in tab.message.text()
    assert tab.message.isVisible()
    assert tab.model.rowCount() == 0
    assert tab.bar.slices == ()
    assert ready.count() == 0
    with qtbot.waitSignal(tab.ready, timeout=5000):
        tab.select_node(sub)
    assert {ext: row.size for ext, row in _rows(tab).items()} == {"txt": 300}
    assert ready.count() == 1
    assert not tab.message.isVisible()
