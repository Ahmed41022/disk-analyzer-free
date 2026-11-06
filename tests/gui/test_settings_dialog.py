"""Preference transactions, live theme tracking, and cached presentation updates."""

# ruff: noqa: PLR2004 -- exact byte limits, fixed row heights, and fixture sizes are contracts.

import os
from collections.abc import Callable, Iterator
from copy import deepcopy
from importlib.util import find_spec
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

if find_spec("PySide6") is None:
    if os.environ.get("DAFREE_REQUIRE_GUI") == "1":
        pytest.fail("PySide6 is required when DAFREE_REQUIRE_GUI=1", pytrace=False)
    pytest.skip("PySide6 is not installed", allow_module_level=True)

from PySide6.QtCore import QCoreApplication, QEvent, QLocale, Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QDialog, QLabel

from dafree import api
from dafree.api.testing import TreeBuilder
from dafree.gui.dialogs import settings_dialog as module
from dafree.gui.dialogs.settings_dialog import SettingsDialog
from dafree.gui.main_window import MainWindow
from dafree.gui.theme.palette import apply_palette
from dafree.i18n import current_locale, setup
from dafree.paths import AppPaths
from dafree.settings import (
    ColumnId,
    ColumnSetting,
    Settings,
    load_settings,
    save_settings,
    set_dotted,
    validate_settings,
)

pytestmark = pytest.mark.gui


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    """Keep configuration and every UI-owned path inside this test's temporary directory."""
    return AppPaths(
        tmp_path / "config", tmp_path / "data", tmp_path / "logs", tmp_path / "snapshots", False
    )


@pytest.fixture(autouse=True)
def restore_application(qapp: QApplication) -> Iterator[None]:
    """Undo process-wide presentation state only after controllers have disconnected."""
    palette, stylesheet = qapp.palette(), qapp.styleSheet()
    locale, qt_locale = current_locale(), QLocale()
    setup("en_US")
    QLocale.setDefault(QLocale("en_US"))
    apply_palette(qapp, "light")
    yield
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    setup(locale)
    QLocale.setDefault(qt_locale)
    qapp.setPalette(palette)
    qapp.setStyleSheet(stylesheet)


@pytest.fixture
def make_dialog(qtbot: QtBot, paths: AppPaths) -> Iterator[Callable[..., SettingsDialog]]:
    """Retire each standalone dialog's observer before restoring global Qt state."""
    dialogs: list[SettingsDialog] = []

    def create(settings: Settings | None = None) -> SettingsDialog:
        dialog = SettingsDialog(settings if settings is not None else Settings(), paths=paths)
        dialogs.append(dialog)
        qtbot.addWidget(dialog)
        dialog.show()
        return dialog

    yield create
    for dialog in dialogs:
        dialog._theme_controller.close()


def test_theme_change_applies_palette(make_dialog, qapp: QApplication) -> None:
    """Commit an explicit theme after OK, with no draft palette preview."""
    settings = Settings(theme="light")
    dialog = make_dialog(settings)
    before = qapp.palette()
    dialog.theme.setCurrentIndex(dialog.theme.findData("dark"))
    assert qapp.palette() == before
    assert settings.theme == "light"
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert settings.theme == "dark"
    assert qapp.palette().color(QPalette.ColorRole.Window).name() == "#23262b"


def test_settings_saved_on_ok_not_on_cancel(
    make_dialog, paths: AppPaths, qapp: QApplication
) -> None:
    """Cancellation preserves original bytes and nested settings; OK persists one candidate."""
    settings = Settings(theme="light")
    save_settings(settings, paths)
    original = deepcopy(settings)
    before = (paths.config / "settings.json").read_bytes()
    palette = qapp.palette()
    canceled = make_dialog(settings)
    canceled.theme.setCurrentIndex(canceled.theme.findData("dark"))
    canceled.follow_symlinks.setChecked(True)
    canceled.density.setCurrentIndex(canceled.density.findData("comfortable"))
    canceled.reject()
    assert settings == original
    assert (paths.config / "settings.json").read_bytes() == before
    assert qapp.palette() == palette
    accepted = make_dialog(settings)
    accepted.theme.setCurrentIndex(accepted.theme.findData("dark"))
    accepted.follow_symlinks.setChecked(True)
    accepted.density.setCurrentIndex(accepted.density.findData("comfortable"))
    accepted.accept()
    assert settings.default_scan.follow_symlinks
    assert settings.row_density == "comfortable"
    assert load_settings(paths) == settings


