"""Shipped GUI translations, Qt native strings, RTL inheritance, and locale rendering."""

from __future__ import annotations

import ast
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

from PySide6.QtCore import QCoreApplication, QDateTime, QEvent, QLocale, Qt
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from dafree import api
from dafree.api.testing import MockEntry, MockSpec, make_mock_backend
from dafree.gui import _format_size
from dafree.gui.app import _ApplicationState, build_app
from dafree.gui.main_window import MainWindow
from dafree.gui.models.tree_model import TreeTableModel
from dafree.gui.widgets.progress_panel import elapsed_text
from dafree.i18n import _, current_locale, setup
from dafree.paths import AppPaths
from dafree.settings import ColumnId, Settings

pytestmark = pytest.mark.gui
_VISIBLE_CALLS = {
    "setText",
    "setWindowTitle",
    "QAction",
    "QLabel",
    "setToolTip",
    "addTab",
    "setAccessibleName",
    "setPlaceholderText",
    "addItem",
    "setTitle",
    "addAction",
    "addButton",
    "setInformativeText",
    "setDetailedText",
    "setFormat",
    "QPushButton",
    "QCheckBox",
    "QGroupBox",
    "QDockWidget",
    "QToolBar",
    "addRow",
}
_SYMBOLS = {"—", "�"}


def _literal_violations(source: str) -> list[tuple[int, str]]:
    def literals(node: ast.AST) -> Iterator[tuple[int, str]]:
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in {"_", "ngettext"}:
                return
            if isinstance(node.func, ast.Attribute) and node.func.attr == "toString":
                # The fixed-point format code is a parameter, not visible prose.
                for argument in node.args:
                    if not (isinstance(argument, ast.Constant) and argument.value == "f"):
                        yield from literals(argument)
                return
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.strip()
            and node.value not in _SYMBOLS
        ):
            yield node.lineno, node.value
        for child in ast.iter_child_nodes(node):
            yield from literals(child)

    result = []
    for call in ast.walk(ast.parse(source)):
        if not isinstance(call, ast.Call):
            continue
        name = (
            call.func.attr
            if isinstance(call.func, ast.Attribute)
            else call.func.id
            if isinstance(call.func, ast.Name)
            else ""
        )
        if name in _VISIBLE_CALLS:
            for argument in [*call.args, *(kw.value for kw in call.keywords)]:
                result.extend(literals(argument))
    return result


@pytest.fixture(autouse=True)
def restore_application(qapp: QApplication) -> Iterator[None]:
    """Restore translators, hooks, gettext, and Qt state after each locale scenario."""
    previous, locale = current_locale(), QLocale()
    palette, stylesheet, direction = qapp.palette(), qapp.styleSheet(), qapp.layoutDirection()
    yield
    state = qapp.findChild(_ApplicationState, "dafree.application")
    if state is not None:
        state.close()
        state.setParent(None)
        state.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    setup(previous)
    QLocale.setDefault(locale)
    qapp.setPalette(palette)
    qapp.setStyleSheet(stylesheet)
    qapp.setLayoutDirection(direction)


def test_arabic_sets_rtl_layout(qtbot: QtBot, qapp: QApplication, tmp_path: Path) -> None:
    """Arabic reaches real window children and native Qt buttons, with localized counters."""
    paths = AppPaths(tmp_path, tmp_path / "data", tmp_path / "logs", tmp_path / "snaps", False)
    settings = Settings(locale="ar")
    build_app([], paths, settings)
    window = MainWindow(paths=paths, settings=settings, volume_provider=lambda: [])

    def finish(widget) -> None:
        window.close()
        qtbot.waitUntil(lambda: not window.runner.busy and not window.controller.running)

    qtbot.addWidget(window, before_close_func=finish)
    window.show()
    assert qapp.layoutDirection() == Qt.LayoutDirection.RightToLeft
    assert window.layoutDirection() == Qt.LayoutDirection.RightToLeft
    assert window.query_edit.layoutDirection() == Qt.LayoutDirection.RightToLeft
    assert window.windowTitle() == _("Disk Analyzer Free") != "Disk Analyzer Free"
    assert QLocale().toString(0) in window.files_label.text()
    window.open_settings()
    dialog = window._settings_dialog
    assert dialog is not None and dialog.layoutDirection() == Qt.LayoutDirection.RightToLeft
    cancel = dialog.buttons.button(QDialogButtonBox.StandardButton.Cancel)
    assert cancel is not None and cancel.text().replace("&", "") != "Cancel"
    dialog.reject()


