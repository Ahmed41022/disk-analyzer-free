"""Desktop interface package."""

from functools import lru_cache

from dafree import api


@lru_cache(maxsize=16)
def _number_translation(locale_name: str, separator: str) -> dict[int, str]:
    from PySide6.QtCore import QLocale  # noqa: PLC0415 -- optional GUI runtime.

    locale = QLocale(locale_name)
    digits = {str(i): locale.toString(i) for i in range(10)}
    digits[separator] = locale.decimalPoint() if separator == "." else separator
    return str.maketrans(digits)


def _format_size(value: int, mode: api.UnitMode, style: api.UnitStyle) -> str:
    """Localize native size digits without rounding its exact uint64 byte representation.

    Explicit non-default separators stay authoritative. Unit labels and filenames are
    never translated as numbers, and the CLI formatter remains locale-independent.
    """
    from PySide6.QtCore import QLocale  # noqa: PLC0415 -- optional GUI runtime.

    number, space, unit = api.format_size(value, mode, style).partition(" ")
    return (
        number.translate(_number_translation(QLocale().name(), style.decimal_separator))
        + space
        + unit
    )


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
