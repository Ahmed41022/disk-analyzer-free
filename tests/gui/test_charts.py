"""Pie and bar chart geometry, labels, keyboard use, and folder navigation."""

# ruff: noqa: PLR2004 -- small, fixed report values and geometry are assertions.

import os
import threading
from collections.abc import Iterator
from importlib.util import find_spec
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

if find_spec("PySide6") is None:
    if os.environ.get("DAFREE_REQUIRE_GUI") == "1":
        pytest.fail("PySide6 is required when DAFREE_REQUIRE_GUI=1", pytrace=False)
    pytest.skip("PySide6 is not installed", allow_module_level=True)

from PySide6.QtCore import QCoreApplication, QEvent, QLocale, Qt
from PySide6.QtGui import QAccessible
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from dafree import api
from dafree.api.analysis import ChartKind, ChartSlice, chart_data
from dafree.api.testing import MockEntry, MockSpec, make_mock_backend
from dafree.gui import _number_translation
from dafree.gui.controllers.task_runner import TaskRunner
from dafree.gui.main_window import MainWindow
from dafree.gui.views import charts_tab as charts_tab_module
from dafree.gui.views.charts_tab import ChartsTab
from dafree.gui.views.tree_tab import TreeTab
from dafree.gui.widgets.bar_chart import BarChart
from dafree.gui.widgets.pie_chart import PieChart
from dafree.paths import AppPaths
from dafree.settings import Settings

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def flush_deferred_qt_deletes(qapp: QApplication) -> Iterator[None]:
    """Flush qtbot's queued widget deletions before native module shutdown."""
    yield
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _make_tree(root: Path) -> api.Tree:
    entries = [
        MockEntry(root, api.EntryKind.DIR),
        MockEntry(root / "folder", api.EntryKind.DIR),
        MockEntry(root / "folder/inside.bin", size=10),
        MockEntry(root / "small.bin", size=20),
        MockEntry(root / "large.bin", size=70),
    ]
    return api.scan(api.ScanRequest([root]), backend=make_mock_backend(MockSpec(entries))).tree


def test_pie_angles_sum_to_360(qtbot: QtBot) -> None:
    widget = PieChart(Settings())
    qtbot.addWidget(widget)
    widget.set_data((ChartSlice("A", 1), ChartSlice("B", 2), ChartSlice("C", 3)))
    assert len(widget.slice_angles()) == 3
    assert sum(widget.slice_angles()) == pytest.approx(360.0)


def test_pie_tiny_remainder_remains_keyboard_and_legend_accessible(qtbot: QtBot) -> None:
    """Unrepresentable tiny sectors never produce negative angles or inaccessible items."""
    widget = PieChart(Settings())
    qtbot.addWidget(widget)
    widget.resize(520, 500)
    widget.set_data(
        [ChartSlice(str(index), (1 << 64) - 1) for index in range(15)] + [ChartSlice("Tiny", 1)]
    )
    widget.show()
    assert min(widget.slice_angles()) >= 0
    assert sum(widget.slice_angles()) == pytest.approx(360.0)
    qtbot.mouseClick(widget, Qt.MouseButton.LeftButton, pos=widget.slice_point(15).toPoint())
    assert widget.selected_index == 15


def test_other_slice_aggregates_remainder(tmp_path: Path) -> None:
    tree = _make_tree(tmp_path / "scan")
    slices = chart_data(tree, tree.roots()[0], ChartKind.CHILDREN_BY_SIZE, top=1)
    other = next(item for item in slices if item.is_other)
    assert other.value == 30
    assert sum(item.value for item in slices) == 100


def test_bar_labels_use_units(qtbot: QtBot) -> None:
    widget = BarChart(Settings())
    qtbot.addWidget(widget)
    widget.set_data((ChartSlice("Large", 1024),), count_values=False)
    assert widget.slice_labels()
    assert api.format_size(1024) in widget.slice_labels()[0]
    widget.set_data((ChartSlice("Files", 2),), count_values=True)
    assert "2" in widget.slice_labels()[0]
    assert "KB" not in widget.slice_labels()[0]
    assert "%" in widget.slice_labels()[0]


