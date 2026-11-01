"""Asynchronous native volume metadata and small, accessible capacity rows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from dafree import api
from dafree.gui import _display_text
from dafree.gui.controllers.task_runner import TaskRunner
from dafree.i18n import _
from dafree.settings import Settings


def display_mount(path: str) -> str:
    """Remove a verbatim Windows prefix only from a displayed mount label."""
    if path.startswith("\\\\?\\UNC\\"):
        path = "\\\\" + path[8:]
    elif path.startswith("\\\\?\\"):
        path = path[4:]
    return _display_text(path)


@dataclass(frozen=True)
class _VolumeJob:
    owner: object


class VolumeList(QWidget):
    """Discover volumes in a worker; retain raw DTOs rather than QString target paths."""

    targetRequested = Signal(object)
    loaded = Signal()

    def __init__(
        self,
        settings: Settings,
        runner: TaskRunner,
        parent: QWidget | None = None,
        *,
        provider: Callable[[], list[api.VolumeInfo]] | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings, self._runner = settings, runner
        self._provider = api.platform.volumes if provider is None else provider
        self._job = _VolumeJob(object())
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.message = QLabel(_("Loading volumes…"), self)
        self.message.setWordWrap(True)
        self.list = QListWidget(self)
        self.list.setAccessibleName(_("Volumes"))
        layout.addWidget(self.message)
        layout.addWidget(self.list)
        self.list.itemActivated.connect(self._activate)
        runner.finished.connect(self._finished)
        runner.failed.connect(self._failed)

    @property
    def loading(self) -> bool:
        """Whether this widget already has a metadata request in flight."""
        return self._loading

    def refresh(self) -> None:
        """Queue one read-only host query without blocking Qt or stacking requests."""
        if not self._loading:
            self._loading = True
            self.message.setText(_("Loading volumes…"))
            self.message.show()
            self._runner.submit(self._provider, task_id=self._job)

    def _finished(self, job: object, result: object) -> None:
        if job is self._job:
            if not isinstance(result, list) or not all(
                isinstance(v, api.VolumeInfo) for v in result
            ):
                self._failed(job, _("Invalid volume metadata"))
                return
            self.set_volumes(result)
            self._loading = False
            self.loaded.emit()

    def _failed(self, job: object, message: str) -> None:
        if job is self._job:
            self._loading = False
            self.message.setText(
                _("Could not read volumes: {error}").format(error=_display_text(message))
            )
            self.message.show()
            self.loaded.emit()

    def set_volumes(self, volumes: list[api.VolumeInfo]) -> None:
        """Offer positive-capacity mounts once; omit kernel pseudo-filesystems."""
        self.list.clear()
        seen: set[str] = set()
        for volume in volumes:
            if not volume.mount or volume.total <= 0 or volume.mount in seen:
                continue
            seen.add(volume.mount)
            self._add_volume(volume)
        self.message.setText(_("No volumes available"))
        self.message.setVisible(self.list.count() == 0)

    def _add_volume(self, volume: api.VolumeInfo) -> None:
        mount = display_mount(volume.mount)
        title = (
            _("{label} ({mount})").format(label=_display_text(volume.label), mount=mount)
            if volume.label
            else mount
        )
        item = QListWidgetItem(self.list)
        item.setData(Qt.ItemDataRole.UserRole, volume)
        item.setToolTip(_display_text(volume.mount))
        row = QWidget(self.list)
        layout = QHBoxLayout(row)
        icon = QLabel(row)
        pixmap = (
            QStyle.StandardPixmap.SP_DriveNetIcon
            if volume.is_network
            else QStyle.StandardPixmap.SP_DriveHDIcon
        )
        icon.setPixmap(self.style().standardIcon(pixmap).pixmap(QSize(24, 24)))
        layout.addWidget(icon)
        details = QVBoxLayout()
        label = QLabel(title, row)
        label.setTextFormat(Qt.TextFormat.PlainText)
        details.addWidget(label)
        bar = QProgressBar(row)
        bar.setRange(0, 1000)
        bar.setValue(round((volume.total - min(volume.free, volume.total)) / volume.total * 1000))
        free = api.format_size(volume.free, self._settings.units, self._settings.unit_style)
        total = api.format_size(volume.total, self._settings.units, self._settings.unit_style)
        description = _("{free} free of {total}").format(free=free, total=total)
        bar.setFormat(description)
        bar.setAccessibleName(_("{mount}: {capacity}").format(mount=mount, capacity=description))
        item.setData(
            Qt.ItemDataRole.AccessibleTextRole,
            _("{mount}: {capacity}").format(mount=mount, capacity=description),
        )
        details.addWidget(bar)
        layout.addLayout(details, 1)
        item.setSizeHint(row.sizeHint())
        self.list.setItemWidget(item, row)

    def _activate(self, item: QListWidgetItem) -> None:
        volume = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(volume, api.VolumeInfo):
            self.targetRequested.emit(volume.mount)
