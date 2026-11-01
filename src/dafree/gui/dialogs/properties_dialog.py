"""Read-only node properties with lazy owner resolution and snapshot volume metadata."""

from __future__ import annotations

import os
from dataclasses import dataclass

from PySide6.QtCore import QDateTime, QLocale, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dafree import api
from dafree.gui import _copy_text, _display_text
from dafree.gui.controllers.task_runner import TaskRunner
from dafree.i18n import _
from dafree.settings import Settings

_NATIVE_PATH_MIME = "application/x-dafree-native-path"


def flag_labels(flags: api.NodeFlags) -> list[str]:
    """Describe native flags as human-readable badges, including accounting exclusions."""
    labels = (
        (api.NodeFlags.DIR, _("Folder")),
        (api.NodeFlags.SYMLINK, _("Symbolic link")),
        (api.NodeFlags.REPARSE, _("Reparse point")),
        (api.NodeFlags.MOUNT_POINT, _("Mount point")),
        (api.NodeFlags.HARDLINK_DUP, _("Hard link — not counted in totals")),
        (api.NodeFlags.HIDDEN, _("Hidden")),
        (api.NodeFlags.SYSTEM, _("System")),
        (api.NodeFlags.ACCESS_DENIED, _("Access denied")),
        (api.NodeFlags.PARTIAL, _("Partial scan")),
        (api.NodeFlags.SPARSE, _("Sparse")),
        (api.NodeFlags.COMPRESSED, _("Compressed")),
        (api.NodeFlags.CLOUD_PLACEHOLDER, _("Cloud placeholder")),
        (api.NodeFlags.EXCLUDED, _("Excluded from totals")),
        (api.NodeFlags.ERROR, _("Scan error")),
        (api.NodeFlags.ALLOC_UNRELIABLE, _("Allocated size is approximate")),
        (api.NodeFlags.SYNTHETIC, _("Combined scan")),
    )
    return [label for flag, label in labels if flags & flag]


def _kind(flags: api.NodeFlags) -> str:
    for flag, text in (
        (api.NodeFlags.SYNTHETIC, _("Scan")),
        (api.NodeFlags.SYMLINK, _("Symbolic link")),
        (api.NodeFlags.MOUNT_POINT, _("Mount point")),
        (api.NodeFlags.REPARSE, _("Reparse point")),
        (api.NodeFlags.DIR, _("Folder")),
    ):
        if flags & flag:
            return text
    return _("File")


def _timestamp(value: int | None) -> str:
    if value is None:
        return "—"
    date = QDateTime.fromSecsSinceEpoch(value).toLocalTime()
    return QLocale().toString(date, QLocale.FormatType.ShortFormat) if date.isValid() else "—"


def _mount_key(path: str) -> str:
    if os.name == "nt":
        if path.startswith("\\\\?\\UNC\\"):
            path = "\\\\" + path[8:]
        elif path.startswith("\\\\?\\"):
            path = path[4:]
    return os.path.normcase(os.path.normpath(path))


def _volume_for_path(path: str, volumes: tuple[api.VolumeInfo, ...]) -> api.VolumeInfo | None:
    key = _mount_key(path)
    matching = [
        volume
        for volume in volumes
        if volume.mount
        and (
            key == _mount_key(volume.mount)
            or key.startswith(_mount_key(volume.mount).rstrip(os.sep) + os.sep)
        )
    ]
    return max(matching, key=lambda volume: len(_mount_key(volume.mount)), default=None)


@dataclass(frozen=True)
class _OwnerJob:
    owner: object


