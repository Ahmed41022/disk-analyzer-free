"""Typed public facade over the native core."""

from dafree import _core

__version__ = _core.version()

__all__ = ["__version__"]
