"""Initial Fusion palettes; live theme switching belongs to deferred T4.10."""

from importlib.resources import files
from typing import Literal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def apply_palette(app: QApplication, theme: Literal["system", "light", "dark"]) -> None:
    """Apply the selected initial palette and the packaged, palette-based stylesheet."""
    dark = theme == "dark" or (
        theme == "system" and app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    )
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
    app.setPalette(palette)
    app.setStyleSheet(files("dafree.gui.theme").joinpath("style.qss").read_text(encoding="utf-8"))