def test_system_theme_follows_color_scheme_signal(make_dialog, qapp: QApplication) -> None:
    """Committed System observes native hints; fixed themes keep their explicit palette."""
    dialog = make_dialog(Settings(theme="system"))
    dialog.accept()
    qapp.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Dark)
    assert qapp.palette().color(QPalette.ColorRole.Window).name() == "#23262b"
    qapp.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Light)
    assert qapp.palette().color(QPalette.ColorRole.Window).name() == "#f2f4f7"
    dialog._theme_controller.set_theme("dark")
    qapp.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Light)
    assert qapp.palette().color(QPalette.ColorRole.Window).name() == "#23262b"


def test_failed_save_keeps_dialog_open_and_live_state_unchanged(
    make_dialog, paths: AppPaths, monkeypatch, qapp: QApplication
) -> None:
    """A disk error must not commit draft values or a theme whose persistence failed."""
    settings = Settings(theme="light")
    save_settings(settings, paths)
    previous = deepcopy(settings)
    old_bytes = (paths.config / "settings.json").read_bytes()
    palette = qapp.palette()
    dialog = make_dialog(settings)
    dialog.theme.setCurrentIndex(dialog.theme.findData("dark"))

    def denied(candidate, destination) -> None:
        raise OSError("read-only-test")

    monkeypatch.setattr(module, "save_settings", denied)
    dialog.accept()
    assert dialog.isVisible()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert "read-only-test" in dialog.error.text()
    assert settings == previous
    assert (paths.config / "settings.json").read_bytes() == old_bytes
    assert qapp.palette() == palette


def test_invalid_duplicate_sizes_cannot_commit(make_dialog, paths: AppPaths) -> None:
    """Validate the final min/max relationship before any persistence or live mutation."""
    settings = Settings()
    dialog = make_dialog(settings)
    dialog.min_size.setText("2GiB")
    dialog.max_size.setText("1GiB")
    dialog.accept()
    assert dialog.isVisible()
    assert dialog.error.text()
    assert settings == Settings()
    assert not (paths.config / "settings.json").exists()


def test_language_change_requires_restart(make_dialog, paths: AppPaths, qapp: QApplication) -> None:
    """Persist the next launch's language without changing current gettext or Qt locale."""
    settings = Settings(locale="en_US")
    dialog = make_dialog(settings)
    direction = qapp.layoutDirection()
    dialog.language.setCurrentIndex(dialog.language.findData("ar"))
    assert any("restarting" in label.text() for label in dialog.findChildren(QLabel))
    dialog.accept()
    assert settings.locale == load_settings(paths).locale == "ar"
    assert current_locale() == "en_US"
    assert QLocale().name() == "en_US"
    assert qapp.layoutDirection() == direction


@pytest.mark.parametrize("language", ["future_LOCALE", "invalid-\ud800"])
def test_preferences_preserve_unrelated_live_updates_and_raw_text(
    make_dialog, paths: AppPaths, language
) -> None:
    """Worker updates and lossless filesystem strings survive an unrelated preference edit."""
    settings = Settings(locale=language)
    settings.default_scan.exclude.paths = ["bad-\ud800", "line\r\nbreak"]
    settings.default_scan.exclude.globs = ["*bad-\udfff*"]
    settings.dupes.filter = "name-\ud800"
    dialog = make_dialog(settings)
    settings.recent_targets = [str(paths.data / "recent")]
    settings.default_scan.targets = [str(paths.data / "target")]
    settings.columns[0].width = 444
    dialog.theme.setCurrentIndex(dialog.theme.findData("dark"))
    dialog.accept()
    assert settings.recent_targets == [str(paths.data / "recent")]
    assert settings.default_scan.targets == [str(paths.data / "target")]
    assert settings.columns[0].width == 444
    assert settings.locale == language
    assert settings.default_scan.exclude.paths == ["bad-\ud800", "line\r\nbreak"]
    assert settings.default_scan.exclude.globs == ["*bad-\udfff*"]
    assert settings.dupes.filter == "name-\ud800"
    assert load_settings(paths) == settings


def test_duplicate_uint64_values_are_exact(make_dialog, paths: AppPaths) -> None:
    """Text byte values preserve integers beyond QDoubleSpinBox's exact integer range."""
    settings = Settings()
    dialog = make_dialog(settings)
    minimum, maximum = (1 << 53) + 1, (1 << 64) - 1
    dialog.min_size.setText(str(minimum))
    dialog.max_size.setText(str(maximum))
    dialog.partial_bytes.setValue((1 << 32) - 1)
    dialog.io_threads.setValue((1 << 32) - 1)
    dialog.accept()
    loaded = load_settings(paths)
    assert loaded.dupes.min_size == minimum
    assert loaded.dupes.max_size == maximum
    assert loaded.dupes.partial_bytes == loaded.dupes.io_threads == (1 << 32) - 1


