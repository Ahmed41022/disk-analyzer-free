"""Bounded retained diagnostics with kind filtering, clipboard copy, and new CSV reports."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from dafree.api.types import IssueKind, ScanIssue
from dafree.gui import _copy_text, _display_text
from dafree.gui.controllers.task_runner import TaskRunner
from dafree.i18n import _

_EMPTY = QModelIndex()
_MAX_ISSUES = 1000
_COLUMNS = 3


def issue_kind_text(kind: IssueKind) -> str:
    """Translate retained diagnostic categories rather than expose enum identifiers."""
    return {
        IssueKind.ACCESS_DENIED: _("Access denied"),
        IssueKind.NOT_FOUND: _("Not found"),
        IssueKind.PATH_TOO_LONG: _("Path too long"),
        IssueKind.INVALID_NAME: _("Invalid name"),
        IssueKind.IO: _("I/O error"),
        IssueKind.TIMEOUT: _("Timeout"),
        IssueKind.SYMLINK_LOOP: _("Symbolic link loop"),
        IssueKind.ORPHANED: _("Orphaned entry"),
        IssueKind.CHANGED: _("Changed during scan"),
        IssueKind.OTHER: _("Other"),
    }[kind]


class _IssuesModel(QAbstractTableModel):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.issues: tuple[ScanIssue, ...] = ()

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = _EMPTY) -> int:
        return 0 if parent.isValid() else len(self.issues)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = _EMPTY) -> int:
        return 0 if parent.isValid() else _COLUMNS

    def data(
        self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> str | None:
        if (
            role
            not in (
                Qt.ItemDataRole.DisplayRole,
                Qt.ItemDataRole.ToolTipRole,
                Qt.ItemDataRole.AccessibleTextRole,
            )
            or not index.isValid()
            or index.model() is not self
            or not 0 <= index.row() < len(self.issues)
            or not 0 <= index.column() < _COLUMNS
        ):
            return None
        issue = self.issues[index.row()]
        return (
            issue_kind_text(issue.kind),
            _display_text(issue.path),
            _display_text(issue.message),
        )[index.column()]

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> str | None:
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
            and 0 <= section < _COLUMNS
        ):
            return (_("Kind"), _("Path"), _("Message"))[section]
        return None

    def replace(self, issues: Sequence[ScanIssue]) -> None:
        retained = tuple(issues[:_MAX_ISSUES])
        if retained == self.issues:
            return
        self.beginResetModel()
        self.issues = retained
        self.endResetModel()


@dataclass(frozen=True)
class _ExportJob:
    owner: object


def _csv_rows(issues: Sequence[ScanIssue]) -> list[tuple[str, str, str]]:
    return [
        (issue_kind_text(issue.kind), _display_text(issue.path), _display_text(issue.message))
        for issue in issues
    ]


def _write_csv(
    path: Path, rows: Sequence[tuple[str, str, str]], headers: tuple[str, str, str]
) -> int:
    # Exclusive creation rejects existing files and final symlinks; no user file is replaced.
    created = False
    try:
        with path.open("x", encoding="utf-8", newline="") as stream:
            created = True
            writer = csv.writer(stream)
            writer.writerow(headers)
            writer.writerows(rows)
    except (OSError, csv.Error) as error:
        if created:
            raise OSError(
                _("The new report may be incomplete: {error}").format(error=str(error))
            ) from error
        raise
    return len(rows)


class IssuesTab(QWidget):
    """Filter retained diagnostics and copy/export the displayed subset to new files."""

    exportFinished = Signal(bool)

    def __init__(self, parent: QWidget | None = None, *, runner: TaskRunner | None = None) -> None:
        super().__init__(parent)
        self._runner = runner if runner is not None else TaskRunner(self)
        self._export_job = _ExportJob(object())
        self._exporting = False
        self._retained: tuple[ScanIssue, ...] = ()
        self._total = 0
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.kind_filter = QComboBox(self)
        self.kind_filter.setAccessibleName(_("Issue kind"))
        self.kind_filter.addItem(_("All kinds"), None)
        for kind in IssueKind:
            self.kind_filter.addItem(issue_kind_text(kind), kind.value)
        self.kind_filter.currentIndexChanged.connect(self._apply_filter)
        controls.addWidget(self.kind_filter)
        self.copy = QPushButton(_("Copy all"), self)
        self.copy.setToolTip(_("Copy all displayed issues."))
        self.copy.clicked.connect(self.copy_all)
        self.export = QPushButton(_("Export CSV"), self)
        self.export.setToolTip(
            _("Export retained issues matching the current filter to a new file.")
        )
        self.export.clicked.connect(self._choose_export)
        controls.addWidget(self.copy)
        controls.addWidget(self.export)
        controls.addStretch()
        layout.addLayout(controls)
        self.summary = QLabel(_("No scan issues."), self)
        self.table = QTableView(self)
        self.model = _IssuesModel(self.table)
        self.table.setModel(self.model)
        self.table.setAccessibleName(_("Scan issues"))
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.setColumnWidth(0, 140)
        self.table.setColumnWidth(1, 320)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.summary)
        layout.addWidget(self.table, 1)
        self.message = QLabel("", self)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self._runner.finished.connect(self._exported)
        self._runner.failed.connect(self._export_failed)
        self._update_buttons()

    def set_issues(self, issues: Sequence[ScanIssue], total: int) -> None:
        """Retain at most the core's 1,000 diagnostics, preserving the complete issue count."""
        self._retained, self._total = tuple(issues[:_MAX_ISSUES]), total
        self._apply_filter()

    def _apply_filter(self, index: int = 0) -> None:
        value = self.kind_filter.currentData()
        selected = IssueKind(value) if value is not None else None
        self.model.replace(
            [issue for issue in self._retained if selected is None or issue.kind == selected]
        )
        shown = len(self.model.issues)
        self.summary.setText(
            _("Showing {shown} of {total} issues").format(shown=shown, total=self._total)
            if self._total
            else _("No scan issues.")
        )
        self._update_buttons()

    def _update_buttons(self) -> None:
        available = self.model.rowCount() > 0
        self.copy.setEnabled(available)
        self.export.setEnabled(available and not self._exporting)

    @staticmethod
    def _headers() -> tuple[str, str, str]:
        return (_("Kind"), _("Path"), _("Message"))

    def copy_all(self) -> None:
        """Copy displayed diagnostic CSV plus lossless native strings in a JSON MIME payload."""
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(self._headers())
        writer.writerows(_csv_rows(self.model.issues))
        raw = [
            {"kind": issue.kind.name, "path": issue.path, "message": issue.message}
            for issue in self.model.issues
        ]
        _copy_text(
            stream.getvalue(),
            {
                "application/x-dafree-issues+json": json.dumps(raw, ensure_ascii=True).encode(
                    "ascii"
                )
            },
        )

    def _choose_export(self) -> None:
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            _("Export issues"),
            "",
            _("CSV files (*.csv)"),
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if path:
            self.export_to(Path(path))

    def export_to(self, path: Path) -> None:
        """Write a snapshot of matching issues in a worker, exclusively creating a new report."""
        if self._exporting or not self.model.issues:
            return
        rows, headers = _csv_rows(self.model.issues), self._headers()
        self._exporting = True
        self._update_buttons()
        self.message.setText(_("Exporting issues…"))
        self._runner.submit(lambda: _write_csv(path, rows, headers), task_id=self._export_job)

    def _exported(self, job: object, result: object) -> None:
        if job is self._export_job:
            self._exporting = False
            self._update_buttons()
            self.message.setText(_("Exported {count} issues.").format(count=result))
            self.exportFinished.emit(True)

    def _export_failed(self, job: object, message: str) -> None:
        if job is self._export_job:
            self._exporting = False
            self._update_buttons()
            self.message.setText(
                _(
                    "Could not export issues: {error}. "
                    "Choose a new filename; existing files are preserved."
                ).format(error=_display_text(message))
            )
            self.exportFinished.emit(False)
