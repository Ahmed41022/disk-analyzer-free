"""Background-rendered native treemap with device-pixel-aware navigation."""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QLocale, QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QContextMenuEvent,
    QImage,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPalette,
    QPen,
    QResizeEvent,
)
from PySide6.QtWidgets import QWidget

from dafree import api
from dafree.gui import _display_text, _format_size
from dafree.gui.accessibility import AccessibleRect, TreemapAccessibility
from dafree.gui.controllers.task_runner import TaskRunner
from dafree.i18n import _
from dafree.settings import Settings

_ACCESSIBLE_LIMIT = 50
_RESIZE_DELAY_MS = 150
_COLORS = (
    0x0072B2FF,
    0xE69F00FF,
    0x009E73FF,
    0xCC79A7FF,
    0x56B4E9FF,
    0xD55E00FF,
    0xF0E442FF,
    0x999999FF,
)


def _node_name(tree: api.Tree, node: int) -> str:
    return _("All scan targets") if node == 0 else _display_text(tree.name(node))


@dataclass(frozen=True)
class _RenderJob:
    owner: object
    generation: int


@dataclass(frozen=True)
class _Rendered:
    layout: api.TreemapLayout
    buffer: bytes
    width: int
    height: int
    ratio: float
    accessible: tuple[AccessibleRect, ...]


@dataclass(frozen=True)
class _RenderRequest:
    tree: api.Tree
    root: int
    width: int
    height: int
    ratio: float
    options: api.TreemapOptions
    palette: api.Palette
    cushion: bool
    settings: Settings


def _render(request: _RenderRequest) -> _Rendered:
    layout = api.treemap_layout(
        request.tree, request.root, request.width, request.height, request.options
    )
    buffer = api.treemap_render(layout, request.palette, request.cushion)
    rects = layout.rects
    # Vectorized native array operations; Python reads metadata for at most 50 nodes.
    real = rects[
        (rects["flags"] & int(api.TmFlags.OTHER) == 0) & (rects["w"] > 0) & (rects["h"] > 0)
    ]
    largest = (real["w"] * real["h"]).argsort(kind="stable")[::-1][:_ACCESSIBLE_LIMIT]
    entries = []
    for rect in real[largest]:
        node = int(rect["node"])
        entries.append(
            AccessibleRect(
                node,
                _("{name}, {size}").format(
                    name=_node_name(request.tree, node),
                    size=_format_size(
                        request.tree.node(node).size,
                        request.settings.units,
                        request.settings.unit_style,
                    ),
                ),
                QRectF(*(float(rect[field]) / request.ratio for field in ("x", "y", "w", "h"))),
            )
        )
    return _Rendered(layout, buffer, request.width, request.height, request.ratio, tuple(entries))


