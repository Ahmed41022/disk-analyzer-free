"""Python package for Disk Analyzer Free."""

import os
import sys
from collections.abc import Callable
from typing import cast

if sys.platform == "win32":
    _dll_directory_attribute = "add_dll_directory"
    _add_dll_directory = cast(
        Callable[[str], object],
        getattr(os, _dll_directory_attribute),
    )
    _python_dll_directory = _add_dll_directory(sys.base_prefix)
else:
    _python_dll_directory = None

from .api import __version__

__all__ = ["__version__"]
