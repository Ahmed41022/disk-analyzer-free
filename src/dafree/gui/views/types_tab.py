"""Scoped extension tables and bounded charts from one background native report."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from PySide6.QtCore import (
    QAbstractTableModel,
    QLocale,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    Signal,
)
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QScrollArea,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from dafree import api
from dafree.api.analysis import ChartSlice, ExtStat, ext_breakdown
from dafree.gui import _display_text, _format_size, _number_translation
from dafree.gui.controllers.task_runner import TaskRunner
from dafree.gui.widgets.bar_chart import BarChart
from dafree.gui.widgets.breadcrumb import Breadcrumb
from dafree.i18n import N_, _
from dafree.settings import Settings

_EMPTY = QModelIndex()
_COLUMNS = 6
_TOP = 15
_U64_MAX = (1 << 64) - 1
_I64_MAX = (1 << 63) - 1
_SURROGATE_MIN = 0xD800
_SURROGATE_MAX = 0xDFFF
_SAFE_EXTENSION = re.compile(r"[A-Za-z0-9_]+")
_CATEGORIES = {
    api.ExtCategory.IMAGE: N_("Images"),
    api.ExtCategory.VIDEO: N_("Videos"),
    api.ExtCategory.AUDIO: N_("Audio"),
    api.ExtCategory.ARCHIVE: N_("Archives"),
    api.ExtCategory.DOCUMENT: N_("Documents"),
    api.ExtCategory.CODE: N_("Code"),
    api.ExtCategory.EXECUTABLE: N_("Executables"),
    api.ExtCategory.DISK_IMAGE: N_("Disk images"),
    api.ExtCategory.SYSTEM: N_("System files"),
    api.ExtCategory.OTHER: N_("Other file types"),
}
type Index = QModelIndex | QPersistentModelIndex


@dataclass(frozen=True)
class _TypesJob:
    owner: object
    generation: int


@dataclass(frozen=True)
class _TypesReport:
    rows: tuple[ExtStat, ...]
    slices: tuple[ChartSlice, ...]
    total_size: int
    alloc_unreliable: bool


def _extension_label(ext: str) -> str:
    return _display_text(f".{ext}" if ext else _("No extension"))


def _prepare(tree: api.Tree, scope: int) -> _TypesReport:
    rows = tuple(ext_breakdown(tree, scope))
    positive = [row for row in rows if row.size > 0]
    slices = [ChartSlice(_extension_label(row.ext), row.size) for row in positive[:_TOP]]
    if len(positive) > _TOP:
        slices.append(
            ChartSlice(
                _("Other"), min(_U64_MAX, sum(row.size for row in positive[_TOP:])), is_other=True
            )
        )
    info = tree.node(scope)
    return _TypesReport(
        rows, tuple(slices), info.size, bool(info.flags & api.NodeFlags.ALLOC_UNRELIABLE)
    )


def _extension_query(ext: str) -> str:
    if _SAFE_EXTENSION.fullmatch(ext) and ext.casefold() != "or":
        return f"ext:{ext}"
    # Qt transports this signal as QString; escape lone native surrogates as JSON too.
    has_surrogates = any(_SURROGATE_MIN <= ord(character) <= _SURROGATE_MAX for character in ext)
    return "ext:" + json.dumps(ext, ensure_ascii=has_surrogates)


class _TypesModel(QAbstractTableModel):
    """Display grouped immutable extension statistics without per-node objects."""

    EXT_COLUMN = 0
    CATEGORY_COLUMN = 1
    FILES_COLUMN = 2
    SIZE_COLUMN = 3
    ALLOC_COLUMN = 4
    PERCENT_COLUMN = 5

    def __init__(self, settings: Settings, parent: QWidget) -> None:
        super().__init__(parent)
        self._settings = settings
        self._report = _TypesReport((), (), 0, False)

    def set_report(self, report: _TypesReport | None) -> None:
        """Replace all grouped rows and invalidate Qt's previous indexes."""
        self.beginResetModel()
        self._report = report if report is not None else _TypesReport((), (), 0, False)
        self.endResetModel()

    def rowCount(self, parent: Index = _EMPTY) -> int:
        """Expose each extension once at the flat model root."""
        return 0 if parent.isValid() else len(self._report.rows)

    def columnCount(self, parent: Index = _EMPTY) -> int:
        """Expose extension, category, files, size, allocated size, and scope share."""
        return 0 if parent.isValid() else _COLUMNS

    def report_row(self, row: int) -> ExtStat:
        """Return the exact grouped native values associated with a visible row."""
        if not 0 <= row < len(self._report.rows):
            raise IndexError(row)
        return self._report.rows[row]

    def data(self, index: Index, role: int = Qt.ItemDataRole.DisplayRole) -> str | int | None:
        """Supply plain text values and numeric alignment for supported Qt roles."""
        if (
            not index.isValid()
            or index.model() is not self
            or not (0 <= index.row() < self.rowCount() and 0 <= index.column() < _COLUMNS)
        ):
            return None
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return (
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if index.column() >= self.FILES_COLUMN
                else None
            )
        if role not in (
            Qt.ItemDataRole.DisplayRole,
            Qt.ItemDataRole.ToolTipRole,
            Qt.ItemDataRole.AccessibleTextRole,
        ):
            return None
        return self._display(self.report_row(index.row()), index.column())

    def _display(self, row: ExtStat, column: int) -> str:
        if column == self.EXT_COLUMN:
            return _extension_label(row.ext)
        if column == self.CATEGORY_COLUMN:
            return _(_CATEGORIES[row.category])
        if column == self.FILES_COLUMN:
            locale = QLocale()
            return (
                locale.toString(row.files)
                if row.files <= _I64_MAX
                else str(row.files).translate(_number_translation(locale.name(), "."))
            )
        if column == self.PERCENT_COLUMN:
            percent = 100 * row.size / self._report.total_size if self._report.total_size else 0.0
            return QLocale().toString(percent, "f", 1) + QLocale().percent()
        approximate = column == self.ALLOC_COLUMN and self._report.alloc_unreliable
        return ("≈" if approximate else "") + _format_size(
            row.alloc if column == self.ALLOC_COLUMN else row.size,
            self._settings.units,
            self._settings.unit_style,
        )

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> str | None:
        """Translate table headers when Qt asks for them."""
        if orientation != Qt.Orientation.Horizontal or role != Qt.ItemDataRole.DisplayRole:
            return None
        labels = (
            _("Extension"),
            _("Category"),
            _("Files"),
            _("Size"),
            _("Allocated"),
            _("Scope share (%)"),
        )
        return labels[section] if 0 <= section < _COLUMNS else None

    def refresh_settings(self) -> None:
        """Reformat the existing report without repeating native analysis."""
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, self.PERCENT_COLUMN)
        if self.rowCount():
            self.dataChanged.emit(
                self.index(0, 0), self.index(self.rowCount() - 1, self.PERCENT_COLUMN)
            )


