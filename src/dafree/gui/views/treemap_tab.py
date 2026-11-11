"""Treemap tab with node-based parent navigation and shared menu forwarding."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from dafree import api
from dafree.gui.controllers.task_runner import TaskRunner
from dafree.gui.widgets.breadcrumb import Breadcrumb
from dafree.gui.widgets.treemap import TreemapWidget
from dafree.settings import Settings


class TreemapTab(QWidget):
    """Lazily host the treemap widget and its zoom breadcrumb."""

    nodeSelected = Signal(object, object)
    contextMenuRequested = Signal(object, object, object)

    def __init__(
        self, settings: Settings, runner: TaskRunner, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.breadcrumb = Breadcrumb(self, allow_synthetic_root=True)
        self.widget = TreemapWidget(settings, runner, self)
        layout.addWidget(self.breadcrumb)
        layout.addWidget(self.widget, 1)
        self.breadcrumb.nodeActivated.connect(self.widget.zoom_to)
        self.widget.zoomChanged.connect(self._zoom_changed)
        self.widget.nodeSelected.connect(
            lambda node: self.nodeSelected.emit(self.widget.tree, node)
        )
        self.widget.contextMenuRequested.connect(
            lambda node, point: self.contextMenuRequested.emit(self.widget.tree, node, point)
        )

    def _zoom_changed(self, node: int) -> None:
        if self.widget.tree is not None:
            self.breadcrumb.set_node(self.widget.tree, node)

    def set_tree(self, tree: api.Tree) -> None:
        """Retain the latest native tree and invalidate a replaced scan namespace."""
        self.widget.set_tree(tree)

    def clear(self) -> None:
        """Clear both navigation and rendered references when a scan starts."""
        self.widget.clear()
        self.breadcrumb.clear()

    def select_node(self, node: int) -> None:
        """Highlight a tree selection without changing zoom or emitting selection."""
        self.widget.select_node(node)

    def refresh_settings(self) -> None:
        """Apply committed style and size-format settings to the next render."""
        self.widget.refresh_settings()
