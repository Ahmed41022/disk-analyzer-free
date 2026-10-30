"""Python package for Disk Analyzer Free."""

import os
import sys

_python_dll_directory = os.add_dll_directory(sys.base_prefix) if sys.platform == "win32" else None

from .api import __version__  # noqa: E402

__all__ = ["__version__"]
