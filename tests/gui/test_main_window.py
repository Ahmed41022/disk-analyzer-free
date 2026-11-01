"""Main-window status, lazy views, native results, metadata workers and shutdown."""

# ruff: noqa: PLR2004 -- fixture counts, geometry, and diagnostic retention are contract assertions.

import os
import threading
from collections.abc import Callable, Iterator
from importlib.util import find_spec
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

if find_spec("PySide6") is None:
    if os.environ.get("DAFREE_REQUIRE_GUI") == "1":
        pytest.fail("PySide6 is required when DAFREE_REQUIRE_GUI=1", pytrace=False)
    pytest.skip("PySide6 is not installed", allow_module_level=True)

from PySide6.QtCore import QCoreApplication, QEvent, QLocale, Qt, QTimer
from PySide6.QtWidgets import QProgressBar

from dafree import api
from dafree.api.testing import MockEntry, MockSpec, TreeBuilder, make_mock_backend
from dafree.api.types import ScanIssue
from dafree.gui import main_window as module
from dafree.gui.main_window import MainWindow
from dafree.gui.views import tree_tab as tree_module
from dafree.gui.views.issues_tab import IssuesTab
from dafree.gui.views.tree_tab import TreeTab
from dafree.i18n import current_locale, setup
from dafree.paths import AppPaths
from dafree.settings import Settings, WindowState, load_settings

pytestmark = pytest.mark.gui
type WindowFactory = Callable[..., MainWindow]


@pytest.fixture
def make_window(qtbot: QtBot) -> Iterator[WindowFactory]:
    """Let queued native results finish before Qt schedules its owner for deletion."""
    previous = QLocale()
    previous_language = current_locale()
    QLocale.setDefault(QLocale("en_US"))
    setup("en_US")

    def create(**kwargs) -> MainWindow:
        kwargs.setdefault("volume_provider", lambda: [])
        window = MainWindow(**kwargs)

        def finish(widget) -> None:
            window.close()
            qtbot.waitUntil(
                lambda: not window.controller.running and not window.runner.busy, timeout=10_000
            )

        qtbot.addWidget(window, before_close_func=finish)
        window.show()
        return window

    yield create
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QLocale.setDefault(previous)
    setup(previous_language)


def progress(root: Path, issues: int = 3) -> api.ScanProgress:
    """A copied progress DTO carries no filesystem traversal or Python backend."""
    return api.ScanProgress(
        7,
        2,
        12345,
        16384,
        issues,
        str(root),
        1250,
        api.ScanState.RUNNING,
        None,
        api.ScanModeUsed.WALK,
    )


def test_status_bar_updates_from_progress(make_window: WindowFactory, tmp_path: Path) -> None:
    """Mode, files, folders, total, elapsed and issue counts follow the controller."""
    window = make_window()
    window.controller.progressChanged.emit(progress(tmp_path))
    assert window.mode_label.text() == "Walk"
    assert window.files_label.text() == "Files: 7"
    assert window.dirs_label.text() == "Folders: 2"
    assert window.total_label.text() == "Total: " + api.format_size(12345)
    assert window.elapsed_label.text() == "00:00:01"
    assert window.issues_button.text() == "Issues: 3"
    window.controller.noticeReceived.emit(
        api.Notice(api.NoticeKind.FAST_MODE_UNAVAILABLE, "Walk fallback")
    )
    assert window.mode_label.isVisible() and window.files_label.isVisible()
    assert window.notice_label.text() == "Walk fallback"


def test_issue_count_click_opens_issues_tab(make_window: WindowFactory, tmp_path: Path) -> None:
    """Issue content stays unconstructed until its status button is activated."""
    window = make_window()
    assert set(window._pages) == {"tree"}
    assert window.tabs.count() == 11
    window.controller.progressChanged.emit(progress(tmp_path))
    issue = ScanIssue(str(tmp_path / "denied"), api.IssueKind.ACCESS_DENIED, "Denied")
    window.controller.issuesAdded.emit([issue])
    window.issues_button.click()
    assert window._tab_keys[window.tabs.currentIndex()] == "issues"
    page = window._pages["issues"]
    assert isinstance(page, IssuesTab)
    assert page.model.rowCount() == 1
    assert page.model.index(0, 0).data() == "Access denied"
    assert page.model.index(0, 1).data() == issue.path
    assert page.summary.text() == "Showing 1 of 3 issues"
    assert set(window._pages) == {"tree", "issues"}


