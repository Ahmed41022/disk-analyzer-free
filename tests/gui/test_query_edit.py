"""Debounced native filters, precise query diagnostics, and formatting without refetch."""

# ruff: noqa: PLR2004 -- debounce, span and fixture values verify the specified contract.

import os
import threading
from dataclasses import replace
from importlib.util import find_spec
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

if find_spec("PySide6") is None:
    if os.environ.get("DAFREE_REQUIRE_GUI") == "1":
        pytest.fail("PySide6 is required when DAFREE_REQUIRE_GUI=1", pytrace=False)
    pytest.skip("PySide6 is not installed", allow_module_level=True)

from PySide6.QtCore import QCoreApplication, QEvent, Qt

from dafree import api, query
from dafree.api.testing import MockEntry, MockSpec, make_mock_backend
from dafree.gui.main_window import MainWindow
from dafree.gui.models.tree_model import TreeTableModel
from dafree.gui.views import tree_tab as tree_module
from dafree.gui.views.tree_tab import TreeTab
from dafree.gui.widgets import query_edit as module
from dafree.gui.widgets.query_edit import QueryEdit
from dafree.i18n import N_, current_locale, setup
from dafree.settings import ColumnId, Settings

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def restore_locale():
    """Queries use the active catalogue without leaking locale changes to other tests."""
    previous = current_locale()
    setup("en_US")
    yield
    setup(previous)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def make_tree(root: Path) -> api.Tree:
    """Use only native mock entries under this test's temporary directory."""
    backend = make_mock_backend(
        MockSpec(
            [
                MockEntry(root, api.EntryKind.DIR),
                MockEntry(root / "nested", api.EntryKind.DIR),
                MockEntry(root / "nested/REPORT[1].txt", size=4096),
                MockEntry(root / "other.txt", size=2048),
            ]
        )
    )
    return api.scan(api.ScanRequest([root]), backend=backend).tree


def make_edit(qtbot: QtBot) -> QueryEdit:
    """Create a visible native editing surface for real paint/keyboard behavior."""
    edit = QueryEdit()
    qtbot.addWidget(edit)
    edit.resize(340, 36)
    edit.show()
    return edit


@pytest.mark.parametrize(
    "direction", [Qt.LayoutDirection.LeftToRight, Qt.LayoutDirection.RightToLeft]
)
@pytest.mark.parametrize(
    "scenario",
    [
        ("prefix 😀 broken suffix", (9, 15), 10, 16),
        ("ملف خاطئ نهاية", (4, 8), 4, 8),
        ("ملف bad نهاية", (4, 7), 4, 7),
        ("padding " * 40 + "broken", (320, 326), 320, 326),
    ],
    ids=["emoji", "arabic", "mixed", "scrolled"],
)
def test_invalid_query_underlines_span(qtbot: QtBot, direction, scenario, monkeypatch) -> None:
    """The actual red wave follows the parser's characters, including UTF-16 offsets."""
    edit = make_edit(qtbot)
    edit.setLayoutDirection(direction)
    emitted = []
    edit.filterChanged.connect(emitted.append)
    text, span, cursor_start, cursor_end = scenario

    def invalid(value: str) -> query.Query:
        assert value == text
        raise query.QueryError(span, N_("Search text cannot contain a NUL character."))

    monkeypatch.setattr(module.query, "parse", invalid)
    edit.setText(text)
    qtbot.waitUntil(lambda: edit.error_span is not None)
    assert edit.error_span == span
    assert "NUL" in edit.toolTip()
    assert not emitted
    edit.setCursorPosition(cursor_start)
    start_x = edit.cursorRect().x()
    edit.setCursorPosition(cursor_end)
    end_x = edit.cursorRect().x()
    rectangle = edit.error_underline_rect()
    assert not rectangle.isEmpty()
    assert rectangle.width() < edit.width() / 2
    assert abs(rectangle.left() - min(start_x, end_x)) <= 2
    assert abs(rectangle.width() - abs(end_x - start_x)) <= 2
    image = edit.grab().toImage()
    scale = image.devicePixelRatio()
    red = []
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if (color.red(), color.green(), color.blue()) == (211, 47, 47):
                red.append((x, y))
    assert red, "The invalid span must actually paint a red underline"
    assert all(rectangle.adjusted(-1, -1, 1, 1).contains(x / scale, y / scale) for x, y in red)


