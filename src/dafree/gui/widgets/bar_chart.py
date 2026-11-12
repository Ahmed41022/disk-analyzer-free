"""Horizontal QPainter bars using the same values and keyboard actions as the pie."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from dafree.gui import _display_text
from dafree.gui.widgets.pie_chart import _ChartWidget
from dafree.i18n import _
from dafree.settings import Settings


class BarChart(_ChartWidget):
    """Draw bounded proportional bars with localized full-value legend text."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(settings, parent)
        self._title = _("Bar chart")
        self.setAccessibleName(self._title)

    def _row(self, index: int) -> QRectF:
        return QRectF(
            8, 12 + index * self._row_height(), max(1, self.width() - 16), self._row_height()
        )

    def slice_rect(self, index: int) -> QRectF:
        """Return the visible bar's logical rectangle."""
        if not 0 <= index < len(self.slices):
            raise IndexError(index)
        row = self._row(index)
        maximum = max(item.value for item in self.slices)
        return QRectF(
            row.left(),
            row.top() + self.fontMetrics().height() + 2,
            row.width() * self.slices[index].value / maximum,
            max(2, self._row_height() - self.fontMetrics().height() - 4),
        )

    def _hit(self, point: QPointF) -> int | None:
        return next(
            (index for index in range(len(self.slices)) if self._row(index).contains(point)), None
        )

    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint labels above bars so text remains legible on both theme palettes."""
        painter = QPainter(self)
        if not self._background(painter):
            return
        for index, label in enumerate(self.slice_labels()):
            row = self._row(index)
            painter.fillRect(self.slice_rect(index), self._color(index))
            painter.setPen(self.palette().text().color())
            text = self.fontMetrics().elidedText(
                _display_text(label), Qt.TextElideMode.ElideMiddle, int(row.width())
            )
            painter.drawText(
                row.adjusted(0, 0, 0, self.fontMetrics().height() - self._row_height()),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                text,
            )
            if index == self.selected_index:
                painter.setPen(QPen(self.palette().highlight().color(), 2))
                painter.drawRect(row.adjusted(1, 1, -1, -1))
