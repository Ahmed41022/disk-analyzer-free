"""Paged, read-only Qt tables over ranked native node IDs."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPersistentModelIndex, Qt

from dafree import api
from dafree.gui import _display_text, _format_size
from dafree.i18n import _
from dafree.settings import Settings

_PAGE_SIZE = 64
_MAX_PAGES = 8
_COLUMN_COUNT = 4
_EMPTY = QModelIndex()
_DISPLAY = int(Qt.ItemDataRole.DisplayRole)
_TOOLTIP = int(Qt.ItemDataRole.ToolTipRole)
_ACCESSIBLE = int(Qt.ItemDataRole.AccessibleTextRole)
_ALIGNMENT = int(Qt.ItemDataRole.TextAlignmentRole)
type Index = QModelIndex | QPersistentModelIndex


@dataclass(frozen=True)
class _NodeRow:
    info: api.NodeInfo
    name: str
    path: str


class NodeListModel(QAbstractTableModel):
    """Keep rank order and lazily cache at most eight 64-row metadata pages."""

    NAME_COLUMN = 0
    SIZE_COLUMN = 1
    ALLOC_COLUMN = 2
    PATH_COLUMN = 3

    def __init__(
        self,
        tree: api.Tree | None,
        nodes: list[int],
        settings: Settings,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self.tree: api.Tree | None = None
        self._nodes: list[int] = []
        self._pages: OrderedDict[int, list[_NodeRow]] = OrderedDict()
        self.set_nodes(tree, nodes)

    def set_nodes(self, tree: api.Tree | None, nodes: list[int]) -> None:
        """Replace the scan namespace and ranking without eagerly reading metadata."""
        count = len(tree) if tree is not None else 0
        if any(not 0 <= node < count for node in nodes):
            raise IndexError("ranked node is outside the tree")
        self.beginResetModel()
        self.tree, self._nodes = tree, list(nodes)
        self._pages.clear()
        self.endResetModel()

    def rowCount(self, parent: Index = _EMPTY) -> int:
        """Expose the ranked list only at the model root."""
        return 0 if parent.isValid() else len(self._nodes)

    def columnCount(self, parent: Index = _EMPTY) -> int:
        """Expose name, size, allocated size, and path columns."""
        return 0 if parent.isValid() else _COLUMN_COUNT

    def node_at(self, row: int) -> int:
        """Return a ranked native ID without fetching node metadata."""
        if not 0 <= row < len(self._nodes):
            raise IndexError(row)
        return self._nodes[row]

    def _row(self, row: int) -> _NodeRow:
        self.node_at(row)
        tree = self.tree
        if tree is None:
            raise IndexError(row)
        page = row // _PAGE_SIZE
        if page not in self._pages:
            start = page * _PAGE_SIZE
            self._pages[page] = [
                _NodeRow(tree.node(node), tree.name(node), tree.path(node))
                for node in self._nodes[start : start + _PAGE_SIZE]
            ]
            if len(self._pages) > _MAX_PAGES:
                self._pages.popitem(last=False)
        self._pages.move_to_end(page)
        return self._pages[page][row % _PAGE_SIZE]

    def data(self, index: Index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Return bounded cached metadata for supported display and accessibility roles."""
        if (
            not index.isValid()
            or index.model() is not self
            or not (
                0 <= index.row() < len(self._nodes) and 0 <= index.column() < self.columnCount()
            )
        ):
            return None
        column = index.column()
        if role == _ALIGNMENT:
            return (
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if column in (self.SIZE_COLUMN, self.ALLOC_COLUMN)
                else None
            )
        if role not in (_DISPLAY, _TOOLTIP, _ACCESSIBLE):
            return None
        row = self._row(index.row())
        if role == _TOOLTIP:
            return _display_text(row.path)
        if role == _ACCESSIBLE:
            return _("{name}, {size}, {path}").format(
                name=_display_text(row.name),
                size=self._size(row.info.size),
                path=_display_text(row.path),
            )
        return self._display(row, column)

    def _display(self, row: _NodeRow, column: int) -> str:
        if column == self.NAME_COLUMN:
            return _display_text(row.name)
        if column == self.PATH_COLUMN:
            return _display_text(row.path)
        approximate = (
            column == self.ALLOC_COLUMN and row.info.flags & api.NodeFlags.ALLOC_UNRELIABLE
        )
        value = row.info.alloc if column == self.ALLOC_COLUMN else row.info.size
        return ("≈" if approximate else "") + self._size(value)

    def _size(self, value: int) -> str:
        return _format_size(value, self._settings.units, self._settings.unit_style)

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> str | None:
        """Translate logical column headers using the current application locale."""
        if orientation != Qt.Orientation.Horizontal or role != _DISPLAY:
            return None
        labels = (_("Name"), _("Size"), _("Allocated"), _("Path"))
        return labels[section] if 0 <= section < len(labels) else None

    def refresh_settings(self) -> None:
        """Notify Qt of unit/locale changes while retaining ranked IDs and native pages."""
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, self.PATH_COLUMN)
        if self._nodes:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._nodes) - 1, self.PATH_COLUMN),
                [_DISPLAY, _ACCESSIBLE],
            )
