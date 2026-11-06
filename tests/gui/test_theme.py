"""Theme controller tests for committed and system-following palettes."""

import os
from collections.abc import Iterator
from importlib.util import find_spec

import pytest

if find_spec("PySide6") is None:
    if os.environ.get("DAFREE_REQUIRE_GUI") == "1":
        pytest.fail("PySide6 is required when DAFREE_REQUIRE_GUI=1", pytrace=False)
    pytest.skip("PySide6 is not installed", allow_module_level=True)

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

from dafree.gui.theme.palette import Theme, ThemeController, apply_palette

pytestmark = pytest.mark.gui


@pytest.fixture
def theme_app(qapp: QApplication) -> Iterator[QApplication]:
    """Restore the process-wide Qt palette and stylesheet after each test."""
    palette, stylesheet = qapp.palette(), qapp.styleSheet()
    yield qapp
    qapp.setPalette(palette)
    qapp.setStyleSheet(stylesheet)


def _is_dark(app: QApplication) -> bool:
    return app.palette().color(QPalette.ColorRole.Window).name() == "#23262b"


def test_system_theme_follows_signal_argument(theme_app: QApplication) -> None:
    """Use the signal value even when the style hint property has not changed."""
    apply_palette(theme_app, "light")
    controller = ThemeController(theme_app, "system")
    try:
        theme_app.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Dark)
        assert _is_dark(theme_app)
        theme_app.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Light)
        assert not _is_dark(theme_app)
    finally:
        controller.close()


@pytest.mark.parametrize("theme,expected_dark", [("light", False), ("dark", True)])
def test_fixed_theme_ignores_system_signal_and_remembers_it(
    theme_app: QApplication, theme: Theme, expected_dark: bool
) -> None:
    """Keep an explicit palette while recording the latest OS scheme for later."""
    apply_palette(theme_app, theme)
    controller = ThemeController(theme_app, theme)
    try:
        theme_app.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Dark)
        assert _is_dark(theme_app) is expected_dark
        controller.set_theme("system")
        assert _is_dark(theme_app)
    finally:
        controller.close()


def test_close_disconnects_system_signal(theme_app: QApplication) -> None:
    """Closing the controller prevents subsequent OS changes from applying."""
    apply_palette(theme_app, "light")
    controller = ThemeController(theme_app, "system")
    controller.close()
    controller.close()
    theme_app.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Dark)
    assert not _is_dark(theme_app)


def test_constructor_preserves_already_applied_palette(theme_app: QApplication) -> None:
    """Observing an existing application never changes its palette until a committed choice."""
    apply_palette(theme_app, "light")
    controller = ThemeController(theme_app, "dark")
    try:
        assert not _is_dark(theme_app)
        controller.set_theme("dark")
        assert _is_dark(theme_app)
    finally:
        controller.close()