class TreemapWidget(QWidget):
    """Render immutable scan snapshots off-thread and select native node identities."""

    ready = Signal()
    nodeSelected = Signal(object)
    zoomChanged = Signal(object)
    contextMenuRequested = Signal(object, object)

    def __init__(
        self, settings: Settings, runner: TaskRunner, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._settings, self._runner = settings, runner
        self._owner, self._generation = object(), 0
        self._building = False
        self._pending = False
        self.tree: api.Tree | None = None
        self.zoom_root: int | None = None
        self.selected_node: int | None = None
        self.layout_result: api.TreemapLayout | None = None
        self.render_buffer = b""
        self.image = QImage()
        self._ratio = 1.0
        self._error = ""
        self._selected_rect = QRectF()
        self.accessibility = TreemapAccessibility(self)
        self.setAccessibleName(_("Treemap"))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(1, 1)
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(_RESIZE_DELAY_MS)
        self._resize_timer.timeout.connect(self._submit_pending)
        runner.finished.connect(self._finished)
        runner.failed.connect(self._failed)

    def clear(self) -> None:
        """Invalidate pending work and every node from the previous scan namespace."""
        self._generation += 1
        self._pending = False
        self._resize_timer.stop()
        self.tree = None
        self.zoom_root = self.selected_node = None
        self.layout_result = None
        self.image = QImage()
        self.render_buffer = b""
        self._error = ""
        self._selected_rect = QRectF()
        self.setToolTip("")
        self.accessibility.update(())
        self.update()

    def set_tree(self, tree: api.Tree) -> None:
        """Replace a snapshot, retaining zoom and selection only for the same tree."""
        if tree is self.tree:
            return
        self.clear()
        self.tree = tree
        roots = tree.roots()
        self.zoom_root = roots[0] if len(roots) == 1 else 0
        self.zoomChanged.emit(self.zoom_root)
        self._schedule()

    def zoom_to(self, node: int) -> None:
        """Zoom into a real directory; breadcrumb callers may also choose the root."""
        if self.tree is None or not self.tree.node(node).flags & api.NodeFlags.DIR:
            return
        if node != self.zoom_root:
            self.zoom_root = node
            self.layout_result = None
            self.image = QImage()
            self.render_buffer = b""
            self.accessibility.update(())
            self._selected_rect = QRectF()
            self.setToolTip("")
            self.zoomChanged.emit(node)
            self._schedule()

    def select_node(self, node: int) -> None:
        """Highlight a tree selection without changing the zoom or emitting a loop."""
        if self.tree is None:
            return
        self.tree.node(node)  # Validate against this snapshot's namespace.
        self.selected_node = node
        self._update_selection()

    def refresh_settings(self) -> None:
        """Apply committed dimensions, units, flat-color preference and palette."""
        self._schedule()

    def _schedule(self, *, resize: bool = False) -> None:
        self._generation += 1
        self._pending = self.tree is not None
        if resize:
            self._resize_timer.start()
        else:
            self._resize_timer.stop()
            self._submit_pending()
        self.update()

    def _submit_pending(self) -> None:
        if self._building or not self._pending or self.tree is None or self.zoom_root is None:
            return
        if self.width() <= 0 or self.height() <= 0:
            return
        self._pending = False
        self._building = True
        job = _RenderJob(self._owner, self._generation)
        tree, root = self.tree, self.zoom_root
        ratio = self.devicePixelRatioF()
        width, height = math.ceil(self.width() * ratio), math.ceil(self.height() * ratio)
        options = api.TreemapOptions()
        for field in ("max_depth", "min_px", "padding", "header_px", "max_rects"):
            value = getattr(self._settings.treemap, field)
            setattr(
                options,
                field,
                value * ratio if field in ("min_px", "padding", "header_px") else value,
            )
        palette = api.Palette()
        palette.by_class = list(_COLORS * 2)
        palette.dir_by_depth = list(_COLORS)
        palette.background = (
            int(self.palette().color(QPalette.ColorRole.Base).name()[1:], 16) << 8 | 255
        )
        palette.border = (
            int(self.palette().color(QPalette.ColorRole.Window).name()[1:], 16) << 8 | 255
        )
        cushion = not self._settings.treemap.flat_colours
        # Snapshot the settings used by this job; later dialog changes cannot race it.
        settings = Settings(units=self._settings.units, unit_style=self._settings.unit_style)
        request = _RenderRequest(
            tree, root, width, height, ratio, options, palette, cushion, settings
        )
        self._runner.submit(
            lambda: _render(request),
            task_id=job,
        )

    def _finished(self, job: object, result: object) -> None:
        if not isinstance(job, _RenderJob) or job.owner is not self._owner:
            return
        self._building = False
        if job.generation == self._generation and isinstance(result, _Rendered):
            self.layout_result = result.layout
            self.render_buffer = result.buffer
            self.image = QImage(
                self.render_buffer, result.width, result.height, QImage.Format.Format_RGBA8888
            )
            self.image.setDevicePixelRatio(result.ratio)
            self._ratio = result.ratio
            self._error = ""
            self.accessibility.update(result.accessible)
            self._update_selection()
            self.ready.emit()
        if not self._resize_timer.isActive():
            self._submit_pending()

    def _failed(self, job: object, message: str) -> None:
        if not isinstance(job, _RenderJob) or job.owner is not self._owner:
            return
        self._building = False
        if job.generation == self._generation:
            self._error = _("Could not prepare treemap: {error}").format(
                error=_display_text(message)
            )
            self.update()
        if not self._resize_timer.isActive():
            self._submit_pending()

    def _update_selection(self) -> None:
        self._selected_rect = QRectF()
        if self.layout_result is not None and self.selected_node is not None:
            rects = self.layout_result.rects
            selected = rects[rects["node"] == self.selected_node]
            if len(selected):
                self._selected_rect = QRectF(
                    *(float(selected[0][field]) / self._ratio for field in ("x", "y", "w", "h"))
                )
        self.update()

    def tooltip_for(self, node: int) -> str:
        """Describe one node with localized size and share of the current zoom root."""
        if self.tree is None or self.zoom_root is None:
            return ""
        size, total = self.tree.node(node).size, self.tree.node(self.zoom_root).size
        locale = QLocale()
        percent = locale.toString(100 * size / total if total else 0.0, "f", 1) + locale.percent()
        return _("{name}\nSize: {size}\n{percent} of zoom root").format(
            name=_node_name(self.tree, node),
            size=_format_size(size, self._settings.units, self._settings.unit_style),
            percent=percent,
        )

    def _hit(self, event: QMouseEvent) -> int | None:
        if self.layout_result is None:
            return None
        return self.layout_result.hit_test(
            event.position().x() * self._ratio, event.position().y() * self._ratio
        )

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Resolve native device-pixel hit bounds for the hover tooltip."""
        node = self._hit(event)
        self.setToolTip("" if node is None else self.tooltip_for(node))
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Select by node ID, keeping path display separate from navigation."""
        if event.button() == Qt.MouseButton.LeftButton and (node := self._hit(event)) is not None:
            self.select_node(node)
            self.nodeSelected.emit(node)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Zoom directories only; ordinary files remain selectable rectangles."""
        if event.button() == Qt.MouseButton.LeftButton and (node := self._hit(event)) is not None:
            self.select_node(node)
            self.nodeSelected.emit(node)
            self.zoom_to(node)
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        """Reuse the application's shared context menu for pointer or keyboard actions."""
        node = self.selected_node if event.reason() == QContextMenuEvent.Reason.Keyboard else None
        if event.reason() != QContextMenuEvent.Reason.Keyboard and self.layout_result is not None:
            node = self.layout_result.hit_test(
                event.pos().x() * self._ratio, event.pos().y() * self._ratio
            )
        if node is not None:
            self.select_node(node)
            self.nodeSelected.emit(node)
            self.contextMenuRequested.emit(node, event.globalPos())
            event.accept()

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Coalesce repeated resizes into one background render after 150 ms."""
        super().resizeEvent(event)
        self._schedule(resize=True)

    def changeEvent(self, event: QEvent) -> None:
        """Repaint for theme and monitor scaling changes without blocking the UI."""
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "_resize_timer"):
            self._schedule(resize=True)

    def event(self, event: QEvent) -> bool:
        """Re-render when Qt changes the monitor's device-pixel ratio."""
        result = super().event(event)
        if event.type() == QEvent.Type.DevicePixelRatioChange and hasattr(self, "_resize_timer"):
            self._schedule(resize=True)
        return result

    def paintEvent(self, event: QPaintEvent) -> None:
        """Blit the retained RGBA buffer and a lightweight selection outline."""
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().base())
        if not self.image.isNull():
            painter.drawImage(QPoint(0, 0), self.image)
            if not self._selected_rect.isEmpty():
                painter.setPen(QPen(self.palette().highlightedText().color(), 2))
                painter.drawRect(self._selected_rect.adjusted(1, 1, -1, -1))
        else:
            painter.setPen(self.palette().text().color())
            message = self._error or (
                _("Preparing treemap…") if self.tree is not None else _("Choose a target to scan.")
            )
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, message
            )