class _TypesTable(QTableView):
    """Activate extension rows consistently across Qt platform styles."""

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Treat Return and keypad Enter as one activation of the current row."""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.currentIndex().isValid():
                self.activated.emit(self.currentIndex())
            event.accept()
            return
        super().keyPressEvent(event)


class TypesTab(QWidget):
    """Prepare scoped grouped tables and charts while rejecting superseded results."""

    ready = Signal()
    findRequested = Signal(object, object, str)

    def __init__(
        self, settings: Settings, runner: TaskRunner, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._runner = runner
        self._owner, self._generation = object(), 0
        self._building = self._pending = False
        self.tree: api.Tree | None = None
        self.scope: int | None = None
        layout = QVBoxLayout(self)
        self.breadcrumb = Breadcrumb(self, allow_synthetic_root=True)
        self.breadcrumb.nodeActivated.connect(self.select_node)
        layout.addWidget(self.breadcrumb)
        self.message = QLabel(_("Choose a target to scan."), self)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.model = _TypesModel(settings, self)
        self.table = _TypesTable(splitter)
        self.table.setModel(self.model)
        self.table.setAccessibleName(_("Extension breakdown"))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.activated.connect(self._activate)
        scroll = QScrollArea(splitter)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(240)
        self.bar = BarChart(settings, scroll)
        scroll.setWidget(self.bar)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([640, 320])
        layout.addWidget(splitter, 1)
        runner.finished.connect(self._finished)
        runner.failed.connect(self._failed)

    def clear(self) -> None:
        """Release the report and invalidate results associated with the old scan."""
        self._generation += 1
        self._pending = False
        self.tree = None
        self.scope = None
        self.model.set_report(None)
        self.bar.set_data(())
        self.breadcrumb.clear()
        self.message.setText(_("Choose a target to scan."))
        self.message.show()

    def set_tree(self, tree: api.Tree) -> None:
        """Start at the sole scan target or combined synthetic root for multiple targets."""
        if tree is self.tree:
            return
        self.clear()
        self.tree = tree
        roots = tree.roots()
        self.select_node(roots[0] if len(roots) == 1 else 0)

    def select_node(self, node: int) -> None:
        """Use a selected directory, or a selected file's parent, as report scope."""
        if self.tree is None:
            return
        info = self.tree.node(node)
        scope = node if info.flags & api.NodeFlags.DIR else (self.tree.parent(node) or 0)
        if scope != self.scope:
            self.scope = scope
            self.breadcrumb.set_node(self.tree, scope)
            self._schedule()

    def refresh_settings(self) -> None:
        """Reformat cached table/chart values without repeating native aggregation."""
        self.model.refresh_settings()
        self.bar.refresh_settings()

    def _schedule(self) -> None:
        self._generation += 1
        self._pending = self.tree is not None
        self.model.set_report(None)
        self.bar.set_data(())
        if self._pending:
            self.message.setText(_("Preparing extension breakdown…"))
            self.message.show()
        self._submit_pending()

    def _submit_pending(self) -> None:
        if self._building or not self._pending or self.tree is None or self.scope is None:
            return
        self._pending = False
        self._building = True
        job = _TypesJob(self._owner, self._generation)
        tree, scope = self.tree, self.scope
        self._runner.submit(lambda: _prepare(tree, scope), task_id=job)

    def _finished(self, job: object, result: object) -> None:
        if not isinstance(job, _TypesJob) or job.owner is not self._owner:
            return
        self._building = False
        if job.generation == self._generation and isinstance(result, _TypesReport):
            self.model.set_report(result)
            self.bar.set_data(result.slices)
            self.message.setText(_("No data for this selection."))
            self.message.setVisible(not result.rows)
            self.ready.emit()
        self._submit_pending()

    def _failed(self, job: object, message: str) -> None:
        if isinstance(job, _TypesJob) and job.owner is self._owner:
            self._building = False
            if job.generation == self._generation:
                self.message.setText(
                    _("Could not prepare extension breakdown: {error}").format(
                        error=_display_text(message)
                    )
                )
                self.message.show()
            self._submit_pending()

    def _activate(self, index: QModelIndex) -> None:
        if (
            self.tree is not None
            and self.scope is not None
            and index.isValid()
            and (index.model() is self.model and 0 <= index.row() < self.model.rowCount())
        ):
            self.findRequested.emit(
                self.tree, self.scope, _extension_query(self.model.report_row(index.row()).ext)
            )
