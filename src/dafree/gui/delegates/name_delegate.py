"""Indented names, original category icons, and native expansion affordances."""

from __future__ import annotations

from PySide6.QtCore import QAbstractItemModel, QEvent, QModelIndex, QPersistentModelIndex, QRect, Qt
from PySide6.QtGui import QColor, QIcon, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOption,
    QStyleOptionViewItem,
)

from dafree import api
from dafree.gui.delegates import (
    display_text,
    paint_background,
    paint_context,
    paint_focus,
    paint_text,
)
from dafree.gui.models.tree_model import TreeTableModel

_INDENT = 18
_ICON = 16
_DIRECTORY = int(api.NodeFlags.DIR)
_CATEGORY_COLORS = (
    "#619d52",
    "#8c67bd",
    "#bc648e",
    "#b68b43",
    "#5289bf",
    "#4a9b98",
    "#b8724c",
    "#7c80b4",
    "#737e8c",
    "#89919b",
)


class NameDelegate(QStyledItemDelegate):
    """Render only visible names; cache ten tiny code-drawn category icons."""

    def __init__(self, parent: TreeTableModel | None = None) -> None:
        super().__init__(parent)
        self._icons: dict[int, QIcon] = {}

    @staticmethod
    def chevron_element(expanded: bool, direction: Qt.LayoutDirection) -> QStyle.PrimitiveElement:
        """Mirror the closed chevron while retaining the downward open chevron."""
        if expanded:
            return QStyle.PrimitiveElement.PE_IndicatorArrowDown
        return (
            QStyle.PrimitiveElement.PE_IndicatorArrowLeft
            if direction == Qt.LayoutDirection.RightToLeft
            else QStyle.PrimitiveElement.PE_IndicatorArrowRight
        )

    @staticmethod
    def chevron_rect(option: QStyleOptionViewItem, depth: int) -> QRect:
        """Return the same mirrored hit rectangle used by painting."""
        logical = QRect(
            option.rect.left() + 3 + depth * _INDENT,
            option.rect.top(),
            _INDENT,
            option.rect.height(),
        )
        return QStyle.visualRect(option.direction, option.rect, logical)

    def _category_icon(self, category: int) -> QIcon:
        if category not in self._icons:
            pixmap = QPixmap(_ICON, _ICON)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            color = QColor(_CATEGORY_COLORS[category % len(_CATEGORY_COLORS)])
            painter.setPen(color.darker(120))
            painter.setBrush(color.lighter(180))
            painter.drawRoundedRect(3, 1, 10, 13, 1, 1)
            painter.fillRect(3, 8, 10, 4, color)
            painter.end()
            self._icons[category] = QIcon(pixmap)
        return self._icons[category]

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        """Paint a mirrored chevron, type icon, and end-elided native display name."""
        frame = paint_context(option)
        model = frame.model if frame is not None else index.model()
        if not isinstance(model, TreeTableModel):
            return
        value = frame.row if frame is not None else model.row_data(index.row())
        item = option
        rect = frame.rect if frame is not None else option.rect
        direction = frame.direction if frame is not None else option.direction
        state = frame.state if frame is not None else option.state.value
        text = (
            model.display_value(value, frame.column) if frame is not None else display_text(index)
        )
        style = item.widget.style() if item.widget else QApplication.style()
        painter.save()
        painter.setClipRect(rect)
        paint_background(painter, item, state)
        if value[2]:
            arrow = QStyleOption()
            arrow.rect = self.chevron_rect(item, value[1])
            arrow.direction, arrow.palette, arrow.state = direction, item.palette, item.state
            style.drawPrimitive(
                self.chevron_element(value[3], direction), arrow, painter, item.widget
            )
        icon_x = rect.left() + 3 + (value[1] + 1) * _INDENT
        icon_rect = QRect(icon_x, rect.center().y() - _ICON // 2, _ICON, _ICON)
        icon_rect = QStyle.visualRect(direction, rect, icon_rect)
        icon = (
            style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
            if value[13] & _DIRECTORY
            else self._category_icon(value[14])
        )
        icon.paint(painter, icon_rect)
        logical = rect.adjusted(3 + (value[1] + 1) * _INDENT + _ICON + 5, 0, -4, 0)
        text_rect = QStyle.visualRect(direction, rect, logical)
        metrics = frame.metrics if frame is not None else item.fontMetrics
        text = metrics.elidedText(text, Qt.TextElideMode.ElideRight, max(0, text_rect.width()))
        paint_text(painter, item, text_rect, text, state=state)
        paint_focus(painter, item, state)
        painter.restore()

    def editorEvent(
        self,
        event: QEvent,
        model: QAbstractItemModel,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        """Toggle only a left-button release inside the painted chevron."""
        if (
            isinstance(event, QMouseEvent)
            and event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
            and isinstance(model, TreeTableModel)
        ):
            value = index.data(TreeTableModel.ROW_ROLE)
            if (
                value
                and value[2]
                and self.chevron_rect(option, value[1]).contains(event.position().toPoint())
            ):
                model.toggle(index.row())
                return True
        return super().editorEvent(event, model, option, index)
