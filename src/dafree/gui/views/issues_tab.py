"""Bounded retained diagnostics; filtering and export are added in T4.13."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtWidgets import QLabel, QTableView, QVBoxLayout, QWidget

from dafree.api.types import IssueKind, ScanIssue
from dafree.gui import _display_text
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


class IssuesTab(QWidget):
    """Show the core's bounded retained issues and the complete diagnostic count."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
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

    def set_issues(self, issues: Sequence[ScanIssue], total: int) -> None:
        """Render only retained diagnostics and state when the complete count is larger."""
        self.model.replace(issues)
        shown = len(self.model.issues)
        self.summary.setText(
            _("Showing {shown} of {total} issues").format(shown=shown, total=total)
            if total
            else _("No scan issues.")
        )
