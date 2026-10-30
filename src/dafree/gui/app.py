"""Qt application startup."""

import sys


def main(argv: list[str] | None = None) -> int:
    """Create and run the desktop application."""
    # Load Qt only when the user launches the desktop interface.
    from PySide6.QtWidgets import QApplication  # noqa: PLC0415

    from dafree.gui.main_window import create_main_window  # noqa: PLC0415

    app = QApplication(argv if argv is not None else sys.argv)
    window = create_main_window()
    window.show()
    return app.exec()