def test_volume_list_populated(
    qtbot: QtBot,
    make_window: WindowFactory,
    tmp_path: Path,
) -> None:
    """Real capacity widgets retain native targets and mark network mounts with an icon."""
    volumes = [
        api.VolumeInfo(str(tmp_path), label="Local", total=1000, free=250),
        api.VolumeInfo(str(tmp_path / "network"), total=2000, free=1000, is_network=True),
        api.VolumeInfo(str(tmp_path / "pseudo"), total=0),
    ]
    window = make_window(volume_provider=lambda: volumes)
    qtbot.waitUntil(lambda: not window.volumes.loading)
    assert window.volumes.list.count() == 2
    bars = window.volumes.findChildren(QProgressBar)
    assert [bar.value() for bar in bars] == [750, 500]
    assert "free of" in bars[0].format()
    assert bars[0].accessibleName().startswith(str(tmp_path))
    assert window.volumes.list.item(1).data(Qt.ItemDataRole.UserRole) is volumes[1]
    with qtbot.waitSignal(window.scanRequested) as requested:
        window.volumes.list.itemActivated.emit(window.volumes.list.item(1))
    assert requested.args == [[volumes[1].mount]]


def test_volume_query_does_not_block_or_stack(
    qtbot: QtBot,
    make_window: WindowFactory,
) -> None:
    """Repeated refresh requests coalesce while metadata work runs outside Qt's thread."""
    entered, release = threading.Event(), threading.Event()
    calls: list[int] = []

    def provider() -> list[api.VolumeInfo]:
        calls.append(threading.get_ident())
        entered.set()
        assert release.wait(5)
        return []

    window = make_window(volume_provider=provider)
    try:
        qtbot.waitUntil(entered.is_set)
        heartbeat: list[bool] = []
        QTimer.singleShot(0, lambda: heartbeat.append(True))
        window.volumes.refresh()
        window.volumes.refresh()
        qtbot.waitUntil(lambda: bool(heartbeat))
        assert len(calls) == 1 and calls[0] != threading.get_ident()
        with qtbot.waitSignal(window.volumes.loaded):
            release.set()
        assert not window.volumes.loading
    finally:
        release.set()


def test_recent_targets_remain_lossless(
    make_window: WindowFactory, tmp_path: Path, qtbot: QtBot
) -> None:
    """Qt displays escaped names while opaque item data and object signals keep raw paths."""
    target = str(tmp_path / "bad-\ud800")
    window = make_window(settings=Settings(recent_targets=[target]))
    assert "\\ud800" in window.recent.item(0).text()
    with qtbot.waitSignal(window.scanRequested) as requested:
        window.recent.itemActivated.emit(window.recent.item(0))
    assert requested.args == [[target]]


def test_native_result_populates_tree_and_parent_navigation(
    qtbot: QtBot,
    make_window: WindowFactory,
    tmp_path: Path,
) -> None:
    """The actual controller builds a view off-thread, then installs the Qt model and details."""
    backend = make_mock_backend(
        MockSpec(
            [
                MockEntry(tmp_path, api.EntryKind.DIR),
                MockEntry(tmp_path / "sample.bin", size=5),
            ]
        )
    )
    window = make_window(scan_backend=backend)
    with qtbot.waitSignal(window.controller.finished, timeout=5000):
        window.start_scan(api.ScanRequest([tmp_path], threads=1))
    page = window._pages["tree"]
    assert isinstance(page, TreeTab)
    qtbot.waitUntil(lambda: page.table is not None)
    assert page.table is not None
    assert page.table.tree_model.rowCount() == 2
    assert page.table.verticalHeader().defaultSectionSize() == 24
    assert not page.breadcrumb.up.isEnabled()
    qtbot.keyClick(page.table, Qt.Key.Key_Right)
    assert page.breadcrumb.up.isEnabled()
    assert page.breadcrumb.path_label.toolTip().endswith("sample.bin")
    page.breadcrumb.up.click()
    assert page.table.currentIndex().row() == 0
    assert "Size: " in page.details.text()
    assert window.recent.item(0).data(Qt.ItemDataRole.UserRole).path == str(tmp_path)


def test_close_cancels_scan_without_blocking(
    qtbot: QtBot, make_window: WindowFactory, tmp_path: Path
) -> None:
    """Closing cancels read-only work and keeps Qt alive until startup/result workers drain."""
    entries = [MockEntry(tmp_path, api.EntryKind.DIR)]
    for index in range(12):
        entries.extend(
            [
                MockEntry(tmp_path / str(index), api.EntryKind.DIR),
                MockEntry(tmp_path / str(index) / "file", size=1),
            ]
        )
    window = make_window(scan_backend=make_mock_backend(MockSpec(entries, delay_ms=80)))
    window.start_scan(api.ScanRequest([tmp_path], threads=1))
    heartbeat: list[bool] = []
    QTimer.singleShot(0, lambda: heartbeat.append(True))
    assert not window.close()
    qtbot.waitUntil(lambda: not window.isVisible(), timeout=5000)
    assert heartbeat and not window.controller.running and not window.runner.busy


