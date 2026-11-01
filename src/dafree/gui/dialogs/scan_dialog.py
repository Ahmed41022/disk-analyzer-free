"""Select scan roots and persist traversal defaults without starting native work in Qt."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Sequence
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from dafree import api
from dafree.gui import _display_text
from dafree.gui.controllers.task_runner import TaskRunner
from dafree.gui.widgets.volume_list import VolumeList
from dafree.i18n import _
from dafree.paths import AppPaths
from dafree.settings import ExcludeRulesModel, ScanOptionsModel, Settings, save_settings

_WINDOWS = sys.platform == "win32"
_MAX_THREADS = (1 << 32) - 1


@dataclass(frozen=True)
class _Target:
    path: str


@dataclass(frozen=True)
class _Validation:
    owner: object
    path: str


def _directory(path: str) -> bool:
    return Path(path).is_dir()


class ScanDialog(QDialog):
    """Build a scan request; metadata validation and volume discovery use a shared runner."""

    def __init__(  # noqa: PLR0913 -- explicit platform/storage seams keep native tests isolated.
        self,
        settings: Settings,
        runner: TaskRunner,
        parent: QWidget | None = None,
        *,
        paths: AppPaths | None = None,
        targets: Sequence[str] | None = None,
        volume_provider: Callable[[], list[api.VolumeInfo]] | None = None,
        elevation_provider: Callable[[], bool] | None = None,
        relaunch: Callable[[list[str]], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("New scan"))
        self.resize(650, 700)
        self._settings, self._runner, self._paths = settings, runner, paths
        self._owner = object()
        self._pending: set[str] = set()
        self._relaunch = relaunch
        self.request: api.ScanRequest | None = None
        self._defaults = deepcopy(settings.default_scan)
        layout = QVBoxLayout(self)
        self.volumes = VolumeList(settings, runner, self, provider=volume_provider)
        self.volumes.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.volumes.targetRequested.connect(self.add_target)
        layout.addWidget(self.volumes, 1)
        self.add_volumes = QPushButton(_("Add selected volumes"), self)
        self.add_volumes.clicked.connect(self._add_volumes)
        layout.addWidget(self.add_volumes)
        self.targets = QListWidget(self)
        self.targets.setAccessibleName(_("Scan targets"))
        self.targets.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.targets, 1)
        self._build_target_controls(layout)
        self._build_options(layout, elevation_provider)
        self.error = QLabel("", self)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        self.start = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.start.setText(_("Start scan"))
        self.start.setDefault(True)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        # Enter always belongs to the explicit Start action, including in path fields.
        for button in (self.add_volumes, self.add_path, self.add_folder, self.remove, self.restart):
            button.setAutoDefault(False)
        runner.finished.connect(self._validated)
        runner.failed.connect(self._validation_failed)
        for target in self._defaults.targets if targets is None else targets:
            self.add_target(target)
        self._update_start()
        self.volumes.refresh()

    def _build_target_controls(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        self.path = QLineEdit(self)
        self.path.setPlaceholderText(_("Folder path"))
        self.path.setAccessibleName(_("Folder path"))
        row.addWidget(self.path, 1)
        self.add_path = QPushButton(_("Add path"), self)
        self.add_path.clicked.connect(self._add_typed)
        row.addWidget(self.add_path)
        self.add_folder = QPushButton(_("Add folder…"), self)
        self.add_folder.clicked.connect(self._pick_folder)
        row.addWidget(self.add_folder)
        self.remove = QPushButton(_("Remove targets"), self)
        self.remove.clicked.connect(self._remove_targets)
        row.addWidget(self.remove)
        layout.addLayout(row)
        for button in (self.add_path, self.add_folder, self.remove):
            button.setAutoDefault(False)

    def _build_options(
        self, layout: QVBoxLayout, elevation_provider: Callable[[], bool] | None
    ) -> None:
        options = self._defaults
        form = QFormLayout()
        self.threads = QDoubleSpinBox(self)
        self.threads.setDecimals(0)
        self.threads.setRange(0, _MAX_THREADS)
        self.threads.setSpecialValueText(_("Auto"))
        self.threads.setValue(options.threads)
        form.addRow(_("Threads"), self.threads)
        self.mode = QComboBox(self)
        self.mode.addItem(_("Auto"), api.ScanMode.AUTO)
        self.mode.addItem(_("Walk"), api.ScanMode.WALK)
        if _WINDOWS:
            self.mode.addItem(_("MFT"), api.ScanMode.MFT)
            model = self.mode.model()
            if isinstance(model, QStandardItemModel):
                model.item(2).setEnabled(False)
                model.item(2).setToolTip(_("Fast scanning is unavailable in this build."))
        self.mode.setCurrentIndex(1 if options.mode == api.ScanMode.WALK else 0)
        form.addRow(_("Mode"), self.mode)
        self.follow_symlinks = QCheckBox(_("Follow symbolic links"), self)
        self.follow_symlinks.setChecked(options.follow_symlinks)
        self.cross_filesystems = QCheckBox(_("Cross filesystems"), self)
        self.cross_filesystems.setChecked(options.cross_filesystems)
        self.hidden = QCheckBox(_("Exclude hidden entries"), self)
        self.hidden.setChecked(options.exclude.hidden)
        self.system = QCheckBox(_("Exclude system entries"), self)
        self.system.setChecked(options.exclude.system)
        for checkbox in (self.follow_symlinks, self.cross_filesystems, self.hidden, self.system):
            form.addRow(checkbox)
        layout.addLayout(form)
        self.exclusions = QTabWidget(self)
        self.globs = QPlainTextEdit(self)
        self.exclude_paths = QPlainTextEdit(self)
        for editor, values, name in (
            (self.globs, options.exclude.globs, _("Excluded globs, one per line")),
            (self.exclude_paths, options.exclude.paths, _("Excluded paths, one per line")),
        ):
            editor.setPlainText(_display_text("\n".join(values)))
            editor.setPlaceholderText(name)
            editor.setAccessibleName(name)
        self.exclusions.addTab(self.globs, _("Globs"))
        self.exclusions.addTab(self.exclude_paths, _("Paths"))
        self.exclusions.setMaximumHeight(130)
        layout.addWidget(self.exclusions)
        self.restart = QPushButton(_("Restart as administrator"), self)
        known_elevated: bool | None = None
        if _WINDOWS:
            with suppress(api.Unsupported):
                known_elevated = (elevation_provider or api.platform.is_elevated)()
        self.restart.setVisible(_WINDOWS and known_elevated is not True)
        self.restart.setEnabled(known_elevated is False and self._relaunch is not None)
        self.restart.setToolTip(_("Administrator relaunch is unavailable in this build."))
        self.restart.clicked.connect(self._restart)
        layout.addWidget(self.restart)

    def target_paths(self) -> list[str]:
        """Return raw paths from opaque metadata, never from displayed QString text."""
        return [
            self.targets.item(i).data(Qt.ItemDataRole.UserRole).path
            for i in range(self.targets.count())
        ]

    def add_target(self, path: str) -> None:
        """Normalize a root lexically and validate directory metadata in a worker."""
        if not path or "\0" in path:
            self.error.setText(_("Enter a valid folder path."))
            return
        normalized = os.path.abspath(path)  # noqa: PTH100 -- lexical only; resolve would do I/O in Qt.
        key = os.path.normcase(normalized)
        if key in self._pending or key in {os.path.normcase(p) for p in self.target_paths()}:
            return
        self._pending.add(key)
        self.error.setText(_("Checking folder…"))
        self._update_start()
        self._runner.submit(
            lambda: _directory(normalized), task_id=_Validation(self._owner, normalized)
        )

    def _validated(self, job: object, result: object) -> None:
        if not isinstance(job, _Validation) or job.owner is not self._owner:
            return
        self._pending.discard(os.path.normcase(job.path))
        if result is True:
            item = QListWidgetItem(_display_text(job.path), self.targets)
            item.setData(Qt.ItemDataRole.UserRole, _Target(job.path))
            item.setToolTip(_display_text(job.path))
            self.error.clear()
        else:
            self.error.setText(
                _("Folder is unavailable: {path}").format(path=_display_text(job.path))
            )
        self._update_start()

    def _validation_failed(self, job: object, message: str) -> None:
        if isinstance(job, _Validation) and job.owner is self._owner:
            self._pending.discard(os.path.normcase(job.path))
            self.error.setText(
                _("Could not validate folder: {error}").format(error=_display_text(message))
            )
            self._update_start()

    def _update_start(self) -> None:
        self.start.setEnabled(self.targets.count() > 0 and not self._pending)

    def _add_typed(self) -> None:
        self.add_target(self.path.text())

    def _pick_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, _("Choose scan folder"))
        if path:
            self.add_target(path)

    def _add_volumes(self) -> None:
        for item in self.volumes.list.selectedItems():
            volume = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(volume, api.VolumeInfo):
                self.add_target(volume.mount)

    def _remove_targets(self) -> None:
        for item in self.targets.selectedItems():
            self.targets.takeItem(self.targets.row(item))
        self._update_start()

    @staticmethod
    def _lines(editor: QPlainTextEdit, previous: list[str]) -> list[str]:
        text = editor.toPlainText()
        return (
            previous.copy()
            if text == _display_text("\n".join(previous))
            else [line for line in text.splitlines() if line]
        )

    def accept(self) -> None:
        """Persist an independent defaults snapshot, then expose the accepted request."""
        if not self.start.isEnabled():
            return
        previous = self._defaults
        mode = api.ScanMode(self.mode.currentData())
        if mode == api.ScanMode.MFT:
            self.error.setText(_("Fast scanning is unavailable in this build."))
            return
        options = ScanOptionsModel(
            targets=self.target_paths(),
            mode=mode,
            threads=int(self.threads.value()),
            follow_symlinks=self.follow_symlinks.isChecked(),
            cross_filesystems=self.cross_filesystems.isChecked(),
            exclude=ExcludeRulesModel(
                paths=self._lines(self.exclude_paths, previous.exclude.paths),
                globs=self._lines(self.globs, previous.exclude.globs),
                hidden=self.hidden.isChecked(),
                system=self.system.isChecked(),
            ),
            owner=previous.owner,
            hardlinks=previous.hardlinks,
            include_ads=previous.include_ads,
            show_ntfs_metafiles=previous.show_ntfs_metafiles,
        )
        snapshot = deepcopy(self._settings)
        snapshot.default_scan = options
        try:
            if self._paths is not None:
                save_settings(snapshot, self._paths)
        except OSError as error:
            self.error.setText(
                _("Could not save scan options: {error}").format(error=_display_text(str(error)))
            )
            return
        self._settings.default_scan = options
        self.request = api.ScanRequest(
            options.targets.copy(),
            mode=options.mode,
            threads=options.threads,
            follow_symlinks=options.follow_symlinks,
            cross_filesystems=options.cross_filesystems,
            exclude=api.ExcludeRules(
                options.exclude.paths.copy(),
                options.exclude.globs.copy(),
                options.exclude.hidden,
                options.exclude.system,
            ),
            owner=options.owner,
            hardlinks=options.hardlinks,
            include_ads=options.include_ads,
            show_ntfs_metafiles=options.show_ntfs_metafiles,
        )
        super().accept()

    def _restart(self) -> None:
        if self._relaunch is not None and self.restart.isEnabled():
            try:
                self._relaunch(self.target_paths())
            except (api.DafreeError, OSError) as error:
                self.error.setText(_display_text(str(error)))
            else:
                QApplication.quit()
