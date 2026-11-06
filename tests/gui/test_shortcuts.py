"""Shortcut defaults, focus scope, and transactional settings edits."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

if os.environ.get("DAFREE_REQUIRE_GUI") != "1":
    pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QWidget

from dafree.gui.dialogs.settings_dialog import SettingsDialog
from dafree.gui.main_window import MainWindow
from dafree.gui.shortcuts import ShortcutRegistry, shortcut_specs
from dafree.i18n import current_locale, setup
from dafree.paths import AppPaths
from dafree.settings import Settings, load_settings

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def english_catalogue() -> Iterator[None]:
    """Keep shortcut labels and dialog captions stable across GUI tests."""
    previous = current_locale()
    setup("en_US")
    yield
    setup(previous)


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    """Confine all persisted settings and application paths to the test directory."""
    return AppPaths(
        tmp_path / "config", tmp_path / "data", tmp_path / "logs", tmp_path / "snapshots", False
    )


def test_default_shortcuts_trigger_actions(qtbot: QtBot) -> None:
    """Every registered default triggers its handler from a shown window."""
    window = QWidget()
    qtbot.addWidget(window)
    window.show()
    registry = ShortcutRegistry(window)
    triggered: list[str] = []

    for spec in shortcut_specs():
        registry.register(spec.id, window, lambda action_id=spec.id: triggered.append(action_id))

    registry.apply({})
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    for spec in shortcut_specs():
        qtbot.keySequence(window, spec.default)
        assert triggered[-1] == spec.id


def test_scoped_cancel_shortcut_only_triggers_from_progress(qtbot: QtBot) -> None:
    """Escape cancels from the progress panel, not from an unrelated query field."""
    window = QWidget()
    query = QLineEdit(window)
    progress = QWidget(window)
    progress.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    query.setGeometry(0, 0, 200, 30)
    progress.setGeometry(0, 40, 200, 30)
    qtbot.addWidget(window)
    window.show()
    registry = ShortcutRegistry(window)
    calls: list[str] = []
    registry.register("cancel_scan", progress, lambda: calls.append("cancel"), scoped=True)
    registry.apply({})
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)

    query.setFocus()
    qtbot.keySequence(query, QKeySequence("Esc"))
    assert calls == []

    progress.setFocus()
    qtbot.keySequence(progress, QKeySequence("Esc"))
    assert calls == ["cancel"]


def test_override_persists(qtbot: QtBot, paths: AppPaths) -> None:
    """OK saves an edited sequence while retaining IDs from newer settings schemas."""
    settings = Settings(shortcuts={"future_action": "Ctrl+Alt+F"})
    dialog = SettingsDialog(settings, paths=paths)
    qtbot.addWidget(dialog, before_close_func=lambda widget: dialog._theme_controller.close())
    dialog.show()

    dialog.shortcut_edits["new_scan"].setKeySequence(QKeySequence("Ctrl+Alt+N"))
    dialog.accept()

    assert dialog.result() == QDialog.DialogCode.Accepted
    saved = load_settings(paths)
    assert saved.shortcuts["new_scan"] == "Ctrl+Alt+N"
    assert saved.shortcuts["future_action"] == "Ctrl+Alt+F"


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Ctrl+Alt+N", "Ctrl+Alt+N"),
        ("Ctrl+K", "Ctrl+K, Ctrl+C"),
    ],
    ids=["exact", "prefix"],
)
def test_conflict_reported(qtbot: QtBot, paths: AppPaths, first: str, second: str) -> None:
    """Exact and multi-chord prefix conflicts block the transaction with an explanation."""
    settings = Settings()
    dialog = SettingsDialog(settings, paths=paths)
    qtbot.addWidget(dialog, before_close_func=lambda widget: dialog._theme_controller.close())
    dialog.show()
    dialog.shortcut_edits["new_scan"].setKeySequence(QKeySequence(first))
    dialog.shortcut_edits["refresh_selection"].setKeySequence(QKeySequence(second))

    dialog.accept()

    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.shortcut_error.text()
    assert settings.shortcuts == {}
    assert not paths.config.exists()


def test_cancel_and_empty_override(qtbot: QtBot, paths: AppPaths) -> None:
    """Cancel writes nothing; an explicitly cleared shortcut persists as unassigned."""
    cancelled = SettingsDialog(Settings(), paths=paths)
    qtbot.addWidget(cancelled, before_close_func=lambda widget: cancelled._theme_controller.close())
    cancelled.show()
    cancelled.shortcut_edits["new_scan"].setKeySequence(QKeySequence("Ctrl+Alt+N"))
    cancelled.reject()
    assert cancelled.result() == QDialog.DialogCode.Rejected
    assert not paths.config.exists()

    settings = Settings(shortcuts={"new_scan": "Ctrl+Alt+N"})
    dialog = SettingsDialog(settings, paths=paths)
    qtbot.addWidget(dialog, before_close_func=lambda widget: dialog._theme_controller.close())
    dialog.show()
    dialog.shortcut_edits["new_scan"].clear()
    dialog.accept()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert load_settings(paths).shortcuts["new_scan"] == ""


def test_overrides_replace_bindings_and_conflicts_disable_both(qtbot: QtBot) -> None:
    """Rebinding removes the old key, suppresses ambiguity, and permits restoring defaults."""
    window = QWidget()
    qtbot.addWidget(window)
    window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    registry = ShortcutRegistry(window)
    calls = []
    registry.register("new_scan", window, lambda: calls.append("new"))
    registry.register("focus_query", window, lambda: calls.append("find"))
    registry.apply({"new_scan": "Ctrl+Alt+N"})
    qtbot.keySequence(window, QKeySequence("Ctrl+N"))
    assert calls == []
    qtbot.keySequence(window, QKeySequence("Ctrl+Alt+N"))
    assert calls == ["new"]
    registry.apply({"new_scan": "Ctrl+F"})
    assert registry.actions["new_scan"].shortcut().isEmpty()
    assert registry.actions["focus_query"].shortcut().isEmpty()
    registry.apply({})
    qtbot.keySequence(window, QKeySequence(QKeySequence.StandardKey.Find))
    assert calls == ["new", "find"]


def test_main_window_shortcuts_respect_focus_and_deferred_features(qtbot: QtBot) -> None:
    """Real window wiring focuses search, preserves text copy, and scopes scan cancellation."""
    window = MainWindow(volume_provider=lambda: [])

    def finish(widget) -> None:
        window.close()
        qtbot.waitUntil(lambda: not window.runner.busy and not window.controller.running)

    qtbot.addWidget(window, before_close_func=finish)
    window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    qtbot.keySequence(window, QKeySequence("Ctrl+F"))
    assert window.query_edit.hasFocus()
    window.query_edit.setText("copy this")
    window.query_edit.selectAll()
    qtbot.keySequence(window.query_edit, QKeySequence(QKeySequence.StandardKey.Copy))
    assert window.query_edit.selectedText() == "copy this"
    assert QApplication.clipboard().text() == "copy this"
    for key in (
        "delete_trash",
        "delete_permanently",
        "copy_path",
        "save_snapshot",
        "open_snapshot",
        "export",
        "refresh_selection",
    ):
        assert not window.shortcuts.actions[key].isEnabled()
    calls = []
    window.cancel.triggered.connect(lambda: calls.append("cancel"))
    window.cancel.setEnabled(True)
    window.progress_panel.show()
    qtbot.keySequence(window.query_edit, QKeySequence("Esc"))
    assert calls == []
    window.progress_panel.setFocus()
    qtbot.keySequence(window.progress_panel, QKeySequence("Esc"))
    assert calls == ["cancel"]