def test_windows_defaults_preserved_on_other_platforms(make_dialog, monkeypatch) -> None:
    """Disabled platform-specific controls never erase a shared Windows configuration."""
    monkeypatch.setattr(module, "_WINDOWS", False)
    settings = Settings()
    settings.default_scan.mode = api.ScanMode.MFT
    settings.default_scan.include_ads = True
    settings.default_scan.show_ntfs_metafiles = False
    dialog = make_dialog(settings)
    assert not dialog.metafiles.isEnabled() and not dialog.include_ads.isEnabled()
    dialog.accept()
    assert settings.default_scan.mode == api.ScanMode.MFT
    assert settings.default_scan.include_ads
    assert not settings.default_scan.show_ntfs_metafiles
    assert settings.show_ntfs_metafiles


def test_windows_metafile_choice_updates_scan_default(make_dialog, monkeypatch) -> None:
    """The Advanced preference must affect the scan request's persisted default too."""
    monkeypatch.setattr(module, "_WINDOWS", True)
    settings = Settings()
    dialog = make_dialog(settings)
    dialog.metafiles.setChecked(False)
    dialog.include_ads.setChecked(True)
    dialog.accept()
    assert not settings.show_ntfs_metafiles
    assert not settings.default_scan.show_ntfs_metafiles
    assert settings.default_scan.include_ads


def test_open_logs_requires_existing_directory(make_dialog, paths: AppPaths, monkeypatch) -> None:
    """The explicit folder button opens only its known path and never creates a folder."""
    dialog = make_dialog()
    opened = []
    monkeypatch.setattr(module.QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    dialog.log_folder.click()
    assert not opened
    assert not paths.logs.exists()
    assert dialog.error.text()
    paths.logs.mkdir()
    dialog.log_folder.click()
    assert Path(opened[0].toLocalFile()) == paths.logs
    assert not dialog.error.text()


def test_row_density_validation_backfills_old_files(paths: AppPaths) -> None:
    """Old schemas retain compact defaults and new values use the existing strict decoder."""
    paths.config.mkdir()
    (paths.config / "settings.json").write_text('{"version":1}', encoding="utf-8")
    settings = load_settings(paths)
    assert settings.row_density == "compact"
    comfortable = set_dotted(settings, "row_density", '"comfortable"')
    assert comfortable.row_density == "comfortable"
    assert settings.row_density == "compact"
    with pytest.raises(ValueError):
        set_dotted(settings, "row_density", '"huge"')
    normalized = validate_settings(settings)
    normalized.default_scan.targets.append("independent")
    assert not settings.default_scan.targets


def test_density_keeps_legacy_settings_constructor_order() -> None:
    """Appending the new preference must not reinterpret positional column arguments."""
    columns = [ColumnSetting(ColumnId.NAME)]
    settings = Settings(1, "light", None, api.UnitMode.AUTO, api.UnitStyle(), columns)
    assert settings.columns == columns
    assert settings.row_density == "compact"


def test_main_window_settings_refresh_cached_table(qtbot: QtBot, tmp_path: Path) -> None:
    """The live table picks up formatting/density without native refetches or loss of selection."""
    window = MainWindow(volume_provider=lambda: [])

    def finish(widget) -> None:
        window.close()
        qtbot.waitUntil(lambda: not window.runner.busy and not window.controller.running)

    qtbot.addWidget(window, before_close_func=finish)
    window.show()
    window._tree_ready(TreeBuilder.flat(tmp_path / "synthetic", 20))
    page = window._pages["tree"]
    qtbot.waitUntil(lambda: page.table is not None)
    table = page.table
    model = table.tree_model
    index = model.index(0, 0)
    selected = model.node_at(table.currentIndex().row())
    assert index.data()
    rows = model.view.rows

    def no_fetch(start: int, count: int):
        pytest.fail("Applying settings must retain the native row cache")

    model.view.rows = no_fetch
    try:
        window.settings_action.trigger()
        dialog = window._settings_dialog
        assert dialog is not None and dialog.isVisible()
        window.open_settings()
        assert window._settings_dialog is dialog
        dialog.units.setCurrentIndex(dialog.units.findData(api.UnitMode.BYTES))
        dialog.unit_system.setCurrentIndex(dialog.unit_system.findData(api.UnitSystem.IEC))
        dialog.density.setCurrentIndex(dialog.density.findData("comfortable"))
        dialog.accept()
        assert window._settings_dialog is None
        assert model.unit_mode == api.UnitMode.BYTES
        assert model.unit_style.system == api.UnitSystem.IEC
        assert table.verticalHeader().defaultSectionSize() == 32
        assert model.node_at(table.currentIndex().row()) == selected
        assert window.units.currentData() == api.UnitMode.BYTES
        qtbot.wait(30)
    finally:
        model.view.rows = rows
