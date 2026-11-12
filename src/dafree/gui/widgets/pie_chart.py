"""Accessible QPainter charts over bounded, immutable analysis slices."""

from __future__ import annotations

import math
from collections.abc import Sequence

from PySide6.QtCore import QEvent, QLocale, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPaintEvent, QPen, QResizeEvent
from PySide6.QtWidgets import QWidget

from dafree.api.analysis import ChartSlice
from dafree.gui import _display_text, _format_size, _number_translation
from dafree.gui.accessibility import AccessibleRect, TreemapAccessibility
from dafree.i18n import _
from dafree.settings import Settings

_COLORS = ("#0072b2", "#e69f00", "#009e73", "#cc79a7", "#56b4e9", "#d55e00", "#f0e442", "#707070")
_MAX_SLICES = 16
_FULL_CIRCLE = 360.0


class _ChartWidget(QWidget):
    """Share bounded legend formatting, keyboard selection and virtual item metadata."""

    sliceActivated = Signal(object)

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self.slices: tuple[ChartSlice, ...] = ()
        self.selected_index: int | None = None
        self._count_values = False
        self._title = ""
        self.accessibility = TreemapAccessibility(self)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(180, 120)

    def set_data(self, slices: Sequence[ChartSlice], *, count_values: bool = False) -> None:
        """Show at most fifteen positive entries plus Other, without keeping a native tree."""
        if any(not 0 <= item.value <= (1 << 64) - 1 for item in slices):
            raise ValueError("chart values must fit unsigned 64-bit integers")
        positive = tuple(item for item in slices if item.value > 0)
        if len(positive) > _MAX_SLICES:
            raise ValueError("chart widgets accept at most 16 positive slices")
        self.slices = positive
        self._count_values = count_values
        self.selected_index = None
        self.setToolTip("")
        self.setAccessibleName(self._title)
        self.setAccessibleDescription("")
        self.setMinimumHeight(max(120, len(positive) * self._row_height() + 24))
        self._update_accessibility()
        self.update()

    def slice_labels(self) -> tuple[str, ...]:
        """Return complete localized legend text, including value and percentage."""
        total = sum(item.value for item in self.slices)
        locale = QLocale()
        return tuple(
            _("{label}: {value} ({percent})").format(
                label=_display_text(item.label),
                value=(
                    locale.toString(item.value)
                    if item.value <= (1 << 63) - 1
                    else str(item.value).translate(_number_translation(locale.name(), "."))
                )
                if self._count_values
                else _format_size(item.value, self._settings.units, self._settings.unit_style),
                percent=locale.toString(100 * item.value / total, "f", 1) + locale.percent(),
            )
            for item in self.slices
        )

    def refresh_settings(self) -> None:
        """Refresh size labels and accessible text after committed unit changes."""
        self._update_accessibility()
        if self.selected_index is not None:
            self._select(self.selected_index)
        self.update()

    def _row_height(self) -> int:
        return max(24, self.fontMetrics().height() + 8)

    def _color(self, index: int) -> QColor:
        return QColor("#707070" if self.slices[index].is_other else _COLORS[index % len(_COLORS)])

    def _select(self, index: int) -> None:
        self.selected_index = index
        label = self.slice_labels()[index]
        self.setAccessibleName(_("{chart}: {slice}").format(chart=self._title, slice=label))
        self.setAccessibleDescription(label)
        self.accessibility.set_focus(index)
        self.update()

    def _activate(self, index: int) -> None:
        self._select(index)
        item = self.slices[index]
        if item.node is not None and not item.is_other:
            self.sliceActivated.emit(item.node)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Move between slices with arrows/Home/End and activate with Enter/Space."""
        if not self.slices:
            super().keyPressEvent(event)
            return
        key = event.key()
        if key in (Qt.Key.Key_Home, Qt.Key.Key_End):
            self._select(0 if key == Qt.Key.Key_Home else len(self.slices) - 1)
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_Right, Qt.Key.Key_Down):
            direction = -1 if key in (Qt.Key.Key_Left, Qt.Key.Key_Up) else 1
            index = (
                (self.selected_index + direction) % len(self.slices)
                if self.selected_index is not None
                else 0
            )
            self._select(index)
        elif (
            key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space)
            and self.selected_index is not None
        ):
            self._activate(self.selected_index)
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def slice_rect(self, index: int) -> QRectF:
        """Return the logical bounds of the slice's interactive graphic."""
        raise NotImplementedError

    def slice_point(self, index: int) -> QPointF:
        """Return a logical point inside the visible slice for pointer activation."""
        return self.slice_rect(index).center()

    def _hit(self, point: QPointF) -> int | None:
        for index in range(len(self.slices)):
            if self.slice_rect(index).contains(point):
                return index
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Activate a real node by identity rather than by displayed label."""
        if (
            event.button() == Qt.MouseButton.LeftButton
            and (index := self._hit(event.position())) is not None
        ):
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self._activate(index)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Show complete, unelided legend text at the pointer."""
        index = self._hit(event.position())
        self.setToolTip("" if index is None else self.slice_labels()[index])
        super().mouseMoveEvent(event)

    def _update_accessibility(self) -> None:
        self.accessibility.update(
            tuple(
                AccessibleRect(index, label, self.slice_rect(index))
                for index, label in enumerate(self.slice_labels())
            )
        )
        if self.selected_index is not None:
            self.accessibility.set_focus(self.selected_index)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Update logical accessible bounds without recomputing scan data."""
        super().resizeEvent(event)
        self._update_accessibility()

    def changeEvent(self, event: QEvent) -> None:
        """Refresh text geometry when Qt changes the widget's font."""
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange and hasattr(self, "accessibility"):
            self.setMinimumHeight(max(120, len(self.slices) * self._row_height() + 24))
            self._update_accessibility()

    def _background(self, painter: QPainter) -> bool:
        painter.setLayoutDirection(self.layoutDirection())
        painter.fillRect(self.rect(), self.palette().base())
        painter.setPen(self.palette().text().color())
        if not self.slices:
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                _("No data for this selection."),
            )
            return False
        return True


