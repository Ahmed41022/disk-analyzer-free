"""Virtual treemap accessibility items, geometry, and breadcrumb scope."""

# ruff: noqa: PLR2004 -- accessibility limits and pixel geometry are contract assertions.

import os
from collections.abc import Iterator
from importlib.util import find_spec
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

if find_spec("PySide6") is None:
    if os.environ.get("DAFREE_REQUIRE_GUI") == "1":
        pytest.fail("PySide6 is required when DAFREE_REQUIRE_GUI=1", pytrace=False)
    pytest.skip("PySide6 is not installed", allow_module_level=True)

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRectF
from PySide6.QtGui import QAccessible, QAccessibleInterface
from PySide6.QtWidgets import QApplication, QWidget

from dafree import api
from dafree.api.testing import MockEntry, MockSpec, make_mock_backend
from dafree.gui.accessibility import AccessibleRect, TreemapAccessibility
from dafree.gui.controllers.task_runner import TaskRunner
from dafree.gui.views.treemap_tab import TreemapTab
from dafree.settings import Settings

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def flush_deferred_qt_deletes(qapp: QApplication) -> Iterator[None]:
    """Run qtbot's queued deleteLater requests before the native module shuts down."""
    yield
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def make_accessible_widget(
    qtbot: QtBot, entries: tuple[AccessibleRect, ...]
) -> tuple[QWidget, TreemapAccessibility, QAccessibleInterface]:
    """Build a visible QWidget whose virtual rectangles require no disk scan."""
    widget = QWidget()
    widget.resize(160, 120)
    qtbot.addWidget(widget)
    controller = TreemapAccessibility(widget)
    controller.update(entries)
    widget.show()
    interface = QAccessible.queryAccessibleInterface(widget)
    assert interface is not None
    return widget, controller, interface


def test_virtual_children_have_geometry_parent_indices_and_nested_hit_test(
    qtbot: QtBot,
) -> None:
    """Children expose screen geometry, link back to the canvas, and hit the smallest item."""
    entries = (
        AccessibleRect(7, "Outer folder, 20 B", QRectF(10, 10, 80, 80)),
        AccessibleRect(7, "Nested file, 5 B", QRectF(25, 25, 20, 20)),
    )
    widget, _controller, interface = make_accessible_widget(qtbot, entries)

    assert interface.childCount() == 2
    outer, nested = interface.child(0), interface.child(1)
    assert outer.text(QAccessible.Text.Name) == entries[0].name
    assert nested.text(QAccessible.Text.Name) == entries[1].name
    assert outer.parent().object() is widget
    assert nested.parent().object() is widget
    origin = widget.mapToGlobal(QPoint(0, 0))
    expected = QRectF(entries[0].rect).translated(origin.x(), origin.y()).toAlignedRect()
    assert outer.rect() == expected
    assert interface.indexOfChild(outer) == 0
    assert interface.indexOfChild(nested) == 1

    point = widget.mapToGlobal(QPoint(30, 30))
    hit = interface.childAt(point.x(), point.y())
    assert hit is not None
    assert hit.text(QAccessible.Text.Name) == entries[1].name
    assert not [child for child in widget.children() if isinstance(child, QWidget)]


def test_accessible_children_are_capped_and_clear_invalidates_retained_child(
    qtbot: QtBot,
) -> None:
    """Updates remain bounded and a retained child becomes invalid when its layout clears."""
    entries = tuple(
        AccessibleRect(index, f"Item {index}, 1 B", QRectF(index, 0, 10, 10)) for index in range(50)
    )
    _widget, controller, interface = make_accessible_widget(qtbot, entries)
    assert interface.childCount() == 50
    retained = interface.child(0)
    assert retained.isValid()

    with pytest.raises(ValueError, match="at most 50"):
        controller.update((*entries, AccessibleRect(50, "Item 50, 1 B", QRectF(0, 0, 1, 1))))
    assert interface.childCount() == 50

    controller.update(())
    assert interface.childCount() == 0
    assert not retained.isValid()


def test_virtual_child_visibility_and_disabled_state_follow_widget(qtbot: QtBot) -> None:
    """Accessible state and geometry track canvas visibility and enabled state."""
    widget, _controller, interface = make_accessible_widget(
        qtbot, (AccessibleRect(1, "File, 1 B", QRectF(5, 6, 10, 12)),)
    )
    child = interface.child(0)
    assert not child.state().invisible
    assert not child.state().disabled
    assert not child.rect().isEmpty()

    widget.setEnabled(False)
    assert child.state().disabled
    widget.hide()
    assert child.state().invisible
    assert child.rect().isEmpty()


def test_multi_root_breadcrumb_returns_to_synthetic_root(qtbot: QtBot, tmp_path: Path) -> None:
    """A multi-root tree starts at node zero and its breadcrumb navigates back to zero."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    tree = api.scan(
        api.ScanRequest([first, second]),
        backend=make_mock_backend(
            MockSpec(
                [
                    MockEntry(first, api.EntryKind.DIR),
                    MockEntry(first / "one.bin", size=10),
                    MockEntry(second, api.EntryKind.DIR),
                    MockEntry(second / "two.bin", size=20),
                ]
            )
        ),
    ).tree
    roots = tree.roots()
    assert len(roots) == 2

    runner = TaskRunner()
    tab = TreemapTab(Settings(), runner)
    qtbot.addWidget(tab)
    tab.resize(480, 320)
    tab.show()
    with qtbot.waitSignal(tab.widget.ready, timeout=5000):
        tab.set_tree(tree)
    assert tab.widget.zoom_root == 0
    assert tab.breadcrumb.path_label.toolTip() == "All scan targets"
    assert tab.widget.tooltip_for(0).startswith("All scan targets\n")
    interface = QAccessible.queryAccessibleInterface(tab.widget)
    assert interface is not None
    assert interface.child(0).text(QAccessible.Text.Name).startswith("All scan targets, ")

    with qtbot.waitSignal(tab.widget.ready, timeout=5000):
        tab.widget.zoom_to(roots[0])
    assert tab.breadcrumb.up.isEnabled()
    with qtbot.waitSignal(tab.widget.ready, timeout=5000):
        tab.breadcrumb.up.click()
    assert tab.widget.zoom_root == 0
    assert tab.widget.layout_result is not None
    assert tab.widget.layout_result.rects[0]["node"] == 0

    qtbot.waitUntil(lambda: not runner.busy, timeout=5000)
    runner.deleteLater()
