"""Lossless node-based parent navigation and a middle-elided displayed path."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QStyle, QToolButton, QWidget

from dafree import api
from dafree.gui import _display_text
from dafree.i18n import _


class ElidedPathLabel(QLabel):
    """Display a bounded-width path while retaining its full accessible description."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setMinimumWidth(0)
        self.setTextFormat(Qt.TextFormat.PlainText)

    def set_path(self, path: str) -> None:
        """Escape only displayed surrogates; navigation continues to use native node IDs."""
        self._full_text = _display_text(path)
        self.setToolTip(self._full_text)
        self.setAccessibleName(self._full_text)
        self._update_text()

    def _update_text(self) -> None:
        self.setText(
            self.fontMetrics().elidedText(
                self._full_text, Qt.TextElideMode.ElideMiddle, self.width()
            )
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Recompute elision without changing the stored path or accessing the filesystem."""
        super().resizeEvent(event)
        self._update_text()


class Breadcrumb(QWidget):
    """Show the current path and navigate one native parent at a time."""

    nodeActivated = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tree: api.Tree | None = None
        self._parent_node: int | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.up = QToolButton(self)
        self.up.setText(_("Up"))
        self.up.setAccessibleName(_("Parent folder"))
        self.up.setToolTip(_("Parent folder"))
        self.up.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp))
        self.up.setEnabled(False)
        self.up.clicked.connect(self._activate_parent)
        self.path_label = ElidedPathLabel(self)
        layout.addWidget(self.up)
        layout.addWidget(self.path_label, 1)

    def set_node(self, tree: api.Tree, node: int) -> None:
        """Read one path/parent from the API; never reconstruct a path from displayed text."""
        self._tree = tree
        self._parent_node = tree.parent(node)
        self.path_label.set_path(tree.path(node))
        self.up.setEnabled(self._parent_node not in (None, 0))

    def clear(self) -> None:
        """Clear navigation when a new scan replaces the node-ID namespace."""
        self._tree = None
        self._parent_node = None
        self.path_label.set_path("")
        self.up.setEnabled(False)

    def _activate_parent(self) -> None:
        if self._parent_node not in (None, 0):
            self.nodeActivated.emit(self._parent_node)