class PieChart(_ChartWidget):
    """Draw proportional sectors and a clickable legend with an Okabe-Ito-based palette."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(settings, parent)
        self._title = _("Pie chart")
        self.setAccessibleName(self._title)

    def slice_angles(self) -> tuple[float, ...]:
        """Partition a complete circle using monotonic cumulative boundaries."""
        total = sum(item.value for item in self.slices)
        if not total:
            return ()
        angles = []
        prefix, previous = 0, 0.0
        for item in self.slices:
            prefix += item.value
            boundary = 360 * prefix / total
            angles.append(boundary - previous)
            previous = boundary
        return tuple(angles)

    def _plot(self) -> QRectF:
        size = max(1.0, min(self.width() * 0.40, self.height() - 24.0))
        return QRectF(8, 12, size, size)

    def _legend_rect(self, index: int) -> QRectF:
        left = self._plot().right() + 12
        return QRectF(
            left,
            12 + index * self._row_height(),
            max(0, self.width() - left - 8),
            self._row_height(),
        )

    def slice_rect(self, index: int) -> QRectF:
        """Return the logical pie bounds for an accessible sector."""
        if not 0 <= index < len(self.slices):
            raise IndexError(index)
        return self._plot()

    def slice_point(self, index: int) -> QPointF:
        """Return the midpoint of the sector, halfway between its center and rim."""
        angles = self.slice_angles()
        if not 0 <= index < len(angles):
            raise IndexError(index)
        if angles[index] == 0:
            return self._legend_rect(index).center()
        angle = math.radians(sum(angles[:index]) + angles[index] / 2)
        plot = self._plot()
        radius = plot.width() / 4
        return plot.center() + QPointF(math.cos(angle) * radius, -math.sin(angle) * radius)

    def _hit(self, point: QPointF) -> int | None:
        for index in range(len(self.slices)):
            if self._legend_rect(index).contains(point):
                return index
        plot = self._plot()
        delta = point - plot.center()
        if delta.x() ** 2 + delta.y() ** 2 > (plot.width() / 2) ** 2:
            return None
        angle = math.degrees(math.atan2(-delta.y(), delta.x())) % _FULL_CIRCLE
        end = 0.0
        for index, extent in enumerate(self.slice_angles()):
            end += extent
            if angle < end:
                return index
        return None

    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint sectors and full-value legends without creating a scene or child widgets."""
        painter = QPainter(self)
        if not self._background(painter):
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        start = 0.0
        for index, (angle, label) in enumerate(
            zip(self.slice_angles(), self.slice_labels(), strict=True)
        ):
            painter.setBrush(self._color(index))
            painter.setPen(
                QPen(
                    self.palette().highlight().color()
                    if index == self.selected_index
                    else self.palette().base().color(),
                    3 if index == self.selected_index else 1,
                )
            )
            painter.drawPie(
                self._plot(), round(start * 16), round((start + angle) * 16) - round(start * 16)
            )
            start += angle
            rect = self._legend_rect(index)
            painter.fillRect(QRectF(rect.left(), rect.top() + 6, 12, 12), self._color(index))
            text_rect = rect.adjusted(18, 0, 0, 0)
            painter.setPen(self.palette().text().color())
            text = self.fontMetrics().elidedText(
                label, Qt.TextElideMode.ElideMiddle, max(0, int(text_rect.width()))
            )
            painter.drawText(
                text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text
            )
            if index == self.selected_index and self.hasFocus():
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(self.palette().highlight().color(), 2))
                painter.drawRect(rect.adjusted(1, 1, -1, -1))
