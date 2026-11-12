"""Background folder and file-type reports with synchronized pie and bar views."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from dafree import api
from dafree.api.analysis import ChartKind, ChartSlice, chart_data
from dafree.gui import _display_text
from dafree.gui.controllers.task_runner import TaskRunner
from dafree.gui.widgets.bar_chart import BarChart
from dafree.gui.widgets.breadcrumb import Breadcrumb
from dafree.gui.widgets.pie_chart import PieChart
from dafree.i18n import _
from dafree.settings import Settings


@dataclass(frozen=True)
class _ChartJob:
    owner: object
    generation: int


def _prepare(tree: api.Tree, scope: int, kind: ChartKind) -> list[ChartSlice]:
    return chart_data(tree, scope, kind)


class ChartsTab(QWidget):
    """Prepare one bounded report at a time, discarding superseded scan/scope results."""

    ready = Signal()
    nodeSelected = Signal(object, object)

    def __init__(
        self, settings: Settings, runner: TaskRunner, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._runner = runner
        self._owner, self._generation = object(), 0
        self._building = False
        self._pending = False
        self.tree: api.Tree | None = None
        self.scope: int | None = None
        layout = QVBoxLayout(self)
        self.kind = QComboBox(self)
        self.kind.setAccessibleName(_("Chart metric"))
        for label, kind in (
            (_("Children by size"), ChartKind.CHILDREN_BY_SIZE),
            (_("Children by allocated space"), ChartKind.CHILDREN_BY_ALLOC),
            (_("Children by file count"), ChartKind.CHILDREN_BY_FILES),
            (_("Extensions by size"), ChartKind.EXT_BY_SIZE),
            (_("Extensions by file count"), ChartKind.EXT_BY_COUNT),
            (_("Categories by size"), ChartKind.CATEGORY_BY_SIZE),
        ):
            self.kind.addItem(label, kind)
        form = QFormLayout()
        form.addRow(_("Chart metric"), self.kind)
        layout.addLayout(form)
        self.breadcrumb = Breadcrumb(self, allow_synthetic_root=True)
        self.breadcrumb.nodeActivated.connect(self._activate)
        layout.addWidget(self.breadcrumb)
        self.message = QLabel(_("Choose a target to scan."), self)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        splitter = QSplitter(Qt.Orientation.Horizontal, scroll)
        self.pie, self.bar = PieChart(settings, splitter), BarChart(settings, splitter)
        scroll.setWidget(splitter)
        layout.addWidget(scroll, 1)
        self.pie.sliceActivated.connect(self._activate)
        self.bar.sliceActivated.connect(self._activate)
        self.kind.currentIndexChanged.connect(self._schedule)
        runner.finished.connect(self._finished)
        runner.failed.connect(self._failed)

    def clear(self) -> None:
        """Invalidate old jobs and release every previous scan and displayed slice."""
        self._generation += 1
        self._pending = False
        self.tree = None
        self.scope = None
        self.breadcrumb.clear()
        self.pie.set_data(())
        self.bar.set_data(())
        self.message.setText(_("Choose a target to scan."))
        self.message.show()

    def set_tree(self, tree: api.Tree) -> None:
        """Replace the scan namespace and begin at its target or combined roots."""
        if tree is self.tree:
            return
        self.clear()
        self.tree = tree
        roots = tree.roots()
        self.select_node(roots[0] if len(roots) == 1 else 0)

    def select_node(self, node: int) -> None:
        """Chart a selected directory, or the parent of a selected file."""
        if self.tree is None:
            return
        info = self.tree.node(node)
        scope = node if info.flags & api.NodeFlags.DIR else (self.tree.parent(node) or 0)
        if scope != self.scope:
            self.scope = scope
            self.breadcrumb.set_node(self.tree, scope)
            self._schedule()

    def refresh_settings(self) -> None:
        """Reformat existing values without traversing or regrouping the scan."""
        self.pie.refresh_settings()
        self.bar.refresh_settings()

    def _activate(self, node: int) -> None:
        if self.tree is not None and self.tree.node(node).flags & api.NodeFlags.DIR:
            self.select_node(node)
            if node != 0:  # The synthetic root has no selectable tree-table row.
                self.nodeSelected.emit(self.tree, node)

    def _schedule(self) -> None:
        self._generation += 1
        self._pending = self.tree is not None
        self.pie.set_data(())
        self.bar.set_data(())
        if self._pending:
            self.message.setText(_("Preparing charts…"))
            self.message.show()
        self._submit_pending()

    def _submit_pending(self) -> None:
        if self._building or not self._pending or self.tree is None or self.scope is None:
            return
        self._pending = False
        self._building = True
        job = _ChartJob(self._owner, self._generation)
        tree, scope, kind = self.tree, self.scope, self.kind.currentData()
        self._runner.submit(lambda: _prepare(tree, scope, kind), task_id=job)

    def _finished(self, job: object, result: object) -> None:
        if not isinstance(job, _ChartJob) or job.owner is not self._owner:
            return
        self._building = False
        if job.generation == self._generation and isinstance(result, list):
            count_values = self.kind.currentData() in (
                ChartKind.CHILDREN_BY_FILES,
                ChartKind.EXT_BY_COUNT,
            )
            self.pie.set_data(result, count_values=count_values)
            self.bar.set_data(result, count_values=count_values)
            self.message.hide()
            self.ready.emit()
        self._submit_pending()

    def _failed(self, job: object, message: str) -> None:
        if isinstance(job, _ChartJob) and job.owner is self._owner:
            self._building = False
            if job.generation == self._generation:
                self.message.setText(
                    _("Could not prepare charts: {error}").format(error=_display_text(message))
                )
                self.message.show()
            self._submit_pending()