def test_qt_translator_replaced_on_locale_change(qtbot: QtBot, tmp_path: Path) -> None:
    """German native buttons use qtbase; rebuilding in English removes the old translator."""
    paths = AppPaths(tmp_path, tmp_path / "data", tmp_path / "logs", tmp_path / "snaps", False)
    for language, expected in (("de", "Abbrechen"), ("en_US", "Cancel")):
        build_app([], paths, Settings(locale=language))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        qtbot.addWidget(buttons)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        assert cancel is not None and cancel.text().replace("&", "") == expected
        buttons.close()


@pytest.mark.parametrize("language", ["en_US", "ar", "de"])
def test_locale_formats_dates_counts_and_exact_sizes(language: str, tmp_path: Path) -> None:
    """Qt supplies number/date conventions; byte digits remain exact above float precision."""
    setup(language)
    QLocale.setDefault(QLocale(language))
    root, stamp, size = tmp_path / "tree", 1_700_000_000, (1 << 64) - 1
    tree = api.scan(
        api.ScanRequest([root]),
        backend=make_mock_backend(
            MockSpec(
                [
                    MockEntry(root, api.EntryKind.DIR),
                    MockEntry(root / "file", size=size),
                ]
            )
        ),
    ).tree
    columns = [ColumnId.FILES, ColumnId.MTIME, ColumnId.SIZE]
    model = TreeTableModel(api.TreeView(tree), columns)
    model.unit_mode = api.UnitMode.BYTES
    locale = QLocale()
    assert model.index(0, 0).data() == locale.toString(1)
    child = model.view.tree.find_path(root / "file")
    assert child is not None
    dated = tmp_path / "dated"
    dated.mkdir()
    path = dated / "file"
    path.write_bytes(b"date")
    os.utime(path, (stamp, stamp))
    dated_model = TreeTableModel(api.TreeView(api.scan(api.ScanRequest([dated])).tree), columns)
    assert dated_model.index(1, 1).data() == locale.toString(
        QDateTime.fromSecsSinceEpoch(stamp), QLocale.FormatType.ShortFormat
    )
    digits = "".join(locale.toString(int(digit)) for digit in str(size))
    assert model.index(0, 2).data() == digits + " B"
    assert _format_size(1024, api.UnitMode.AUTO, api.UnitStyle()) == (
        locale.toString(1) + locale.decimalPoint() + locale.toString(0) + " KB"
    )
    assert elapsed_text(1000).endswith(locale.toString(1))
    model.deleteLater()
    dated_model.deleteLater()


def test_no_untranslated_literals() -> None:
    """Audit literal UI text in every GUI source file, including nested text expressions."""
    root = Path(__file__).parents[2] / "src" / "dafree" / "gui"
    failures = []
    for path in sorted(root.rglob("*.py")):
        failures.extend(
            f"{path.relative_to(root)}:{line}: {text!r}"
            for line, text in _literal_violations(path.read_text(encoding="utf8"))
        )
    assert not failures, "Untranslated GUI literals:\n" + "\n".join(failures)


def test_literal_audit_rejects_nested_and_keyword_text() -> None:
    """Wrapping in a formatting or display helper cannot hide untranslated UI prose."""
    assert _literal_violations('QLabel("Hello"); action.setText(text="World")') == [
        (1, "Hello"),
        (1, "World"),
    ]
    assert _literal_violations('label.setToolTip(_display_text("Hello"))') == [(1, "Hello")]
    assert _literal_violations('label.setText(locale.toString("Hello"))') == [(1, "Hello")]
    assert not _literal_violations('QLabel(_("Hello")); label.setText("—")')