def test_valid_query_filters_rows(qtbot: QtBot, tmp_path: Path) -> None:
    """Case-insensitive substring matching keeps ancestor paths and escapes glob syntax."""
    model = TreeTableModel(api.TreeView(make_tree(tmp_path)), list(ColumnId))
    edit = make_edit(qtbot)
    edit.filterChanged.connect(
        lambda spec: model.set_options(replace(model.view.options, filter=spec))
    )
    try:
        edit.setText("report[1]")
        qtbot.waitUntil(lambda: model.view.options.filter is not None)
        assert [row[4] for row in model.view.rows(0, 10)] == [str(tmp_path), "nested"]
        model.toggle(1)
        assert model.index(2, 0).data() == "REPORT[1].txt"
        assert model.view.options.filter == query.parse("report[1]").to_filter_spec()
        edit.clear()
        qtbot.waitUntil(lambda: model.view.options.filter is None)
        assert "other.txt" in [row[4] for row in model.view.rows(0, 10)]
    finally:
        model.deleteLater()


def test_debounce_and_invalid_input_preserves_filter(
    qtbot: QtBot, tmp_path: Path, monkeypatch
) -> None:
    """Rapid edits parse once after 250 ms; invalid input never replaces a working filter."""
    edit = make_edit(qtbot)
    calls = []
    original = query.parse

    def counted(text: str) -> query.Query:
        calls.append(text)
        return original(text)

    monkeypatch.setattr(module.query, "parse", counted)
    emitted = []
    edit.filterChanged.connect(emitted.append)
    edit.setText("r")
    qtbot.wait(100)
    assert not calls
    edit.setText("report")
    qtbot.wait(100)
    assert not calls
    qtbot.waitUntil(lambda: len(emitted) == 1)
    assert calls == ["report"]
    assert edit._timer.interval() == 250
    edit.setText("report\0")
    qtbot.waitUntil(lambda: edit.error_span is not None)
    assert edit.error_span == (6, 7)
    assert len(emitted) == 1
    edit.setText("other")
    assert edit.error_span is None
    qtbot.waitUntil(lambda: len(emitted) == 2)
    assert calls == ["report", "report\0", "other"]


def test_unit_switch_does_not_refetch(qtbot: QtBot, tmp_path: Path, monkeypatch) -> None:
    """Toolbar units reformat table/details/status while preserving native pages and selection."""
    window = MainWindow(settings=Settings(), volume_provider=lambda: [])

    def finish(widget) -> None:
        window.close()
        qtbot.waitUntil(lambda: not window.runner.busy and not window.controller.running)

    qtbot.addWidget(window, before_close_func=finish)
    window.show()
    page = window._pages["tree"]
    assert isinstance(page, TreeTab)
    window._tree_ready(make_tree(tmp_path))
    qtbot.waitUntil(lambda: page.table is not None)
    table = page.table
    model = table.tree_model
    index = model.index(0, list(ColumnId).index(ColumnId.SIZE))
    before = index.data()
    selection = model.node_at(table.currentIndex().row())
    pages = dict(model._pages)
    window.controller.progressChanged.emit(
        api.ScanProgress(
            2,
            1,
            6144,
            6144,
            0,
            str(tmp_path),
            250,
            api.ScanState.RUNNING,
            None,
            api.ScanModeUsed.WALK,
        )
    )
    resets = []
    model.modelReset.connect(lambda: resets.append(True))

    def no_rows(start: int, count: int):
        pytest.fail("Unit switching must not refetch native rows")

    monkeypatch.setattr(model.view, "rows", no_rows)
    window.units.setCurrentIndex(list(api.UnitMode).index(api.UnitMode.BYTES))
    assert index.data() != before
    assert index.data() == api.format_size(6144, api.UnitMode.BYTES)
    assert model.unit_mode == api.UnitMode.BYTES
    assert model._pages == pages
    assert not resets
    assert model.node_at(table.currentIndex().row()) == selection
    assert api.format_size(6144, api.UnitMode.BYTES) in page.details.text()
    assert window.total_label.text() == "Total: " + api.format_size(6144, api.UnitMode.BYTES)
    assert window._settings.units == api.UnitMode.BYTES
    assert window.units.accessibleName() == "Units"
    assert window.query_edit.accessibleName() == "Search results"
    qtbot.wait(30)


