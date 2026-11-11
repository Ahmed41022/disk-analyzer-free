"""Lazy native tree preparation and a table/detail splitter."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, replace

from PySide6.QtCore import QLocale, QModelIndex, Qt, Signal
from PySide6.QtWidgets import QLabel, QSplitter, QVBoxLayout, QWidget

from dafree import api
from dafree.gui import _display_text, _format_size
from dafree.gui.controllers.task_runner import TaskRunner
from dafree.gui.models.tree_model import TreeTableModel
from dafree.gui.widgets.breadcrumb import Breadcrumb
from dafree.gui.widgets.tree_table import TreeTableView
from dafree.i18n import _
from dafree.paths import AppPaths
from dafree.settings import ColumnId, Settings


@dataclass(frozen=True)
class _ViewJob:
    owner: object
    generation: int


@dataclass(frozen=True)
class _PreparedView:
    view: api.TreeView
    current_row: int | None


class TreeTab(QWidget):
    """Prepare native sorting off-thread; construct Qt models and widgets only on the GUI thread."""

    ready = Signal()
    propertiesRequested = Signal(object, object)
    contextMenuRequested = Signal(object, object, object)
    nodeSelected = Signal(object, object)

    def __init__(
        self,
        settings: Settings,
        runner: TaskRunner,
        parent: QWidget | None = None,
        *,
        paths: AppPaths | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings, self._runner, self._paths = settings, runner, paths
        self._owner, self._generation = object(), 0
        self._building = False
        self._filter: api.FilterSpec | None = None
        self._pending: tuple[_ViewJob, api.Tree, api.ViewOptions, int | None] | None = None
        self.tree: api.Tree | None = None
        self.requested_tree: api.Tree | None = None
        self.table: TreeTableView | None = None
        self._layout = QVBoxLayout(self)
        self.breadcrumb = Breadcrumb(self)
        self.breadcrumb.nodeActivated.connect(self.select_node)
        self._layout.addWidget(self.breadcrumb)
        self.message = QLabel(_("Choose a target to start a scan."), self)
        self.message.setWordWrap(True)
        self._layout.addWidget(self.message)
        self.splitter = QSplitter(self)
        self.details = QLabel(_("Select a row to inspect it."), self.splitter)
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setWordWrap(True)
        self.details.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeading)
        self.details.setMinimumWidth(180)
        self.splitter.addWidget(self.details)
        self._layout.addWidget(self.splitter, 1)
        runner.finished.connect(self._prepared)
        runner.failed.connect(self._failed)

    def clear(self) -> None:
        """Invalidate in-flight results when a new scan changes the node-ID namespace."""
        self._generation += 1
        self._pending = None
        self.tree = self.requested_tree = None
        self.breadcrumb.clear()
        self.details.setText(_("Select a row to inspect it."))
        if self.table is not None:
            self.table.save_preferences()
            self.table.setParent(None)
            self.table.deleteLater()
            self.table = None
        self.message.setText(_("Choose a target to start a scan."))
        self.message.show()

    def set_tree(self, tree: api.Tree, *, selected_node: int | None = None) -> None:
        """Coalesce incoming snapshots, retaining sort policy and the focused native path."""
        if tree is self.requested_tree and selected_node is None:
            return
        self.requested_tree = tree
        self._generation += 1
        options = (
            self.table.tree_model.view.options
            if self.table
            else api.ViewOptions(filter=self._filter)
        )
        node = selected_node
        if node is None and self.table and (index := self.table.currentIndex()).isValid():
            node = self.table.tree_model.node_at(index.row())
        self._pending = (_ViewJob(self._owner, self._generation), tree, options, node)
        self.message.setText(_("Preparing tree view…"))
        self.message.show()
        self._submit_pending()

    def _submit_pending(self) -> None:
        if self._building or self._pending is None:
            return
        job, tree, options, node = self._pending
        self._pending = None
        self._building = True

        def prepare() -> _PreparedView:
            view = api.TreeView(tree, options)
            current = None
            if node is not None and node < len(tree):
                # A filter may hide the previously focused node in this snapshot.
                with suppress(ValueError):
                    current = view.expand_to(node)
            return _PreparedView(view, current)

        self._runner.submit(prepare, task_id=job)

    def _prepared(self, job: object, result: object) -> None:
        if not isinstance(job, _ViewJob) or job.owner is not self._owner:
            return
        self._building = False
        if job.generation == self._generation and isinstance(result, _PreparedView):
            if result.view.options.filter != self._filter:
                result.view.set_options(replace(result.view.options, filter=self._filter))
            if self.table is not None:
                self.table.save_preferences()
                self.table.setParent(None)
                self.table.deleteLater()
            model = TreeTableModel(result.view, list(ColumnId))
            self.table = TreeTableView(model, self._settings, self.splitter, paths=self._paths)
            self.splitter.insertWidget(0, self.table)
            self.splitter.setStretchFactor(0, 4)
            self.splitter.setStretchFactor(1, 1)
            self.tree = result.view.tree
            self.table.selectionModel().currentChanged.connect(self._selected)
            self.table.propertiesRequested.connect(
                lambda node: self.propertiesRequested.emit(self.tree, node)
            )
            self.table.contextMenuRequested.connect(
                lambda node, point: self.contextMenuRequested.emit(self.tree, node, point)
            )
            if model.rowCount():
                self.table.setCurrentIndex(model.index(result.current_row or 0, 0))
            self.message.hide()
            self.ready.emit()
        self._submit_pending()

    def _failed(self, job: object, message: str) -> None:
        if isinstance(job, _ViewJob) and job.owner is self._owner:
            self._building = False
            if job.generation == self._generation:
                self.message.setText(
                    _("Could not prepare tree: {error}").format(error=_display_text(message))
                )
                self.message.show()
            self._submit_pending()

    def select_node(self, node: int) -> None:
        """Select a node, preparing hidden ancestors off-thread when needed."""
        if self._building and self.requested_tree is not None:
            self.set_tree(self.requested_tree, selected_node=node)
            return
        if self.table is not None and self.tree is self.requested_tree:
            row = self.table.tree_model.row_of(node)
            if row is not None:
                self.table.setCurrentIndex(self.table.tree_model.index(row, 0))
                self.table.scrollTo(self.table.currentIndex())
                return
        if self.requested_tree is not None:
            self.set_tree(self.requested_tree, selected_node=node)

    def set_filter(self, spec: api.FilterSpec | None) -> None:
        """Retain the latest valid filter across pending snapshots and new scans."""
        self._filter = spec
        if self.table is not None:
            model = self.table.tree_model
            if model.view.options.filter != spec:
                model.set_options(replace(model.view.options, filter=spec))

    def refresh_units(self) -> None:
        """Reformat cached table values and the current selection details."""
        if self.table is not None:
            self.table.tree_model.set_units(self._settings.units, self._settings.unit_style)
            self._selected(self.table.currentIndex(), QModelIndex())

    def _selected(self, current: QModelIndex, previous: QModelIndex) -> None:
        if self.table is None or self.tree is None or not current.isValid():
            return
        row = self.table.tree_model.row_data(current.row())
        if self._building and self.tree is self.requested_tree and previous.isValid():
            self.set_tree(self.tree, selected_node=row[0])
        self.breadcrumb.set_node(self.tree, row[0])
        self.details.setText(
            _(
                "{name}\nSize: {size}\nAllocated: {allocated}\nFiles: {files}\nFolders: {folders}"
            ).format(
                name=_display_text(row[4]),
                size=_format_size(row[5], self._settings.units, self._settings.unit_style),
                allocated=_format_size(row[6], self._settings.units, self._settings.unit_style),
                files=QLocale().toString(row[8]),
                folders=QLocale().toString(row[9]),
            )
        )
        self.nodeSelected.emit(self.tree, row[0])