class PropertiesDialog(QDialog):
    """Inspect one native node; opening resolves its owner off the GUI thread."""

    ownerResolved = Signal()

    def __init__(
        self,
        tree: api.Tree,
        node: int,
        settings: Settings,
        runner: TaskRunner,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Properties"))
        self.resize(560, 480)
        self._tree, self._node, self._settings = tree, node, settings
        self._path = tree.path(node)
        self._job = _OwnerJob(object())
        self.values: dict[str, QLabel] = {}
        layout = QVBoxLayout(self)
        self.form = QFormLayout()
        layout.addLayout(self.form)
        self._field("path", _("Full path"), _display_text(self._path))
        self.copy = QPushButton(_("Copy path"), self)
        self.copy.clicked.connect(self.copy_path)
        self.form.addRow("", self.copy)
        info = tree.node(node)
        self._field("type", _("Type"), _kind(info.flags))
        self._field("size", _("Size"), self._size(info.size))
        allocated = ("≈" if info.flags & api.NodeFlags.ALLOC_UNRELIABLE else "") + self._size(
            info.alloc
        )
        ratio = (
            QLocale().toString(info.alloc / info.size * 100, "f", 1) + QLocale().percent()
            if info.size
            else "—"
        )
        self._field(
            "allocated",
            _("Allocated"),
            _("{size} ({ratio} of logical size)").format(size=allocated, ratio=ratio),
        )
        self._field("files", _("Files"), QLocale().toString(info.files))
        self._field("dirs", _("Folders"), QLocale().toString(info.dirs))
        for key, title, value in (
            ("mtime", _("Modified"), info.mtime),
            ("btime", _("Created"), info.btime),
            ("atime", _("Accessed"), info.atime),
        ):
            self._field(key, title, _timestamp(value))
        self._field("owner", _("Owner"), _("Resolving…"))
        flags = QGridLayout()
        self.badges: list[QLabel] = []
        for index, text in enumerate(flag_labels(info.flags)):
            badge = QLabel(text, self)
            badge.setTextFormat(Qt.TextFormat.PlainText)
            badge.setFrameShape(QLabel.Shape.StyledPanel)
            badge.setWordWrap(True)
            self.badges.append(badge)
            flags.addWidget(badge, index // 2, index % 2)
        layout.addLayout(flags)
        volume = _volume_for_path(self._path, tree.meta().volumes)
        self._field("volume", _("Volume"), self._volume_text(volume))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        runner.finished.connect(self._owner_ready)
        runner.failed.connect(self._owner_failed)

        def resolve() -> str | None:
            tree.resolve_owners([node])
            return tree.node(node).owner

        runner.submit(resolve, task_id=self._job)

    def _field(self, key: str, title: str, text: str) -> None:
        label = QLabel(text, self)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setWordWrap(True)
        label.setAccessibleName(title)
        self.values[key] = label
        self.form.addRow(title, label)

    def _size(self, value: int) -> str:
        return api.format_size(value, self._settings.units, self._settings.unit_style)

    def _volume_text(self, volume: api.VolumeInfo | None) -> str:
        if volume is None:
            return "—"
        return _(
            "{label}\nMount: {mount}\nFilesystem: {filesystem}\nSerial: {serial}\n"
            "Capacity: {total}\nFree: {free}\nCluster size: {cluster}"
        ).format(
            label=_display_text(volume.label),
            mount=_display_text(volume.mount),
            filesystem=_display_text(volume.fs_type),
            serial=f"{volume.serial:X}",
            total=self._size(volume.total),
            free=self._size(volume.free),
            cluster=self._size(volume.cluster_size),
        )

    def _owner_ready(self, job: object, result: object) -> None:
        if job is self._job:
            self.values["owner"].setText(
                _display_text(result) if isinstance(result, str) and result else "—"
            )
            self.ownerResolved.emit()

    def _owner_failed(self, job: object, message: str) -> None:
        if job is self._job:
            self.values["owner"].setText(_("Unavailable"))
            self.values["owner"].setToolTip(_display_text(message))
            self.ownerResolved.emit()

    def copy_path(self) -> None:
        """Copy readable text plus a lossless native-string MIME payload for surrogate paths."""
        _copy_text(
            _display_text(self._path),
            {_NATIVE_PATH_MIME: self._path.encode("utf-8", errors="surrogatepass")},
        )
