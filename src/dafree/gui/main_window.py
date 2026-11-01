"""Main desktop window."""

from PySide6.QtWidgets import QMainWindow

from dafree.i18n import _


class MainWindow(QMainWindow):
    """Top-level window for the desktop interface."""

    def __init__(self) -> None:
        """Create the initial application window."""
        super().__init__()
        # Keep native launch arguments in Python; QVariant string lists can
        # truncate surrogate characters before later actions consume them.
        self._pending_launch_arguments: list[str] = []
        self.setWindowTitle(_("Disk Analyzer Free"))
        self.resize(960, 640)


def create_main_window() -> MainWindow:
    """Create a fresh, configured main window."""
    return MainWindow()