def test_windows_elevated_badge_uses_known_information(
    make_window: WindowFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The presentation supports a known badge, while paused Windows APIs remain unknown."""
    monkeypatch.setattr(module, "_WINDOWS", True)
    elevated = make_window(elevation_provider=lambda: True)
    assert elevated.elevated_badge.isVisible()

    def unavailable() -> bool:
        raise api.Unsupported("Unavailable")

    unknown = make_window(elevation_provider=unavailable)
    assert unknown.elevated_badge.isHidden()


def test_issue_retention_matches_core_cap(make_window: WindowFactory, tmp_path: Path) -> None:
    """A live stream cannot allocate an unbounded Python diagnostic collection."""
    window = make_window()
    window.controller.progressChanged.emit(progress(tmp_path, issues=1005))
    issues = [ScanIssue(str(tmp_path / str(i)), api.IssueKind.IO, "I/O") for i in range(1005)]
    window.controller.issuesAdded.emit(issues)
    window.show_tab("issues")
    page = window._pages["issues"]
    assert isinstance(page, IssuesTab)
    assert len(window._issues) == page.model.rowCount() == 1000
    assert page.summary.text() == "Showing 1000 of 1005 issues"


def test_window_geometry_persists_in_test_profile(
    qtbot: QtBot,
    make_window: WindowFactory,
    tmp_path: Path,
) -> None:
    """Only the supplied application profile is written when the configured window closes."""
    paths = AppPaths(
        tmp_path / "config", tmp_path / "data", tmp_path / "logs", tmp_path / "snapshots", False
    )
    settings = Settings(window=WindowState(width=950, height=650))
    window = make_window(paths=paths, settings=settings)
    qtbot.waitUntil(lambda: not window.runner.busy)
    rectangle = window.normalGeometry()
    window.close()
    stored = load_settings(paths).window
    assert stored is not None
    assert stored.width == rectangle.width() and stored.height == rectangle.height()


def test_tree_preparation_is_async_and_coalesces_snapshots(
    qtbot: QtBot,
    make_window: WindowFactory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Qt stays responsive and only the newest pending native tree builds."""
    native_view = api.TreeView
    trees = [TreeBuilder.flat(tmp_path / name, 2) for name in ("one", "two", "three")]
    entered, release = threading.Event(), threading.Event()
    calls: list[tuple[api.Tree, int]] = []

    def prepare(tree, options):
        calls.append((tree, threading.get_ident()))
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        return native_view(tree, options)

    monkeypatch.setattr(tree_module.api, "TreeView", prepare)
    window = make_window()
    page = window._pages["tree"]
    assert isinstance(page, TreeTab)
    try:
        page.set_tree(trees[0])
        qtbot.waitUntil(entered.is_set)
        page.set_tree(trees[1])
        page.set_tree(trees[2])
        heartbeat: list[bool] = []
        QTimer.singleShot(0, lambda: heartbeat.append(True))
        qtbot.waitUntil(lambda: bool(heartbeat))
        with qtbot.waitSignal(page.ready):
            release.set()
        assert page.tree is trees[2]
        assert [tree for tree, ident in calls] == [trees[0], trees[2]]
        assert all(ident != threading.get_ident() for tree, ident in calls)
    finally:
        release.set()


def test_initial_unit_preferences_match_status_and_table(
    qtbot: QtBot,
    make_window: WindowFactory,
    tmp_path: Path,
) -> None:
    """Initial preferences format existing metadata without enabling deferred unit controls."""
    backend = make_mock_backend(
        MockSpec(
            [
                MockEntry(tmp_path, api.EntryKind.DIR),
                MockEntry(tmp_path / "sample", size=2048),
            ]
        )
    )
    settings = Settings(units=api.UnitMode.BYTES)
    window = make_window(settings=settings, scan_backend=backend)
    with qtbot.waitSignal(window.controller.finished):
        window.start_scan(api.ScanRequest([tmp_path], threads=1))
    page = window._pages["tree"]
    assert isinstance(page, TreeTab)
    qtbot.waitUntil(lambda: page.table is not None)
    expected = api.format_size(2048, settings.units, settings.unit_style)
    assert window.total_label.text() == "Total: " + expected
    assert page.table.tree_model.index(0, 1).data() == expected
