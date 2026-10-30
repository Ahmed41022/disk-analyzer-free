"""Main desktop window."""

from PySide6.QtWidgets import QMainWindow


class MainWindow(QMainWindow):
    """Top-level window for the desktop interface."""

    def __init__(self) -> None:
        """Create the initial application window."""
        super().__init__()
        self.setWindowTitle("Disk Analyzer Free")
        self.resize(960, 640)


def create_main_window() -> MainWindow:
    """Create a fresh, configured main window."""
    return MainWindow()
