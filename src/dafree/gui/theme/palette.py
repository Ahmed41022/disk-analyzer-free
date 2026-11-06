"""Fusion palettes and live system-theme tracking."""

from importlib.resources import files
from typing import Literal

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

Theme = Literal["system", "light", "dark"]


def _set_palette(app: QApplication, dark: bool) -> None:
    """Apply a light or dark palette and the packaged stylesheet only when needed."""
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: ("#23262b", "#f2f4f7"),
        QPalette.ColorRole.WindowText: ("#edf0f2", "#20242a"),
        QPalette.ColorRole.Base: ("#1c1f24", "#ffffff"),
        QPalette.ColorRole.AlternateBase: ("#292d34", "#edf0f5"),
        QPalette.ColorRole.Text: ("#edf0f2", "#20242a"),
        QPalette.ColorRole.Button: ("#30343c", "#e9edf3"),
        QPalette.ColorRole.ButtonText: ("#edf0f2", "#20242a"),
        QPalette.ColorRole.Highlight: ("#3d77b5", "#326fae"),
        QPalette.ColorRole.HighlightedText: ("#ffffff", "#ffffff"),
        QPalette.ColorRole.ToolTipBase: ("#30343c", "#ffffff"),
        QPalette.ColorRole.ToolTipText: ("#edf0f2", "#20242a"),
        QPalette.ColorRole.PlaceholderText: ("#aeb8c4", "#66717e"),
        QPalette.ColorRole.Link: ("#7ab7f4", "#225f9f"),
    }
    for role, (dark_color, light_color) in colors.items():
        palette.setColor(role, QColor(dark_color if dark else light_color))
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.WindowText,
    ):
        palette.setColor(
            QPalette.ColorGroup.Disabled, role, QColor("#77808b" if dark else "#89929e")
        )
    if app.palette() != palette:
        app.setPalette(palette)
    stylesheet = files("dafree.gui.theme").joinpath("style.qss").read_text(encoding="utf-8")
    if app.styleSheet() != stylesheet:
        app.setStyleSheet(stylesheet)


def apply_palette(app: QApplication, theme: Theme) -> None:
    """Apply the selected palette and packaged, palette-based stylesheet."""
    dark = theme == "dark" or (
        theme == "system" and app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    )
    _set_palette(app, dark)


class ThemeController(QObject):
    """Apply committed theme choices and follow system color-scheme changes."""

    def __init__(
        self,
        app: QApplication,
        theme: Theme,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._app = app
        self._theme = theme
        self._scheme = app.styleHints().colorScheme()
        self._closed = False
        app.styleHints().colorSchemeChanged.connect(self._scheme_changed)

    def set_theme(self, theme: Theme) -> None:
        """Commit a theme selection and immediately apply its effective palette."""
        if self._closed:
            return
        self._theme = theme
        self._apply()

    def _scheme_changed(self, scheme: Qt.ColorScheme) -> None:
        if self._closed:
            return
        self._scheme = scheme
        if self._theme == "system":
            self._apply()

    def _apply(self) -> None:
        dark = self._theme == "dark" or (
            self._theme == "system" and self._scheme == Qt.ColorScheme.Dark
        )
        _set_palette(self._app, dark)

    def close(self) -> None:
        """Stop observing system theme changes; repeated calls are safe."""
        if self._closed:
            return
        self._closed = True
        self._app.styleHints().colorSchemeChanged.disconnect(self._scheme_changed)
