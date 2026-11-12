"""Virtual accessibility children for canvas-style widgets."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import cast
from weakref import ref

from PySide6.QtCore import QObject, QPoint, QRect, QRectF
from PySide6.QtGui import QAccessible, QAccessibleEvent, QAccessibleInterface, QAccessibleObject
from PySide6.QtWidgets import QAccessibleWidget, QWidget

from dafree.i18n import _

_MAX_VIRTUAL_CHILDREN = 50


class _FactoryRegistration:
    installed = False

    @classmethod
    def ensure_installed(cls) -> None:
        if not cls.installed:
            QAccessible.installFactory(_accessible_factory)
            cls.installed = True


@dataclass(frozen=True, slots=True)
class AccessibleRect:
    """One visible item exposed as a virtual child in widget-local logical pixels."""

    node: int
    name: str
    rect: QRectF

    def __post_init__(self) -> None:
        if self.node < 0:
            raise ValueError("accessible node IDs must be non-negative")
        if not self.name:
            raise ValueError("accessible child names must not be empty")
        rectangle = QRectF(self.rect)
        geometry = (rectangle.x(), rectangle.y(), rectangle.width(), rectangle.height())
        if not all(isfinite(value) for value in geometry):
            raise ValueError("accessible rectangles must have finite geometry")
        object.__setattr__(self, "rect", rectangle)


class _AccessibleRectObject(QObject):
    """QObject anchor for a virtual child; it creates no QWidget or visual item."""

    def __init__(self, widget: QWidget, entry: AccessibleRect, owner: TreemapAccessibility) -> None:
        super().__init__(widget)
        self.entry = entry
        self.owner_ref = ref(owner)
        self.active = True


class _AccessibleRectInterface(QAccessibleObject):
    """Accessible metadata for a treemap item anchored to its parent widget."""

    def __init__(self, obj: _AccessibleRectObject) -> None:
        super().__init__(obj)

    def child(self, index: int) -> QAccessibleInterface:
        """Expose no grandchildren for a single treemap rectangle."""
        return cast(QAccessibleInterface, None)

    def childAt(self, x: int, y: int) -> QAccessibleInterface:
        """Return no descendants for a single treemap rectangle."""
        return cast(QAccessibleInterface, None)

    def childCount(self) -> int:
        """Return zero because rectangle items are leaves."""
        return 0

    def indexOfChild(self, child: QAccessibleInterface) -> int:
        """Return -1 because rectangle items have no children."""
        return -1

    def role(self) -> QAccessible.Role:
        """Describe a treemap rectangle as a graphic."""
        return QAccessible.Role.Graphic

    def text(self, text: QAccessible.Text) -> str:
        """Return the prepared item name and size for the Name text role."""
        obj = cast(_AccessibleRectObject, self.object())
        if text == QAccessible.Text.Name:
            return obj.entry.name
        return ""

    def rect(self) -> QRect:
        """Convert widget-local logical geometry to screen coordinates."""
        obj = cast(_AccessibleRectObject, self.object())
        widget = obj.parent()
        if not isinstance(widget, QWidget) or not widget.isVisible():
            return QRect()
        logical = obj.entry.rect
        origin = widget.mapToGlobal(QPoint(0, 0))
        return QRectF(logical.translated(origin.x(), origin.y())).toAlignedRect()

    def parent(self) -> QAccessibleInterface:
        """Return the cached accessible interface for the treemap widget."""
        obj = cast(_AccessibleRectObject, self.object())
        owner = obj.owner_ref()
        if owner is None:
            return cast(QAccessibleInterface, None)
        return cast(QAccessibleInterface, owner._get_interface())

    def isValid(self) -> bool:
        """Report whether this proxy still represents a current accessible item."""
        obj = cast(_AccessibleRectObject, self.object())
        return obj.active and super().isValid()

    def state(self) -> QAccessible.State:
        """Reflect visibility and enabled state from the owning treemap widget."""
        result = QAccessible.State()
        obj = cast(_AccessibleRectObject, self.object())
        widget = obj.parent()
        if isinstance(widget, QWidget):
            result.invisible = not widget.isVisible()
            result.disabled = not widget.isEnabled()
            owner = obj.owner_ref()
            if owner is not None and owner.focus_index is not None:
                result.focusable = True
                result.selected = owner._objects[owner.focus_index] is obj
                result.focused = result.selected and widget.hasFocus()
        return result


class TreemapAccessibility:
    """Expose up to 50 virtual Graphic children without creating child widgets."""

    def __init__(self, widget: QWidget) -> None:
        self._widget_ref = ref(widget)
        self._entries: tuple[AccessibleRect, ...] = ()
        self._objects: list[_AccessibleRectObject] = []
        self._interfaces: dict[int, QAccessibleInterface] = {}
        self._interface: _TreemapAccessibleInterface | None = None
        self._destroyed = False
        self.focus_index: int | None = None
        widget.accessibility = self  # type: ignore[attr-defined]
        widget.destroyed.connect(self._on_widget_destroyed)
        _FactoryRegistration.ensure_installed()

    @property
    def entries(self) -> tuple[AccessibleRect, ...]:
        """Return the current bounded immutable list of virtual children."""
        return self._entries

    def update(self, entries: tuple[AccessibleRect, ...]) -> None:
        """Replace the visible virtual children; input is bounded to 50 entries."""
        if len(entries) > _MAX_VIRTUAL_CHILDREN:
            raise ValueError(f"at most {_MAX_VIRTUAL_CHILDREN} accessible items are supported")
        if any(not isinstance(entry, AccessibleRect) for entry in entries):
            raise TypeError("entries must contain AccessibleRect values")
        widget = self._widget_ref()
        if self._destroyed or widget is None:
            return

        self._entries = tuple(entries)
        self.focus_index = None
        for index, entry in enumerate(self._entries):
            if index < len(self._objects):
                child = self._objects[index]
                child.entry = entry
                child.active = True
            else:
                self._objects.append(_AccessibleRectObject(widget, entry, self))
        for child in self._objects[len(self._entries) :]:
            child.active = False
        if QAccessible.isActive():
            event = QAccessibleEvent(widget, QAccessible.Event.ObjectReorder)
            QAccessible.updateAccessibility(event)

    def set_focus(self, index: int) -> None:
        """Expose the canvas's active virtual item to screen-reader focus queries."""
        if not 0 <= index < len(self._entries):
            raise IndexError(index)
        self.focus_index = index
        if QAccessible.isActive():
            QAccessible.updateAccessibility(
                QAccessibleEvent(self._objects[index], QAccessible.Event.Focus)
            )

    def _interface_for(self, index: int) -> QAccessibleInterface | None:
        if index < 0 or index >= len(self._objects):
            return None
        child = self._objects[index]
        key = id(child)
        interface = self._interfaces.get(key)
        if interface is None:
            interface = QAccessible.queryAccessibleInterface(child)
            if interface is None:
                return None
            self._interfaces[key] = interface
        return interface

    def _get_interface(self) -> _TreemapAccessibleInterface | None:
        widget = self._widget_ref()
        if self._destroyed or widget is None:
            return None
        if self._interface is None:
            self._interface = _TreemapAccessibleInterface(widget, self)
        return self._interface

    def _on_widget_destroyed(self, _object: QObject | None = None) -> None:
        self._destroyed = True
        self.focus_index = None
        self._entries = ()
        for child in self._objects:
            child.active = False
        self._objects.clear()
        self._interfaces.clear()
        self._interface = None