def test_filter_before_tree_ready_survives_new_scan(qtbot: QtBot, tmp_path: Path) -> None:
    """A query entered before a snapshot applies to that snapshot and subsequent scans."""
    window = MainWindow(volume_provider=lambda: [])

    def finish(widget) -> None:
        window.close()
        qtbot.waitUntil(lambda: not window.runner.busy and not window.controller.running)

    qtbot.addWidget(window, before_close_func=finish)
    window.query_edit.setText("report")
    page = window._pages["tree"]
    qtbot.waitUntil(lambda: page._filter is not None)
    window._tree_ready(make_tree(tmp_path))
    qtbot.waitUntil(lambda: page.table is not None)
    assert page.table.tree_model.view.options.filter == page._filter
    page.clear()
    window._tree_ready(make_tree(tmp_path))
    qtbot.waitUntil(lambda: page.table is not None)
    assert page.table.tree_model.view.options.filter == page._filter


def test_plain_parser_contract() -> None:
    """Stage only literal substring parsing behind the planned public parser interface."""
    parsed = query.parse("  report [1]?*\\file  ", si=True)
    assert str(parsed) == "report [1]?*\\file"
    assert query.parse(str(parsed)) == parsed
    assert not parsed.needs_owner()
    assert query.parse("   ").to_filter_spec() == api.FilterSpec()
    assert query.parse("size>1GB").to_filter_spec().values == ("*size>1GB*",)
    assert parsed.to_filter_spec().values == ("*report \\[1\\]\\?\\*\\\\file*",)
    with pytest.raises(api.QueryError) as raised:
        query.parse("😀\0")
    assert raised.value.span == (1, 2)
    assert query.QueryError is api.QueryError
    error = query.QueryError((0, 1), "bad {word}", args={"word": "x"})
    assert error.arguments == {"word": "x"}
    assert error.args == ("bad {word}",)
    with pytest.raises(ValueError, match="max_depth"):
        query.parse("x", max_depth=0)


def test_error_message_translated_with_arguments(qtbot: QtBot, monkeypatch) -> None:
    """Translate canonical error IDs at display time and interpolate their argument map."""
    edit = make_edit(qtbot)
    error = query.QueryError((0, 3), "bad {token}", args={"token": "x"})

    def invalid(text: str) -> query.Query:
        raise error

    monkeypatch.setattr(module.query, "parse", invalid)
    monkeypatch.setattr(
        module, "_", lambda text: "translated {token}" if text == error.message_id else text
    )
    edit.setText("bad")
    qtbot.waitUntil(lambda: edit.toolTip() == "translated x")
    assert error.message_id == "bad {token}"
    assert edit.error_span == (0, 3)


def test_filter_changed_during_preparation(qtbot: QtBot, tmp_path: Path, monkeypatch) -> None:
    """A pending worker's older options cannot replace the query entered while it ran."""
    window = MainWindow(volume_provider=lambda: [])
    entered, release = threading.Event(), threading.Event()

    def finish(widget) -> None:
        release.set()
        window.close()
        qtbot.waitUntil(lambda: not window.runner.busy and not window.controller.running)

    qtbot.addWidget(window, before_close_func=finish)
    original = api.TreeView

    def delayed(tree, options):
        view = original(tree, options)
        entered.set()
        assert release.wait(10)
        return view

    monkeypatch.setattr(tree_module.api, "TreeView", delayed)
    page = window._pages["tree"]
    window._tree_ready(make_tree(tmp_path))
    try:
        qtbot.waitUntil(entered.is_set)
        window.query_edit.setText("report")
        qtbot.waitUntil(lambda: page._filter is not None)
        release.set()
        qtbot.waitUntil(lambda: page.table is not None)
        assert page.table.tree_model.view.options.filter == page._filter
        assert page.table.tree_model.rowCount() == 2
    finally:
        release.set()
