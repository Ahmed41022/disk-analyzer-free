"""Debounced name filtering with localized, character-accurate error underlines."""

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QTextLayout,
    QTextOption,
)
from PySide6.QtWidgets import QLineEdit, QStyle, QStyleOptionFrame, QWidget

from dafree import query
from dafree.i18n import _


def _utf16_offset(text: str, position: int) -> int:
    return len(text[:position].encode("utf-16-le", errors="surrogatepass")) // 2


def _cursor_x(layout: QTextLayout, position: int) -> float:
    result = layout.lineAt(0).cursorToX(position)
    if isinstance(result, tuple):
        return float(result[0])
    if not isinstance(result, (int, float)):
        raise TypeError("Unexpected Qt cursor coordinate")
    return float(result)


class QueryEdit(QLineEdit):
    """Emit native filter specifications only after 250 ms of valid, unchanged input."""

    filterChanged = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._error: query.QueryError | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._parse)
        self.textChanged.connect(self._changed)
        self.setPlaceholderText(_("Search"))
        self.setAccessibleName(_("Search results"))
        self.setToolTip(_("Search file and folder names."))
        self.cursorPositionChanged.connect(lambda old, new: self.update())

    @property
    def error_span(self) -> tuple[int, int] | None:
        """Return the parser's original Python character range, if input is invalid."""
        return self._error.span if self._error else None

    def _changed(self, text: str) -> None:
        self._error = None
        self.setToolTip(_("Search file and folder names."))
        self.update()
        self._timer.start()

    def _parse(self) -> None:
        try:
            parsed = query.parse(self.text())
        except query.QueryError as error:
            self._error = error
            self.setToolTip(_(error.message_id).format_map(error.arguments))
            self.update()
        else:
            self._error = None
            self.setToolTip(_("Search file and folder names."))
            self.filterChanged.emit(parsed.to_filter_spec() if self.text().strip() else None)
            self.update()

    def error_underline_rect(self) -> QRectF:
        """Locate the error under the actual scrolled/bidirectional line-edit text."""
        if self._error is None:
            return QRectF()
        text = self.text()
        start, end = (max(0, min(position, len(text))) for position in self._error.span)
        layout = QTextLayout(text, self.font())
        option = QTextOption()
        option.setTextDirection(Qt.LayoutDirection.LayoutDirectionAuto)
        layout.setTextOption(option)
        layout.beginLayout()
        line = layout.createLine()
        if not line.isValid():
            layout.endLayout()
            return QRectF()
        line.setLineWidth(1_000_000)
        layout.endLayout()
        origin = self.cursorRect().x() - _cursor_x(layout, self.cursorPosition())
        left = origin + _cursor_x(layout, _utf16_offset(text, start))
        right = origin + _cursor_x(layout, _utf16_offset(text, end))
        rectangle = QRectF(
            min(left, right), self.cursorRect().bottom() - 2, max(4, abs(right - left)), 3
        )
        frame = QStyleOptionFrame()
        self.initStyleOption(frame)
        contents = self.style().subElementRect(QStyle.SubElement.SE_LineEditContents, frame, self)
        return rectangle.intersected(QRectF(contents))

    def paintEvent(self, event: QPaintEvent) -> None:
        """Retain native editing/selection and overlay a red wave only beneath the error."""
        super().paintEvent(event)
        rectangle = self.error_underline_rect()
        if rectangle.isEmpty():
            return
        path = QPainterPath()
        x, y = rectangle.left(), rectangle.center().y()
        path.moveTo(x, y)
        step = 0
        while x < rectangle.right():
            x = min(x + 2, rectangle.right())
            path.lineTo(x, y + (1 if step % 2 == 0 else -1))
            step += 1
        painter = QPainter(self)
        painter.setClipRect(rectangle)
        painter.setPen(QPen(QColor("#d32f2f"), 1.2))
        painter.drawPath(path)
        painter.end()