class _TreemapAccessibleInterface(QAccessibleWidget):
    """Widget interface whose children are native-layout item proxies."""

    def __init__(self, widget: QWidget, owner: TreemapAccessibility) -> None:
        super().__init__(widget, QAccessible.Role.Graphic)
        self._owner = owner

    def text(self, text: QAccessible.Text) -> str:
        """Use the widget's localized name and standard QAccessible text handling."""
        if text == QAccessible.Text.Name:
            widget = self.widget()
            return widget.accessibleName() or _("Treemap")
        return super().text(text)

    def child(self, index: int) -> QAccessibleInterface:
        """Return the cached virtual child at the zero-based index."""
        if index < 0 or index >= len(self._owner.entries):
            return cast(QAccessibleInterface, None)
        interface = self._owner._interface_for(index)
        return cast(QAccessibleInterface, interface)

    def childCount(self) -> int:
        """Return the bounded number of largest visible rectangles."""
        return len(self._owner.entries)

    def focusChild(self) -> QAccessibleInterface:
        """Return the active virtual item while its canvas owns keyboard focus."""
        index = self._owner.focus_index
        if index is not None and self.widget().hasFocus():
            return self.child(index)
        return super().focusChild()

    def indexOfChild(self, child: QAccessibleInterface) -> int:
        """Find a virtual child by its QObject proxy identity."""
        obj = child.object()
        for index, proxy in enumerate(self._owner._objects):
            if obj == proxy:
                return index
        return -1

    def childAt(self, x: int, y: int) -> QAccessibleInterface:
        """Return the smallest exposed item containing a screen-coordinate point."""
        point = QPoint(x, y)
        matches: list[tuple[int, QAccessibleInterface]] = []
        for index, entry in enumerate(self._owner.entries):
            interface = self._owner._interface_for(index)
            if interface is not None and interface.rect().contains(point):
                area = max(0, entry.rect.toAlignedRect().width()) * max(
                    0, entry.rect.toAlignedRect().height()
                )
                matches.append((area, interface))
        if not matches:
            return cast(QAccessibleInterface, None)
        return min(matches, key=lambda item: item[0])[1]

    def isValid(self) -> bool:
        """Remain valid only while its widget and controller are alive."""
        return not self._owner._destroyed and super().isValid()


def _accessible_factory(class_name: str, obj: QObject) -> QAccessibleInterface | None:
    """Create cached Qt interfaces for a treemap widget or one item proxy."""
    del class_name
    if isinstance(obj, _AccessibleRectObject):
        return _AccessibleRectInterface(obj)
    owner = getattr(obj, "accessibility", None)
    if isinstance(owner, TreemapAccessibility):
        return owner._get_interface()
    return None


__all__ = ["AccessibleRect", "TreemapAccessibility"]