def test_slice_keyboard_focus(qtbot: QtBot) -> None:
    widget = PieChart(Settings())
    qtbot.addWidget(widget)
    widget.resize(480, 320)
    widget.set_data((ChartSlice("Alpha", 1, 11), ChartSlice("Beta", 2, 12)))
    widget.setFocus()
    qtbot.keyClick(widget, Qt.Key.Key_End)
    assert widget.selected_index == 1
    assert "Beta" in widget.accessibleDescription()
    with qtbot.waitSignal(widget.sliceActivated) as activated:
        qtbot.keyClick(widget, Qt.Key.Key_Return)
    assert activated.args == [12]


def test_bar_keyboard_focus_and_activation(qtbot: QtBot) -> None:
    widget = BarChart(Settings())
    qtbot.addWidget(widget)
    widget.set_data((ChartSlice("Alpha", 1, 21), ChartSlice("Beta", 2, 22)))
    widget.setFocus()
    qtbot.keyClick(widget, Qt.Key.Key_End)
    assert widget.selected_index == 1
    with qtbot.waitSignal(widget.sliceActivated) as activated:
        qtbot.keyClick(widget, Qt.Key.Key_Space)
    assert activated.args == [22]


@pytest.mark.parametrize("chart_type", [PieChart, BarChart])
def test_accessible_children_have_slice_names(qtbot: QtBot, chart_type) -> None:
    widget = chart_type(Settings())
    qtbot.addWidget(widget)
    widget.set_data(tuple(ChartSlice(f"Slice {index}", index + 1) for index in range(4)))
    interface = QAccessible.queryAccessibleInterface(widget)
    assert interface is not None
    assert interface.childCount() == 4
    names = [
        interface.child(index).text(QAccessible.Text.Name)
        for index in range(interface.childCount())
    ]
    assert all(f"Slice {index}" in name for index, name in enumerate(names))


@pytest.mark.parametrize("chart_type", [PieChart, BarChart])
def test_empty_and_zero_slices_have_no_invalid_geometry(qtbot: QtBot, chart_type) -> None:
    widget = chart_type(Settings())
    qtbot.addWidget(widget)
    widget.set_data((ChartSlice("Zero", 0, 1),))
    assert widget.slices == ()
    assert widget.selected_index is None
    if chart_type is PieChart:
        assert widget.slice_angles() == ()


def test_mouse_activation_of_folder_slice_changes_scope(qtbot: QtBot, tmp_path: Path) -> None:
    tree = _make_tree(tmp_path / "scan")
    folder = tree.find_path(tmp_path / "scan/folder")
    assert folder is not None
    runner = TaskRunner()
    tab = ChartsTab(Settings(), runner)
    qtbot.addWidget(tab)
    tab.resize(720, 480)
    tab.show()
    with qtbot.waitSignal(tab.ready, timeout=5000):
        tab.set_tree(tree)
    assert tab.scope == tree.roots()[0]
    folder_slice = next(index for index, item in enumerate(tab.pie.slices) if item.node == folder)
    point = tab.pie.slice_point(folder_slice)
    with qtbot.waitSignal(tab.ready, timeout=5000):
        qtbot.mouseClick(tab.pie, Qt.MouseButton.LeftButton, pos=point.toPoint())
    assert tab.scope == folder
    assert tab.tree is tree
    qtbot.waitUntil(lambda: not runner.busy, timeout=5000)
    runner.deleteLater()


def test_keyboard_folder_activation_changes_scope(qtbot: QtBot, tmp_path: Path) -> None:
    tree = _make_tree(tmp_path / "keyboard")
    folder = tree.find_path(tmp_path / "keyboard/folder")
    assert folder is not None
    runner = TaskRunner()
    tab = ChartsTab(Settings(), runner)
    qtbot.addWidget(tab)
    tab.resize(720, 480)
    tab.show()
    with qtbot.waitSignal(tab.ready, timeout=5000):
        tab.set_tree(tree)
    assert any(item.node == folder for item in tab.pie.slices)
    tab.pie.setFocus()
    with qtbot.waitSignal(tab.ready, timeout=5000):
        qtbot.keyClick(tab.pie, Qt.Key.Key_End)
        qtbot.keyClick(tab.pie, Qt.Key.Key_Space)
    assert tab.scope == folder
    qtbot.waitUntil(lambda: not runner.busy, timeout=5000)
    runner.deleteLater()


