"""Depth-coloured, direction-aware percentage bars behind localized numbers."""

from PySide6.QtCore import QModelIndex, QObject, QPersistentModelIndex, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from dafree.gui.delegates import (
    TextCache,
    display_text,
    paint_background,
    paint_context,
    paint_focus,
    paint_state,
)
from dafree.gui.models.tree_model import TreeTableModel

_ALIGN_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


class PercentDelegate(QStyledItemDelegate):
    """Paint one inexpensive bar per visible percentage cell."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._texts = TextCache()

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        """Keep selection contrast, depth colour, and RTL bar origin consistent."""
        frame = paint_context(option)
        model = frame.model if frame is not None else index.model()
        if not isinstance(model, TreeTableModel):
            return
        value = frame.row if frame is not None else model.row_data(index.row())
        item = option
        rect = frame.rect if frame is not None else option.rect
        direction = frame.direction if frame is not None else option.direction
        state = paint_state(option)
        text = display_text(index, option)
        painter.save()
        painter.setClipRect(rect)
        paint_background(painter, item, state)
        bar = rect.adjusted(4, 5, -4, -5)
        bar.setWidth(round(bar.width() * min(1.0, max(0.0, value[7]))))
        bar = QStyle.visualRect(direction, rect, bar)
        color = QColor.fromHsv((210 + value[1] * 29) % 360, 150, 190, 75)
        painter.fillRect(bar, color)
        self._texts.draw(
            painter,
            item,
            rect.adjusted(4, 0, -4, 0),
            text,
            _ALIGN_RIGHT,
        )
        paint_focus(painter, item, state)
        painter.restore()
