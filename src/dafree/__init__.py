"""Python package for Disk Analyzer Free."""

import os
import sys
from collections.abc import Callable
from typing import cast

_add_dll_directory = cast(
    Callable[[str], object] | None,
    getattr(os, "add_dll_directory", None),
)
_python_dll_directory = (
    _add_dll_directory(sys.base_prefix)
    if sys.platform == "win32" and _add_dll_directory is not None
    else None
)

from .api import __version__  # noqa: E402

__all__ = ["__version__"]