def test_clear_removes_stale_charts_and_scope(qtbot: QtBot, tmp_path: Path) -> None:
    tree = _make_tree(tmp_path / "stale")
    runner = TaskRunner()
    tab = ChartsTab(Settings(), runner)
    qtbot.addWidget(tab)
    tab.set_tree(tree)
    tab.clear()
    assert tab.tree is None
    assert tab.scope is None
    assert tab.pie.slices == ()
    assert tab.bar.slices == ()
    qtbot.waitUntil(lambda: not runner.busy, timeout=5000)
    runner.deleteLater()


def test_stale_background_kind_result_does_not_replace_current_data(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = _make_tree(tmp_path / "stale-kind")
    runner = TaskRunner()
    tab = ChartsTab(Settings(), runner)
    qtbot.addWidget(tab)
    started, release = threading.Event(), threading.Event()
    calls = 0

    def gated_prepare(_tree, _scope, _kind):
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            if not release.wait(5):
                raise TimeoutError("chart preparation gate was not released")
            return [ChartSlice("Stale", 99)]
        return [ChartSlice("Current", 42)]

    monkeypatch.setattr(charts_tab_module, "_prepare", gated_prepare)
    tab.set_tree(tree)
    qtbot.waitUntil(started.is_set, timeout=5000)
    try:
        tab.kind.setCurrentIndex(1)
        with qtbot.waitSignal(tab.ready, timeout=5000):
            release.set()
    finally:
        release.set()
    assert tab.pie.slices == (ChartSlice("Current", 42),)
    assert tab.bar.slices == (ChartSlice("Current", 42),)
    qtbot.waitUntil(lambda: not runner.busy, timeout=5000)
    runner.deleteLater()


@pytest.mark.parametrize("chart_type", [PieChart, BarChart])
def test_accessible_focus_child_tracks_keyboard_selection(qtbot: QtBot, chart_type) -> None:
    widget = chart_type(Settings())
    qtbot.addWidget(widget)
    widget.resize(520, 360)
    widget.set_data((ChartSlice("Alpha", 1), ChartSlice("Beta", 2), ChartSlice("Gamma", 3)))
    widget.show()
    widget.activateWindow()
    widget.setFocus()
    qtbot.waitUntil(widget.hasFocus, timeout=5000)
    qtbot.keyClick(widget, Qt.Key.Key_Right)
    assert widget.selected_index == 0
    qtbot.keyClick(widget, Qt.Key.Key_End)
    assert widget.selected_index == 2

    interface = QAccessible.queryAccessibleInterface(widget)
    assert interface is not None
    focused = interface.focusChild()
    assert focused is not None
    assert widget.slice_labels()[2] in focused.text(QAccessible.Text.Name)
    assert focused.state().selected
    assert focused.state().focused


def test_count_label_formats_uint64_max_without_overflow(qtbot: QtBot) -> None:
    widget = BarChart(Settings())
    qtbot.addWidget(widget)
    maximum = (1 << 64) - 1
    widget.set_data((ChartSlice("All files", maximum),), count_values=True)
    localized = str(maximum).translate(_number_translation(QLocale().name(), "."))
    assert localized in widget.slice_labels()[0]


@pytest.mark.parametrize(
    ("system", "expected_unit"),
    [
        (api.UnitSystem.TRADITIONAL, "MB"),
        (api.UnitSystem.IEC, "MiB"),
    ],
)
def test_bar_size_label_uses_selected_size_mode_and_unit_system(
    qtbot: QtBot, system: api.UnitSystem, expected_unit: str
) -> None:
    settings = Settings(
        units=api.UnitMode.MEGA,
        unit_style=api.UnitStyle(system=system),
    )
    widget = BarChart(settings)
    qtbot.addWidget(widget)
    widget.set_data((ChartSlice("Large file", 3 * 1024 * 1024),))
    assert expected_unit in widget.slice_labels()[0]
    assert (
        api.format_size(3 * 1024 * 1024, api.UnitMode.MEGA, settings.unit_style)
        in widget.slice_labels()[0]
    )


def test_pie_slice_points_hit_each_sector(qtbot: QtBot) -> None:
    widget = PieChart(Settings())
    qtbot.addWidget(widget)
    widget.resize(520, 360)
    widget.set_data((ChartSlice("Small", 1), ChartSlice("Medium", 2), ChartSlice("Large", 3)))
    widget.show()
    for index in range(len(widget.slices)):
        qtbot.mouseClick(
            widget,
            Qt.MouseButton.LeftButton,
            pos=widget.slice_point(index).toPoint(),
        )
        assert widget.selected_index == index


@pytest.mark.parametrize("chart_type", [PieChart, BarChart])
def test_other_slice_is_not_activated(qtbot: QtBot, chart_type) -> None:
    widget = chart_type(Settings())
    qtbot.addWidget(widget)
    widget.resize(520, 360)
    widget.set_data((ChartSlice("Other", 1, None, True),))
    widget.show()
    activated = QSignalSpy(widget.sliceActivated)
    qtbot.mouseClick(
        widget,
        Qt.MouseButton.LeftButton,
        pos=widget.slice_point(0).toPoint(),
    )
    assert widget.selected_index == 0
    assert activated.count() == 0


def test_main_window_folder_activation_syncs_tree_selection_and_scope(
    qtbot: QtBot, tmp_path: Path
) -> None:
    root = tmp_path / "main-window"
    tree = _make_tree(root)
    folder = tree.find_path(root / "folder")
    assert folder is not None
    window = MainWindow(
        paths=AppPaths(
            tmp_path / "config", tmp_path / "data", tmp_path / "logs", tmp_path / "snapshots", False
        ),
        settings=Settings(),
        scan_backend=make_mock_backend(
            MockSpec(
                [
                    MockEntry(root, api.EntryKind.DIR),
                    MockEntry(root / "folder", api.EntryKind.DIR),
                    MockEntry(root / "folder/inside.bin", size=10),
                    MockEntry(root / "small.bin", size=20),
                    MockEntry(root / "large.bin", size=70),
                ]
            )
        ),
        volume_provider=lambda: [],
    )

    def finish(widget) -> None:
        widget.close()
        qtbot.waitUntil(
            lambda: not window.controller.running and not window.runner.busy, timeout=10_000
        )

    qtbot.addWidget(window, before_close_func=finish)
    window.show()
    with qtbot.waitSignal(window.controller.finished, timeout=5000):
        window.start_scan(api.ScanRequest([root], threads=1))
    tree_page = window._pages["tree"]
    assert isinstance(tree_page, TreeTab)
    qtbot.waitUntil(lambda: tree_page.table is not None, timeout=5000)
    window.show_tab("charts")
    charts = window._pages["charts"]
    assert isinstance(charts, ChartsTab)
    qtbot.waitUntil(lambda: any(item.node == folder for item in charts.pie.slices), timeout=5000)
    index = next(i for i, item in enumerate(charts.pie.slices) if item.node == folder)
    point = charts.pie.slice_point(index)
    qtbot.mouseClick(charts.pie, Qt.MouseButton.LeftButton, pos=point.toPoint())
    qtbot.waitUntil(lambda: charts.scope == folder, timeout=5000)
    table = tree_page.table
    assert table is not None
    qtbot.waitUntil(
        lambda: table.tree_model.node_at(table.currentIndex().row()) == folder, timeout=5000
    )
    with qtbot.waitSignal(charts.ready, timeout=5000):
        charts.breadcrumb.up.click()
    assert charts.scope == tree.roots()[0]
    with qtbot.waitSignal(charts.ready, timeout=5000):
        charts.breadcrumb.up.click()
    assert charts.scope == 0
    window.units.setCurrentIndex(1)
    assert charts.scope == 0
    window.show_tab("tree")
    window.show_tab("charts")
    assert charts.scope == 0
