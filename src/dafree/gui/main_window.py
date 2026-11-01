"""Main desktop layout, lazy result tabs, and scan/status orchestration."""

from __future__ import annotations

import sys
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass

from PySide6.QtCore import QLocale, QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QDockWidget,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QPushButton,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dafree import api
from dafree.api.types import ScanIssue
from dafree.gui import _display_text
from dafree.gui.controllers.scan_controller import ScanController
from dafree.gui.controllers.task_runner import TaskRunner
from dafree.gui.dialogs.scan_dialog import ScanDialog
from dafree.gui.views.issues_tab import IssuesTab
from dafree.gui.views.tree_tab import TreeTab
from dafree.gui.widgets.breadcrumb import ElidedPathLabel
from dafree.gui.widgets.progress_panel import ProgressPanel, elapsed_text
from dafree.gui.widgets.volume_list import VolumeList
from dafree.i18n import _
from dafree.paths import AppPaths
from dafree.settings import Settings, WindowState, save_settings

_WINDOWS = sys.platform == "win32"
_MAX_ISSUES = 1000
_MAX_RECENT = 10


@dataclass(frozen=True)
class _Target:
    path: str


class MainWindow(QMainWindow):
    """Own one scan and lazily create its implemented result views."""

    scanRequested = Signal(object)
    propertiesRequested = Signal(object, object)
    contextMenuRequested = Signal(object, object, object)
    closed = Signal()

    def __init__(
        self,
        *,
        paths: AppPaths | None = None,
        settings: Settings | None = None,
        scan_backend: api.Backend | None = None,
        volume_provider: Callable[[], list[api.VolumeInfo]] | None = None,
        elevation_provider: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__()
        self._settings = settings if settings is not None else Settings()
        self._paths = paths
        self._volume_provider = volume_provider
        self._scan_dialog: ScanDialog | None = None
        self._pending_launch_arguments: list[str] = []
        self._latest_tree: api.Tree | None = None
        self._issues: list[ScanIssue] = []
        self._issue_total = 0
        self._pages: dict[str, TreeTab | IssuesTab] = {}
        self._tab_keys: list[str] = []
        self._closing = False
        self.runner = TaskRunner(self)
        self.controller = ScanController(self, runner=self.runner, backend=scan_backend)
        self.setWindowTitle(_("Disk Analyzer Free"))
        rectangle = self._settings.window or WindowState()
        self.resize(rectangle.width, rectangle.height)
        if self._settings.window is not None:
            self.move(rectangle.x, rectangle.y)
        self._build_toolbar()
        self._build_sidebar(volume_provider)
        self._build_tabs()
        self._build_progress()
        self._build_status(elevation_provider)
        self._close_timer = QTimer(self)
        self._close_timer.setInterval(50)
        self._close_timer.timeout.connect(self._try_close)
        self.controller.started.connect(self._started)
        self.controller.progressChanged.connect(self._progress)
        self.controller.issuesAdded.connect(self._add_issues)
        self.controller.partialTreeReady.connect(self._tree_ready)
        self.controller.noticeReceived.connect(lambda notice: self._show_notice(notice.detail))
        self.controller.finished.connect(self._finished)
        self.controller.failed.connect(self._failed)
        self.scanRequested.connect(self.open_scan_dialog)
        self.volumes.refresh()

    def _build_toolbar(self) -> None:
        toolbar = QToolBar(_("Scan controls"), self)
        toolbar.setObjectName("scan.controls")
        self.addToolBar(toolbar)
        self.new_scan = QAction(_("New scan"), self)
        self.new_scan.triggered.connect(lambda checked=False: self.scanRequested.emit([]))
        toolbar.addAction(self.new_scan)
        self._recent_menu = QMenu(self)
        button = toolbar.widgetForAction(self.new_scan)
        if isinstance(button, QToolButton):
            button.setMenu(self._recent_menu)
            button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.pause = QAction(_("Pause"), self)
        self.pause.setCheckable(True)
        self.pause.setEnabled(False)
        toolbar.addAction(self.pause)
        self.cancel = QAction(_("Cancel"), self)
        self.cancel.setEnabled(False)
        toolbar.addAction(self.cancel)
        for caption in (_("Refresh"), _("Units")):
            action = toolbar.addAction(caption)
            action.setEnabled(False)
        self.query_placeholder = QLineEdit(toolbar)
        self.query_placeholder.setPlaceholderText(_("Search"))
        self.query_placeholder.setAccessibleName(_("Search results"))
        self.query_placeholder.setEnabled(False)
        toolbar.addWidget(self.query_placeholder)
        toolbar.addAction(_("Settings")).setEnabled(False)
        for action in toolbar.actions():
            widget = toolbar.widgetForAction(action)
            if widget is not None:
                widget.setAccessibleName(action.text())

    def _build_sidebar(self, provider: Callable[[], list[api.VolumeInfo]] | None) -> None:
        dock = QDockWidget(_("Locations"), self)
        dock.setObjectName("locations")
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        body = QWidget(dock)
        layout = QVBoxLayout(body)
        layout.addWidget(QLabel(_("Volumes"), body))
        self.volumes = VolumeList(self._settings, self.runner, body, provider=provider)
        self.volumes.targetRequested.connect(lambda path: self.scanRequested.emit([path]))
        layout.addWidget(self.volumes, 2)
        layout.addWidget(QLabel(_("Recent scans"), body))
        self.recent = QListWidget(body)
        self.recent.setAccessibleName(_("Recent scans"))
        self.recent.itemActivated.connect(self._recent_activated)
        layout.addWidget(self.recent, 1)
        self.snapshots = QPushButton(_("Snapshots"), body)
        self.snapshots.setEnabled(False)  # Snapshot opening belongs to M6.
        if self._paths is not None:
            self.snapshots.setToolTip(_display_text(str(self._paths.snapshots)))
        layout.addWidget(self.snapshots)
        self.snapshots_path = ElidedPathLabel(body)
        if self._paths is not None:
            self.snapshots_path.set_path(str(self._paths.snapshots))
        layout.addWidget(self.snapshots_path)
        dock.setWidget(body)
        self._update_recent()

    def _update_recent(self) -> None:
        self.recent.clear()
        self._recent_menu.clear()
        for target in self._settings.recent_targets:
            item = QListWidgetItem(_display_text(target), self.recent)
            item.setData(Qt.ItemDataRole.UserRole, _Target(target))
            action = self._recent_menu.addAction(_display_text(target))
            action.triggered.connect(
                lambda checked=False, target=target: self.scanRequested.emit([target])
            )
        self._recent_menu.setEnabled(bool(self._settings.recent_targets))

    def _recent_activated(self, item: QListWidgetItem) -> None:
        target = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(target, _Target):
            self.scanRequested.emit([target.path])

    def _build_tabs(self) -> None:
        self.tabs = QTabWidget(self)
        for key, title in (
            ("tree", _("Tree")),
            ("treemap", _("Treemap")),
            ("charts", _("Charts")),
            ("top", _("Top")),
            ("types", _("Types")),
            ("age", _("Age")),
            ("find", _("Find")),
            ("duplicates", _("Duplicates")),
            ("empty", _("Empty")),
            ("compare", _("Compare")),
            ("issues", _("Issues")),
        ):
            page = QWidget(self.tabs)
            page.setObjectName(f"tab.{key}")
            index = self.tabs.addTab(page, title)
            self._tab_keys.append(key)
            self.tabs.setTabEnabled(index, key in ("tree", "issues"))
        self.tabs.currentChanged.connect(self._activate_tab)
        self._activate_tab(0)

    def _build_progress(self) -> None:
        body = QWidget(self)
        layout = QVBoxLayout(body)
        self.progress_panel = ProgressPanel(
            self.controller,
            self._settings,
            body,
            pause_action=self.pause,
            cancel_action=self.cancel,
        )
        layout.addWidget(self.progress_panel)
        layout.addWidget(self.tabs, 1)
        self.setCentralWidget(body)

    def _activate_tab(self, index: int) -> None:
        if index < 0:
            return
        key = self._tab_keys[index]
        if key not in ("tree", "issues"):
            return
        if key not in self._pages:
            if key == "tree":
                tree_page = TreeTab(self._settings, self.runner, self.tabs, paths=self._paths)
                tree_page.propertiesRequested.connect(self.propertiesRequested.emit)
                tree_page.contextMenuRequested.connect(self.contextMenuRequested.emit)
                page: TreeTab | IssuesTab = tree_page
            else:
                page = IssuesTab(self.tabs)
            self._pages[key] = page
            old, title = self.tabs.widget(index), self.tabs.tabText(index)
            with QSignalBlocker(self.tabs):
                self.tabs.removeTab(index)
                self.tabs.insertTab(index, page, title)
                self.tabs.setCurrentIndex(index)
            if old is not None:
                old.deleteLater()
        selected = self._pages[key]
        if isinstance(selected, TreeTab) and self._latest_tree is not None:
            selected.set_tree(self._latest_tree)
        elif isinstance(selected, IssuesTab):
            selected.set_issues(self._issues, self._issue_total)

    def show_tab(self, key: str) -> None:
        """Activate an implemented tab, creating its contents on first use."""
        self.tabs.setCurrentIndex(self._tab_keys.index(key))

    def _build_status(self, provider: Callable[[], bool] | None) -> None:
        bar = self.statusBar()
        self.mode_label = QLabel(_("Ready"), self)
        self.files_label = QLabel(_("Files: 0"), self)
        self.dirs_label = QLabel(_("Folders: 0"), self)
        self.total_label = QLabel(_("Total: 0 B"), self)
        self.elapsed_label = QLabel(elapsed_text(0), self)
        for label in (
            self.mode_label,
            self.files_label,
            self.dirs_label,
            self.total_label,
            self.elapsed_label,
        ):
            label.setTextFormat(Qt.TextFormat.PlainText)
            bar.addWidget(label)
        self.issues_button = QPushButton(_("Issues: 0"), self)
        self.issues_button.setFlat(True)
        self.issues_button.setAccessibleName(_("Scan issues"))
        self.issues_button.clicked.connect(lambda: self.show_tab("issues"))
        bar.addPermanentWidget(self.issues_button)
        self.notice_label = QLabel("", self)
        self.notice_label.setTextFormat(Qt.TextFormat.PlainText)
        self.notice_label.setMaximumWidth(240)
        bar.addPermanentWidget(self.notice_label)
        self.notice_label.hide()
        self.elevated_badge = QLabel(_("Administrator"), self)
        self.elevated_badge.setAccessibleName(_("Running as administrator"))
        elevated = False
        if _WINDOWS:
            with suppress(api.Unsupported):
                elevated = (provider or api.platform.is_elevated)()
        bar.addPermanentWidget(self.elevated_badge)
        self.elevated_badge.setVisible(_WINDOWS and elevated)

    def _show_notice(self, message: str) -> None:
        text = _display_text(message)
        self.notice_label.setText(text)
        self.notice_label.setToolTip(text)
        self.notice_label.setAccessibleName(text)
        self.notice_label.show()

    def open_scan_dialog(self, targets: list[str] | None = None) -> None:
        """Open one target-selection dialog; acceptance alone starts the read-only scan."""
        if self._closing or self.controller.running:
            return
        if self._scan_dialog is not None:
            for target in targets or []:
                self._scan_dialog.add_target(target)
            self._scan_dialog.raise_()
            self._scan_dialog.activateWindow()
            return
        dialog = ScanDialog(
            self._settings,
            self.runner,
            self,
            paths=self._paths,
            targets=targets or None,
            volume_provider=self._volume_provider,
        )
        self._scan_dialog = dialog
        dialog.accepted.connect(self._accept_scan_dialog)
        dialog.finished.connect(self._dispose_scan_dialog)
        dialog.open()

    def _accept_scan_dialog(self) -> None:
        if self._scan_dialog is not None and self._scan_dialog.request is not None:
            self.start_scan(self._scan_dialog.request)

    def _dispose_scan_dialog(self, result: int) -> None:
        if self._scan_dialog is not None:
            self._scan_dialog.deleteLater()
            self._scan_dialog = None

    def receive_arguments(self, arguments: list[str]) -> None:
        """Retain lossless launch targets and present them for explicit scan acceptance."""
        self._pending_launch_arguments = arguments.copy()
        if arguments:
            self.open_scan_dialog(arguments)

    def start_scan(self, request: api.ScanRequest) -> None:
        """Start the single owned controller; native validation/collection stay off-thread."""
        self.controller.start(request)

    def _started(self, request: api.ScanRequest) -> None:
        self._latest_tree = None
        self._issues.clear()
        self._issue_total = 0
        self.new_scan.setEnabled(False)
        self.mode_label.setText(_("Preparing scan…"))
        self.files_label.setText(_("Files: {count}").format(count=QLocale().toString(0)))
        self.dirs_label.setText(_("Folders: {count}").format(count=QLocale().toString(0)))
        self.total_label.setText(
            _("Total: {size}").format(
                size=api.format_size(0, self._settings.units, self._settings.unit_style)
            )
        )
        self.elapsed_label.setText(elapsed_text(0))
        self.notice_label.hide()
        self.issues_button.setText(_("Issues: 0"))
        tree_page = self._pages.get("tree")
        if isinstance(tree_page, TreeTab):
            tree_page.clear()
        issues_page = self._pages.get("issues")
        if isinstance(issues_page, IssuesTab):
            issues_page.set_issues([], 0)

    def _progress(self, progress: api.ScanProgress) -> None:
        locale = QLocale()
        self.mode_label.setText(_("MFT") if progress.mode == api.ScanModeUsed.MFT else _("Walk"))
        self.files_label.setText(_("Files: {count}").format(count=locale.toString(progress.files)))
        self.dirs_label.setText(_("Folders: {count}").format(count=locale.toString(progress.dirs)))
        self.total_label.setText(
            _("Total: {size}").format(
                size=api.format_size(
                    progress.bytes, self._settings.units, self._settings.unit_style
                )
            )
        )
        self.elapsed_label.setText(elapsed_text(progress.elapsed_ms))
        self._issue_total = progress.issues
        self.issues_button.setText(
            _("Issues: {count}").format(count=locale.toString(progress.issues))
        )

    def _add_issues(self, issues: list[ScanIssue]) -> None:
        self._issues.extend(issues[: max(0, _MAX_ISSUES - len(self._issues))])
        page = self._pages.get("issues")
        if isinstance(page, IssuesTab):
            page.set_issues(self._issues, self._issue_total)

    def _tree_ready(self, tree: api.Tree) -> None:
        self._latest_tree = tree
        if not self._closing and self._tab_keys[self.tabs.currentIndex()] == "tree":
            page = self._pages.get("tree")
            if isinstance(page, TreeTab):
                page.set_tree(tree)

    def _finished(self, result: api.ScanResult) -> None:
        metadata = result.tree.meta()
        self._issues = list(metadata.issues.first)
        self._issue_total = metadata.issues.total
        self._tree_ready(result.tree)
        self.new_scan.setEnabled(True)
        targets = [str(path) for path in metadata.options.targets]
        self._settings.recent_targets = list(
            dict.fromkeys(targets + self._settings.recent_targets)
        )[:_MAX_RECENT]
        self._update_recent()
        page = self._pages.get("issues")
        if isinstance(page, IssuesTab):
            page.set_issues(self._issues, self._issue_total)
        if self._closing:
            self._try_close()

    def _failed(self, message: str) -> None:
        self.mode_label.setText(_("Scan failed"))
        self._show_notice(message)
        self.new_scan.setEnabled(True)
        if self._closing:
            self._try_close()

    def _try_close(self) -> None:
        if self._closing and not self.controller.running and not self.runner.busy:
            self._close_timer.stop()
            self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Cancel read-only work and keep servicing Qt until workers deliver their results."""
        if self.controller.running or self.runner.busy:
            self._closing = True
            self.controller.cancel()
            self.setEnabled(False)
            self._close_timer.start()
            event.ignore()
            return
        if self._paths is not None:
            rectangle = self.normalGeometry()
            self._settings.window = WindowState(
                rectangle.x(),
                rectangle.y(),
                rectangle.width(),
                rectangle.height(),
                self.isMaximized(),
            )
            save_settings(self._settings, self._paths)
        event.accept()
        self.closed.emit()
        super().closeEvent(event)


def create_main_window(
    *,
    paths: AppPaths | None = None,
    settings: Settings | None = None,
    scan_backend: api.Backend | None = None,
    volume_provider: Callable[[], list[api.VolumeInfo]] | None = None,
    elevation_provider: Callable[[], bool] | None = None,
) -> MainWindow:
    """Create the configured shell; standalone callers need not create any application files."""
    return MainWindow(
        paths=paths,
        settings=settings,
        scan_backend=scan_backend,
        volume_provider=volume_provider,
        elevation_provider=elevation_provider,
    )
