"""Typed Python access to native treemap layout and RGBA rendering."""

from __future__ import annotations

from enum import IntFlag
from functools import lru_cache
from typing import TYPE_CHECKING

from dafree import _core
from dafree.api.tree import Tree

if TYPE_CHECKING:
    import numpy as np

TreemapOptions = _core.TreemapOptions
Palette = _core.Palette


class TmFlags(IntFlag):
    """Flags stored in each rectangle's ``flags`` field."""

    OTHER = _core.TmFlags.OTHER.value
    DIRECTORY = _core.TmFlags.DIRECTORY.value


@lru_cache(maxsize=1)
def _rect_dtype() -> np.dtype[np.void]:
    """Return the fixed 24-byte native rectangle record dtype."""
    import numpy as np  # noqa: PLC0415 -- arrays alone need NumPy at runtime.

    names = ("x", "y", "w", "h", "node", "depth", "cls", "flags", "pad")
    formats = ("=f4", "=f4", "=f4", "=f4", "=u4", "u1", "u1", "u1", "u1")
    offsets = (0, 4, 8, 12, 16, 20, 21, 22, 23)
    return np.dtype({"names": names, "formats": formats, "offsets": offsets, "itemsize": 24})


class TreemapLayout:
    """Keep the native immutable layout alive with its zero-copy rectangle view."""

    def __init__(self, native: _core.TreemapLayout) -> None:
        self._native = native

    @property
    def rects(self) -> np.ndarray[tuple[int], np.dtype[np.void]]:
        """Read-only zero-copy records with x/y/w/h/node/depth/cls/flags/pad fields."""
        import numpy as np  # noqa: PLC0415 -- keep CLI/GUI startup free of array imports.

        return np.frombuffer(self._native.raw_rects, dtype=_rect_dtype())

    @property
    def width(self) -> float:
        """Requested layout width in device pixels."""
        return self._native.width

    @property
    def height(self) -> float:
        """Requested layout height in device pixels."""
        return self._native.height

    def small_items(self, index: int) -> int:
        """Return the number of nodes grouped into an OTHER rectangle."""
        return self._native.small_items(index)

    def hit_test(self, x: float, y: float) -> int | None:
        """Return the smallest real node containing a point, or None."""
        return self._native.hit_test(x, y)


def treemap_layout(
    tree: Tree,
    root: int,
    width: float,
    height: float,
    options: TreemapOptions | None = None,
) -> TreemapLayout:
    """Compute a native squarified layout for a tree subtree."""
    native_options = TreemapOptions() if options is None else options
    return TreemapLayout(_core.treemap_layout(tree._native, root, width, height, native_options))


def treemap_render(treemap: TreemapLayout, palette: Palette, cushion: bool = True) -> bytes:
    """Render a layout as RGBA8888 bytes, using the layout's ceiling dimensions."""
    return _core.treemap_render(treemap._native, palette, cushion)


__all__ = [
    "Palette",
    "TmFlags",
    "TreemapLayout",
    "TreemapOptions",
    "treemap_layout",
    "treemap_render",
]
