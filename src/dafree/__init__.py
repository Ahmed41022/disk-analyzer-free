"""Python package for Disk Analyzer Free."""

import os
import sys

_python_dll_directory = (
    os.add_dll_directory(sys.base_prefix) if sys.platform == "win32" else None
)

from . import _core as _core  # type: ignore[attr-defined]

__version__ = _core.version()

__all__ = ["__version__"]
