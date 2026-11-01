"""Desktop interface package."""


def _display_text(value: str) -> str:
    """Escape native surrogate code points that Qt's QString transport would truncate."""
    return value.encode("utf-8", errors="backslashreplace").decode("utf-8")


def _copy_text(text: str, formats: dict[str, bytes]) -> None:
    """Copy text and supplemental raw data using Qt-owned clipboard storage.

    Transferring a Python-created QMimeData crashes at shutdown in the observed
    Windows offscreen Qt runtime. Qt-created data avoids that ownership path.
    """
    from PySide6.QtWidgets import QApplication  # noqa: PLC0415 -- Qt remains an optional runtime.

    clipboard = QApplication.clipboard()
    clipboard.setText(text)
    mime = clipboard.mimeData()
    for name, payload in formats.items():
        mime.setData(name, payload)
