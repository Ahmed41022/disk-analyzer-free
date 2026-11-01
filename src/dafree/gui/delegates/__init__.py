"""Tree-table rendering without per-node Qt objects."""

from collections import OrderedDict
from typing import cast

from PySide6.QtCore import QModelIndex, QObject, QPersistentModelIndex, QPointF, QRect, Qt
from PySide6.QtGui import QFont, QPainter, QPalette, QStaticText, QTextOption, QTransform
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionFocusRect,
    QStyleOptionViewItem,
)

from dafree.gui.models.tree_model import TreeTableModel

_LEADING = Qt.AlignmentFlag.AlignLeading | Qt.AlignmentFlag.AlignVCenter
_SINGLE_LINE = int(Qt.TextFlag.TextSingleLine)
_MAX_LAYOUTS = 256
_SELECTED = QStyle.StateFlag.State_Selected.value
_ENABLED = QStyle.StateFlag.State_Enabled.value
_FOCUS = QStyle.StateFlag.State_HasFocus.value
_ALTERNATE = QStyleOptionViewItem.ViewItemFeature.Alternate.value
_RIGHT = int(Qt.AlignmentFlag.AlignRight)
_ABSOLUTE = int(Qt.AlignmentFlag.AlignAbsolute)


def display_text(index: QModelIndex | QPersistentModelIndex) -> str:
    """Format a cached row without a QVariant/Python round trip in each paint."""
    model = index.model()
    if isinstance(model, TreeTableModel):
        value = model.row_data(index.row())
        return model.display_value(value, model.columns[index.column()])
    return str(index.data(Qt.ItemDataRole.DisplayRole) or "")


def display_option(
    option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
) -> None:
    """Use the table's display-only role contract without probing unsupported roles.

    Font, palette, direction, selection and focus are already supplied by the view.
    TreeTableModel deliberately has no per-item fonts, brushes, checks or decorations.
    """
    option.text = display_text(index)
    option.features |= QStyleOptionViewItem.ViewItemFeature.HasDisplay


def paint_background(painter: QPainter, option: QStyleOptionViewItem, state: int) -> None:
    """Fill the table palette's selected, alternate, or ordinary background."""
    if getattr(option, "_dafree_row_background", False):
        return
    if state & _SELECTED:
        role = QPalette.ColorRole.Highlight
    elif option.features.value & _ALTERNATE:
        role = QPalette.ColorRole.AlternateBase
    else:
        role = QPalette.ColorRole.Base
    painter.fillRect(option.rect, option.palette.brush(role))


def paint_text(
    painter: QPainter,
    option: QStyleOptionViewItem,
    rect: QRect,
    text: str,
    *,
    state: int,
) -> None:
    """Draw one clipped line with Qt's active/disabled selection text colours."""
    set_text_pen(painter, option, state)
    if not hasattr(option, "_dafree_frame_font"):
        painter.setFont(option.font)
    painter.drawText(
        rect, int(QStyle.visualAlignment(option.direction, _LEADING)) | _SINGLE_LINE, text
    )


def set_text_pen(painter: QPainter, option: QStyleOptionViewItem, state: int) -> None:
    """Use the correct palette group for selected and disabled text."""
    role = QPalette.ColorRole.HighlightedText if state & _SELECTED else QPalette.ColorRole.Text
    group = (
        QPalette.ColorGroup.Disabled if not state & _ENABLED else option.palette.currentColorGroup()
    )
    painter.setPen(option.palette.color(group, role))


class TextCache:
    """Reuse repeated totals' glyph layouts, bounded to 256 entries per delegate."""

    def __init__(self) -> None:
        self._font: QFont | None = None
        self._layouts: OrderedDict[
            tuple[str, int, Qt.LayoutDirection], tuple[QStaticText, float, float]
        ] = OrderedDict()

    def draw(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        rect: QRect,
        text: str,
        alignment: Qt.AlignmentFlag,
    ) -> None:
        """Prepare only new text/font/width/direction combinations and retain clipping."""
        state = option.state.value
        font = cast(QFont | None, getattr(option, "_dafree_frame_font", None))
        if font is None:
            font = option.font
        if self._font is None or self._font != font:
            # The option's wrapper expires after this callback; own just the active font.
            self._font = QFont(font)
            self._layouts.clear()
        key = (text, rect.width(), option.direction)
        cached = self._layouts.get(key)
        if cached is None:
            fitted = option.fontMetrics.elidedText(
                text, Qt.TextElideMode.ElideRight, max(0, rect.width())
            )
            layout = QStaticText(fitted)
            layout.setTextFormat(Qt.TextFormat.PlainText)
            text_option = QTextOption()
            text_option.setTextDirection(option.direction)
            text_option.setWrapMode(QTextOption.WrapMode.NoWrap)
            layout.setTextOption(text_option)
            layout.prepare(QTransform(), self._font)
            size = layout.size()
            cached = (layout, size.width(), size.height())
            self._layouts[key] = cached
            if len(self._layouts) > _MAX_LAYOUTS:
                self._layouts.popitem(last=False)
        self._layouts.move_to_end(key)
        layout, width, height = cached
        set_text_pen(painter, option, state)
        if not hasattr(option, "_dafree_frame_font"):
            painter.setFont(self._font)
        flags = int(alignment)
        right = bool(flags & _RIGHT)
        if option.direction == Qt.LayoutDirection.RightToLeft and not flags & _ABSOLUTE:
            right = not right
        x = rect.right() + 1 - width if right else rect.left()
        painter.save()
        painter.setClipRect(rect, Qt.ClipOperation.IntersectClip)
        painter.drawStaticText(QPointF(x, rect.top() + (rect.height() - height) / 2), layout)
        painter.restore()


def paint_focus(painter: QPainter, option: QStyleOptionViewItem, state: int) -> None:
    """Keep the native keyboard-focus indicator while avoiding per-cell style layout."""
    if state & _FOCUS:
        focus = QStyleOptionFocusRect()
        focus.rect = option.rect.adjusted(1, 1, -1, -1)
        focus.palette, focus.state = option.palette, option.state
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawPrimitive(
            QStyle.PrimitiveElement.PE_FrameFocusRect, focus, painter, option.widget
        )


class DisplayDelegate(QStyledItemDelegate):
    """Keep each visible-cell paint in one Python callback, using the model's cached page."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._texts = TextCache()

    def initStyleOption(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        """Populate display text from the table's intentionally restricted role contract."""
        display_option(option, index)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        """Paint the supplied palette and font directly, retaining native keyboard focus."""
        text = display_text(index)
        state = option.state.value
        rect = option.rect.adjusted(4, 0, -4, 0)
        painter.save()
        paint_background(painter, option, state)
        self._texts.draw(painter, option, rect, text, self.alignment)
        paint_focus(painter, option, state)
        painter.restore()

    alignment = _LEADING
