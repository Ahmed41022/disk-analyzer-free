"""Bounded largest-file/folder reports prepared away from the GUI thread."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QLocale, QModelIndex, QPoint, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from dafree import api
from dafree.api.analysis import TopKind, top_n
from dafree.gui import _display_text
from dafree.gui.controllers.task_runner import TaskRunner
from dafree.gui.models.list_models import NodeListModel
from dafree.gui.widgets.breadcrumb import Breadcrumb
from dafree.i18n import _
from dafree.settings import Settings


@dataclass(frozen=True)
class _TopJob:
    owner: object
    generation: int


def _prepare(tree: api.Tree, scope: int, kind: TopKind, n: int, leaf_only: bool) -> list[int]:
    return top_n(tree, scope, kind, n, leaf_only=leaf_only)


class _TopTable(QTableView):
    """Make result activation consistent across Qt platform styles."""

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Activate the current result once on either Return or keypad Enter."""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            index = self.currentIndex()
            if index.isValid():
                self.activated.emit(index)
            event.accept()
            return
        super().keyPressEvent(event)


class TopTab(QWidget):
    """Display ranked node IDs with coalesced requests and immutable-scan identity."""

    ready = Signal()
    nodeSelected = Signal(object, object)
    contextMenuRequested = Signal(object, object, object)

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
        self.kind = QComboBox(self)
        self.kind.setAccessibleName(_("Ranked items"))
        self.kind.addItem(_("Files"), TopKind.FILES)
        self.kind.addItem(_("Folders"), TopKind.DIRS)
        self.limit = QComboBox(self)
        self.limit.setAccessibleName(_("Result limit"))
        for count in (20, 50, 100, 500):
            self.limit.addItem(QLocale().toString(count), count)
        self.leaf_only = QCheckBox(_("Leaf folders only"), self)
        self.leaf_only.setToolTip(
            _("Include folders with no child folder using at least one percent of their size.")
        )
        self.leaf_only.setEnabled(False)
        form = QFormLayout()
        form.addRow(_("Ranked items"), self.kind)
        form.addRow(_("Result limit"), self.limit)
        form.addRow(self.leaf_only)
        layout.addLayout(form)
        self.breadcrumb = Breadcrumb(self, allow_synthetic_root=True)
        self.breadcrumb.nodeActivated.connect(self.select_node)
        layout.addWidget(self.breadcrumb)
        self.message = QLabel(_("Choose a target to scan."), self)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.model = NodeListModel(None, [], settings, self)
        self.table = _TopTable(self)
        self.table.setModel(self.model)
        self.table.setAccessibleName(_("Largest files and folders"))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.activated.connect(self._activate)
        layout.addWidget(self.table, 1)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.limit.currentIndexChanged.connect(self._schedule)
        self.leaf_only.toggled.connect(self._schedule)
        runner.finished.connect(self._finished)
        runner.failed.connect(self._failed)

    def clear(self) -> None:
        """Release displayed IDs and invalidate results from the previous scan."""
        self._generation += 1
        self._pending = False
        self.tree = None
        self.scope = None
        self.model.set_nodes(None, [])
        self.breadcrumb.clear()
        self.message.setText(_("Choose a target to scan."))
        self.message.show()

    def set_tree(self, tree: api.Tree) -> None:
        """Begin a new scan at its single target or combined synthetic root."""
        if tree is self.tree:
            return
        self.clear()
        self.tree = tree
        roots = tree.roots()
        self.select_node(roots[0] if len(roots) == 1 else 0)

    def select_node(self, node: int) -> None:
        """Rank a selected directory, using a selected file's parent as scope."""
        if self.tree is None:
            return
        info = self.tree.node(node)
        scope = node if info.flags & api.NodeFlags.DIR else (self.tree.parent(node) or 0)
        if scope != self.scope:
            self.scope = scope
            self.breadcrumb.set_node(self.tree, scope)
            self._schedule()

    def refresh_settings(self) -> None:
        """Reformat cached rows without reranking the tree."""
        self.model.refresh_settings()

    def _kind_changed(self) -> None:
        self.leaf_only.setEnabled(self.kind.currentData() == TopKind.DIRS)
        self._schedule()

    def _schedule(self) -> None:
        self._generation += 1
        self._pending = self.tree is not None
        self.model.set_nodes(self.tree, [])
        if self._pending:
            self.message.setText(_("Preparing largest items…"))
            self.message.show()
        self._submit_pending()

    def _submit_pending(self) -> None:
        if self._building or not self._pending or self.tree is None or self.scope is None:
            return
        self._pending = False
        self._building = True
        job = _TopJob(self._owner, self._generation)
        tree, scope, kind, n = (
            self.tree,
            self.scope,
            self.kind.currentData(),
            self.limit.currentData(),
        )
        leaf = kind == TopKind.DIRS and self.leaf_only.isChecked()
        self._runner.submit(lambda: _prepare(tree, scope, kind, n, leaf), task_id=job)

    def _finished(self, job: object, result: object) -> None:
        if not isinstance(job, _TopJob) or job.owner is not self._owner:
            return
        self._building = False
        if job.generation == self._generation and isinstance(result, list):
            self.model.set_nodes(self.tree, result)
            self.message.setText(_("No data for this selection."))
            self.message.setVisible(not result)
            self.ready.emit()
        self._submit_pending()

    def _failed(self, job: object, message: str) -> None:
        if isinstance(job, _TopJob) and job.owner is self._owner:
            self._building = False
            if job.generation == self._generation:
                self.message.setText(
                    _("Could not prepare largest items: {error}").format(
                        error=_display_text(message)
                    )
                )
                self.message.show()
            self._submit_pending()

    def _activate(self, index: QModelIndex) -> None:
        if self.tree is not None and index.isValid():
            self.nodeSelected.emit(self.tree, self.model.node_at(index.row()))

    def _context_menu(self, point: QPoint) -> None:
        index = self.table.currentIndex() if point.x() < 0 else self.table.indexAt(point)
        if self.tree is None or not index.isValid():
            return
        self.table.setCurrentIndex(index)
        position = self.table.visualRect(index).center() if point.x() < 0 else point
        self.contextMenuRequested.emit(
            self.tree, self.model.node_at(index.row()), self.table.viewport().mapToGlobal(position)
        )
