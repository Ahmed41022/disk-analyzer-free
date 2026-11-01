"""Paged Qt adapter over the native flattened tree; no Python tree enumeration."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any
from weakref import ReferenceType, ref

from PySide6.QtCore import (
    QAbstractTableModel,
    QDateTime,
    QItemSelectionModel,
    QLocale,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
)

from dafree import api
from dafree.gui import _display_text
from dafree.i18n import _
from dafree.settings import ColumnId

_PAGE_SIZE = 200
_MAX_PAGES = 50
_ALLOC_UNRELIABLE = int(api.NodeFlags.ALLOC_UNRELIABLE)
_SORT_KEYS = {
    ColumnId.NAME: api.SortKey.NAME,
    ColumnId.SIZE: api.SortKey.SIZE,
    ColumnId.PCT_PARENT: api.SortKey.PCT_PARENT,
    ColumnId.ALLOC: api.SortKey.ALLOC,
    ColumnId.FILES: api.SortKey.FILES,
    ColumnId.DIRS: api.SortKey.DIRS,
    ColumnId.MTIME: api.SortKey.MTIME,
    ColumnId.OWNER: api.SortKey.OWNER,
    ColumnId.EXT: api.SortKey.EXT,
}
_EMPTY = QModelIndex()
_DISPLAY_ROLE = int(Qt.ItemDataRole.DisplayRole)
_TOOLTIP_ROLE = int(Qt.ItemDataRole.ToolTipRole)
_ACCESSIBLE_ROLE = int(Qt.ItemDataRole.AccessibleTextRole)
_ROW_ROLE = int(Qt.ItemDataRole.UserRole) + 1
_SUPPORTED_ROLES = frozenset((_DISPLAY_ROLE, _TOOLTIP_ROLE, _ACCESSIBLE_ROLE, _ROW_ROLE))
type Index = QModelIndex | QPersistentModelIndex


class TreeTableModel(QAbstractTableModel):
    """Cache at most fifty 200-row pages and notify Qt around structural changes."""

    ROW_ROLE = _ROW_ROLE

    def __init__(self, view: api.TreeView, columns: Sequence[ColumnId]) -> None:
        super().__init__()
        self.view = view
        self._row_count = view.row_count
        self.columns = tuple(columns)
        self._pages: OrderedDict[int, list[api.Row]] = OrderedDict()
        self._selection: ReferenceType[QItemSelectionModel] | None = None

    def bind_selection_model(self, selection: QItemSelectionModel) -> None:
        """Register the table's selection model for node-ID restoration on resets."""
        if selection.model() is not self:
            raise ValueError("selection model belongs to a different model")
        self._selection = ref(selection)

    def rowCount(self, parent: Index = _EMPTY) -> int:
        """Expose visible rows only at the flat model's root."""
        return 0 if parent.isValid() else self._row_count

    def columnCount(self, parent: Index = _EMPTY) -> int:
        """Expose the requested stable logical columns."""
        return 0 if parent.isValid() else len(self.columns)

    def _row(self, row: int) -> api.Row:
        if not 0 <= row < self._row_count:
            raise IndexError(row)
        page = row // _PAGE_SIZE
        if page not in self._pages:
            self._pages[page] = self.view.rows(page * _PAGE_SIZE, _PAGE_SIZE)
            if len(self._pages) > _MAX_PAGES:
                self._pages.popitem(last=False)
        self._pages.move_to_end(page)
        return self._pages[page][row % _PAGE_SIZE]

    def data(self, index: Index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Answer supported roles only; Qt's other paint probes never fetch a page."""
        if role not in _SUPPORTED_ROLES or not index.isValid():
            return None
        position, column = index.row(), index.column()
        if index.model() is not self or not (
            0 <= position < self._row_count and 0 <= column < len(self.columns)
        ):
            return None
        row = self._row(position)
        if role == _ROW_ROLE:
            return row
        if role == _TOOLTIP_ROLE:
            return _display_text(self.view.tree.path(row[0]))
        if role == _ACCESSIBLE_ROLE:
            return _("{name}, {kind}, {size}, {percent} of parent").format(
                name=_display_text(row[4]),
                kind=_("folder") if row[13] & api.NodeFlags.DIR else _("file"),
                size=api.format_size(row[5]),
                percent=self._percent(row[7]),
            )
        return self._display(row, self.columns[column])

    @staticmethod
    def _percent(value: float) -> str:
        return QLocale().toString(value * 100, "f", 1) + QLocale().percent()

    def _display(self, row: api.Row, column: ColumnId) -> str:  # noqa: PLR0911 -- nine columns.
        match column:
            case ColumnId.NAME:
                return _display_text(row[4])
            case ColumnId.SIZE | ColumnId.ALLOC:
                approximate = column == ColumnId.ALLOC and row[13] & _ALLOC_UNRELIABLE
                return ("≈" if approximate else "") + api.format_size(
                    row[6] if column == ColumnId.ALLOC else row[5]
                )
            case ColumnId.PCT_PARENT:
                return self._percent(row[7])
            case ColumnId.FILES | ColumnId.DIRS:
                return QLocale().toString(row[8] if column == ColumnId.FILES else row[9])
            case ColumnId.MTIME:
                return (
                    QLocale().toString(
                        QDateTime.fromSecsSinceEpoch(row[10]), QLocale.FormatType.ShortFormat
                    )
                    if row[10]
                    else "—"
                )
            case ColumnId.OWNER:
                return _display_text(row[11] or "")
            case ColumnId.EXT:
                return _display_text(row[12] or "")

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> str | None:
        """Translate headers on demand so they follow the active application locale."""
        if (
            orientation != Qt.Orientation.Horizontal
            or role != Qt.ItemDataRole.DisplayRole
            or not 0 <= section < len(self.columns)
        ):
            return None
        return {
            ColumnId.NAME: _("Name"),
            ColumnId.SIZE: _("Size"),
            ColumnId.PCT_PARENT: _("% of Parent"),
            ColumnId.ALLOC: _("Allocated"),
            ColumnId.FILES: _("Files"),
            ColumnId.DIRS: _("Folders"),
            ColumnId.MTIME: _("Last Modified"),
            ColumnId.OWNER: _("Owner"),
            ColumnId.EXT: _("Extension"),
        }[self.columns[section]]

    def node_at(self, row: int) -> int:
        """Map one visible row to its stable native node ID."""
        return self._row(row)[0]

    def row_data(self, row: int) -> api.Row:
        """Read a cached visible tuple directly for Python delegates, avoiding QVariant copies."""
        return self._row(row)

    def display_value(self, row: api.Row, column: ColumnId) -> str:
        """Share column formatting between Qt roles and the visible-cell paint path."""
        return self._display(row, column)

    def row_of(self, node: int) -> int | None:
        """Locate a visible node without walking or materializing the tree."""
        return self.view.index_of(node)

    def toggle(self, row: int) -> None:
        """Expand/collapse with accurate before/after Qt insertion/removal signals."""
        value = self._row(row)
        if not value[2]:
            return
        node = value[0]
        count = self.view.collapse_count(node) if value[3] else self.view.expansion_count(node)
        if not count:
            return
        if value[3]:
            self.beginRemoveRows(_EMPTY, row + 1, row + count)
            self.view.collapse(node)
            self._row_count = self.view.row_count
            self._pages.clear()
            self.endRemoveRows()
        else:
            self.beginInsertRows(_EMPTY, row + 1, row + count)
            self.view.expand(node)
            self._row_count = self.view.row_count
            self._pages.clear()
            self.endInsertRows()
        self.dataChanged.emit(self.index(row, 0), self.index(row, len(self.columns) - 1))

    def _reset(self, operation: Callable[[], None]) -> None:
        selection = self._selection() if self._selection else None
        selected = (
            [self.node_at(index.row()) for index in selection.selectedRows()] if selection else []
        )
        current = selection.currentIndex() if selection else _EMPTY
        current_node = self.node_at(current.row()) if current.isValid() else None
        self.beginResetModel()
        try:
            operation()
        finally:
            self._row_count = self.view.row_count
            self._pages.clear()
            self.endResetModel()
            if selection:
                for node in selected:
                    row = self.row_of(node)
                    if row is not None:
                        selection.select(
                            self.index(row, 0),
                            QItemSelectionModel.SelectionFlag.Select
                            | QItemSelectionModel.SelectionFlag.Rows,
                        )
                if current_node is not None and (row := self.row_of(current_node)) is not None:
                    selection.setCurrentIndex(
                        self.index(row, current.column()),
                        QItemSelectionModel.SelectionFlag.NoUpdate,
                    )

    def expand_all_children(self, row: int) -> None:
        """Expand one level of child directories in C++, keeping selection by ID."""
        node = self.node_at(row)
        self._reset(lambda: self.view.expand_children(node))

    def set_options(self, opts: api.ViewOptions) -> None:
        """Reset cached pages after native sorting/filtering and restore visible selection."""
        self._reset(lambda: self.view.set_options(opts))

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        """Delegate each column's sort to the native view, preserving other options."""
        if 0 <= column < len(self.columns):
            options = replace(
                self.view.options,
                sort=_SORT_KEYS[self.columns[column]],
                descending=order == Qt.SortOrder.DescendingOrder,
            )
            if options != self.view.options:
                self.set_options(options)
