"""Virtual tree table, keyboard navigation, and shared column preferences."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QFont, QKeyEvent, QPainter, QPaintEvent, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QMenu,
    QStyle,
    QStyleOptionViewItem,
    QTableView,
    QWidget,
)

from dafree import api
from dafree.gui.delegates import DisplayDelegate
from dafree.gui.delegates.name_delegate import NameDelegate
from dafree.gui.delegates.percent_delegate import PercentDelegate
from dafree.gui.delegates.size_delegate import SizeDelegate
from dafree.gui.models.tree_model import TreeTableModel
from dafree.i18n import _
from dafree.paths import AppPaths
from dafree.settings import ColumnId, ColumnSetting, Settings, save_settings

_ROW_HEIGHT = 24
_SAVE_DELAY_MS = 250
_SELECTED = QStyle.StateFlag.State_Selected.value
_FOCUSED = QStyle.StateFlag.State_HasFocus.value
_HOVERED = QStyle.StateFlag.State_MouseOver.value
_ALTERNATE = QStyleOptionViewItem.ViewItemFeature.Alternate.value


class _PaintOption(QStyleOptionViewItem):
    """Keep one owned frame font and already-painted row backgrounds for delegates."""

    _dafree_frame_font: QFont
    _dafree_row_background: bool


class TreeTableView(QTableView):
    """Display native pages without allocating items or resizing individual rows."""

    propertiesRequested = Signal(object)
    contextMenuRequested = Signal(object, QPoint)
    preferencesChanged = Signal()

    def __init__(  # noqa: PLR0915 -- assemble one table's fixed delegates and header policy.
        self,
        model: TreeTableModel,
        settings: Settings,
        parent: QWidget | None = None,
        *,
        paths: AppPaths | None = None,
    ) -> None:
        super().__init__(parent)
        self.tree_model = model
        model.unit_mode, model.unit_style = settings.units, settings.unit_style
        self._base_resolve_owner = model.view.options.resolve_owner
        self._settings = settings
        self._paths = paths
        self._restoring = True
        self._dirty = False
        self._widths: dict[int, int] = {}
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(_SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self.save_preferences)
        self.setModel(model)
        self.setItemDelegate(DisplayDelegate(self))
        if model.parent() is None:
            model.setParent(self)
        # Retain the Python wrapper too: the model's registration is deliberately weak.
        self._tree_selection = self.selectionModel()
        model.bind_selection_model(self._tree_selection)
        self.setAccessibleName(_("Directory tree"))
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerItem)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        vertical = self.verticalHeader()
        vertical.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vertical.setDefaultSectionSize(_ROW_HEIGHT)
        vertical.hide()
        header = self.horizontalHeader()
        header.setSectionsMovable(True)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        defaults = {value.id: value for value in Settings().columns}
        saved = {value.id: value for value in settings.columns}
        ordered = sorted(
            enumerate(model.columns),
            key=lambda entry: saved.get(entry[1], defaults[entry[1]]).order,
        )
        for visual, (logical, column) in enumerate(ordered):
            setting = saved.get(column, defaults[column])
            self._widths[logical] = setting.width
            self.setColumnWidth(logical, setting.width)
            self.setColumnHidden(logical, not setting.visible)
            header.moveSection(header.visualIndex(logical), visual)
        for logical, column in enumerate(model.columns):
            if column == ColumnId.NAME:
                self.setItemDelegateForColumn(logical, NameDelegate(model))
            elif column == ColumnId.PCT_PARENT:
                self.setItemDelegateForColumn(logical, PercentDelegate(self))
            elif column in (ColumnId.SIZE, ColumnId.ALLOC, ColumnId.FILES, ColumnId.DIRS):
                self.setItemDelegateForColumn(logical, SizeDelegate(self))
        options = model.view.options
        sort_column = next(
            (
                i
                for i, column in enumerate(model.columns)
                if api.SortKey[column.name] == options.sort
            ),
            0,
        )
        header.setSortIndicator(
            sort_column,
            Qt.SortOrder.DescendingOrder if options.descending else Qt.SortOrder.AscendingOrder,
        )
        self.setSortingEnabled(True)
        self._restoring = False
        self._sync_owner_resolution()
        header.sectionResized.connect(self._resized)
        header.sectionMoved.connect(self._changed)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._header_menu)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_requested)

    def _resized(self, logical: int, old_size: int, new_size: int) -> None:
        if new_size > 0:
            self._widths[logical] = new_size
        self._changed()

    def _changed(self, *args: object) -> None:
        if self._restoring:
            return
        header = self.horizontalHeader()
        present = set(self.tree_model.columns)
        columns = [
            ColumnSetting(
                column, not self.isColumnHidden(i), self._widths[i], header.visualIndex(i)
            )
            for i, column in enumerate(self.tree_model.columns)
        ]
        # A model displaying a subset must not discard preferences for other columns.
        for value in self._settings.columns:
            if value.id not in present:
                columns.append(ColumnSetting(value.id, value.visible, value.width, len(columns)))
        self._settings.columns = columns
        self._dirty = True
        self._save_timer.start()
        self.preferencesChanged.emit()

    def setColumnHidden(self, column: int, hide: bool) -> None:
        """Remember a hidden column's width and schedule one debounced settings write."""
        if not self.isColumnHidden(column) and hide:
            self._widths[column] = self.columnWidth(column)
        super().setColumnHidden(column, hide)
        self._changed()
        if not self._restoring:
            self._sync_owner_resolution()

    def _sync_owner_resolution(self) -> None:
        visible = any(
            column == ColumnId.OWNER and not self.isColumnHidden(i)
            for i, column in enumerate(self.tree_model.columns)
        )
        options = self.tree_model.view.options
        resolve = self._base_resolve_owner or visible
        if options.resolve_owner != resolve:
            self.tree_model.set_options(replace(options, resolve_owner=resolve))

    def save_preferences(self) -> None:
        """Flush a pending application-settings save, including when the table closes."""
        if self._dirty:
            self._save_timer.stop()
            if self._paths is not None:
                save_settings(self._settings, self._paths)
            self._dirty = False

    def column_menu(self) -> QMenu:
        """Build localized column visibility actions for the header context menu."""
        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        for logical, column in enumerate(self.tree_model.columns):
            action = menu.addAction(
                str(self.tree_model.headerData(logical, Qt.Orientation.Horizontal))
            )
            action.setObjectName(f"column.{column.value}")
            action.setCheckable(True)
            action.setChecked(not self.isColumnHidden(logical))
            action.toggled.connect(
                lambda visible, logical=logical: self.setColumnHidden(logical, not visible)
            )
        return menu

    def _header_menu(self, position: QPoint) -> None:
        self.column_menu().popup(self.horizontalHeader().mapToGlobal(position))

    def _context_requested(self, position: QPoint) -> None:
        index = self.indexAt(position)
        if index.isValid():
            self.contextMenuRequested.emit(
                self.tree_model.node_at(index.row()), self.viewport().mapToGlobal(position)
            )

    def _move_right(self, row: int, column: int, value: api.Row) -> None:
        if value[2] and not value[3]:
            self.tree_model.toggle(row)
        elif value[2] and row + 1 < self.tree_model.rowCount():
            self.setCurrentIndex(self.tree_model.index(row + 1, column))

    def _move_left(self, row: int, column: int, value: api.Row) -> None:
        if value[2] and value[3]:
            self.tree_model.toggle(row)
        else:
            parent = self.tree_model.view.tree.parent(value[0])
            parent_row = self.tree_model.row_of(parent) if parent is not None else None
            if parent_row is not None:
                self.setCurrentIndex(self.tree_model.index(parent_row, column))

    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint only the viewport, avoiding per-cell native/Python index-count callbacks.

        Qt still owns layout, scrolling, selection, navigation, headers and accessibility.
        Direct delegate calls reuse one style option and the same bounded native row pages.
        """
        painter = QPainter(self.viewport())
        try:
            painter.setClipRegion(event.region())
            painter.fillRect(event.rect(), self.palette().brush(QPalette.ColorRole.Base))
            first = self.rowAt(event.rect().top())
            if first < 0:
                return
            last = self.rowAt(event.rect().bottom())
            if last < 0:
                last = self.tree_model.rowCount() - 1
            header = self.horizontalHeader()
            columns = []
            for visual in range(header.count()):
                logical = header.logicalIndex(visual)
                if self.isColumnHidden(logical):
                    continue
                x, width = header.sectionViewportPosition(logical), header.sectionSize(logical)
                if x + width <= event.rect().left() or x > event.rect().right():
                    continue
                delegate = self.itemDelegateForColumn(logical) or self.itemDelegate()
                columns.append((logical, x, width, delegate))
            option = _PaintOption()
            self.initViewItemOption(option)
            option.widget = self
            font = QFont(option.font)
            option._dafree_frame_font = font
            option._dafree_row_background = True
            painter.setFont(font)
            palette = option.palette
            alternate_brush = palette.brush(QPalette.ColorRole.AlternateBase)
            selection_brush = palette.brush(QPalette.ColorRole.Highlight)
            left = min((x for logical, x, width, delegate in columns), default=0)
            right = max((x + width for logical, x, width, delegate in columns), default=0)
            base_state = option.state.value & ~(_SELECTED | _FOCUSED | _HOVERED)
            base_features = option.features.value & ~_ALTERNATE
            current = self.currentIndex()
            focused = self.hasFocus() or self.viewport().hasFocus()
            for row in range(first, last + 1):
                selected = self._tree_selection.isRowSelected(row)
                state = base_state | (_SELECTED if selected else 0)
                option.features = QStyleOptionViewItem.ViewItemFeature(
                    base_features | (_ALTERNATE if self.alternatingRowColors() and row % 2 else 0)
                )
                y, height = self.rowViewportPosition(row), self.rowHeight(row)
                if selected or (self.alternatingRowColors() and row % 2):
                    painter.fillRect(
                        QRect(left, y, right - left, height),
                        selection_brush if selected else alternate_brush,
                    )
                for logical, x, width, delegate in columns:
                    option.state = QStyle.StateFlag(
                        state
                        | (
                            _FOCUSED
                            if focused and current.row() == row and current.column() == logical
                            else 0
                        )
                    )
                    option.rect = QRect(x, y, width, height)
                    index = self.tree_model.createIndex(row, logical)
                    option.index = index
                    delegate.paint(painter, option, index)
        finally:
            painter.end()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Add tree commands while Qt retains ordinary row/page/home/end navigation."""
        current = self.currentIndex()
        if not current.isValid() or event.modifiers() & (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.MetaModifier
        ):
            super().keyPressEvent(event)
            return
        row = current.row()
        value = self.tree_model.data(current, TreeTableModel.ROW_ROLE)
        match event.key():
            case Qt.Key.Key_Home:
                self.setCurrentIndex(self.tree_model.index(0, current.column()))
            case Qt.Key.Key_End:
                self.setCurrentIndex(
                    self.tree_model.index(self.tree_model.rowCount() - 1, current.column())
                )
            case Qt.Key.Key_Right:
                self._move_right(row, current.column(), value)
            case Qt.Key.Key_Left:
                self._move_left(row, current.column(), value)
            case Qt.Key.Key_Asterisk:
                self.tree_model.expand_all_children(row)
            case Qt.Key.Key_Return | Qt.Key.Key_Enter:
                self.propertiesRequested.emit(value[0])
            case Qt.Key.Key_Menu:
                self.contextMenuRequested.emit(
                    value[0], self.viewport().mapToGlobal(self.visualRect(current).center())
                )
            case _:
                super().keyPressEvent(event)
                return
        event.accept()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Persist the final widths/order/visibility before the widget closes."""
        self.save_preferences()
        super().closeEvent(event)
