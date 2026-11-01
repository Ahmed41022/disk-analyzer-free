"""Desktop interface package."""


def _display_text(value: str) -> str:
    """Escape native surrogate code points that Qt's QString transport would truncate."""
    return value.encode("utf-8", errors="backslashreplace").decode("utf-8")
