"""Public treemap facade contracts."""

# ruff: noqa: PLR2004 -- fixed binary layout and image dimensions are contract values.

import gc
from pathlib import Path

import numpy as np
import pytest

from dafree.api import (
    Palette,
    TmFlags,
    Tree,
    TreemapLayout,
    TreemapOptions,
    treemap_layout,
    treemap_render,
)
from dafree.api.testing import TreeBuilder


def make_tree(tmp_path: Path) -> Tree:
    return TreeBuilder.flat(tmp_path, 12)


def test_rects_are_readonly_zero_copy_and_keep_layout_alive(tmp_path: Path) -> None:
    tree = make_tree(tmp_path)
    treemap = treemap_layout(tree, tree.roots()[0], 128, 96)
    rects = treemap.rects
    raw_rects = treemap._native.raw_rects
    assert raw_rects.dtype == np.dtype("u1")
    assert rects.dtype.itemsize == 24
    assert rects.dtype.names == ("x", "y", "w", "h", "node", "depth", "cls", "flags", "pad")
    assert [rects.dtype.fields[name][1] for name in rects.dtype.names] == [
        0,
        4,
        8,
        12,
        16,
        20,
        21,
        22,
        23,
    ]
    assert not rects.flags.writeable
    with pytest.raises(ValueError):
        rects.setflags(write=True)
    assert np.shares_memory(rects, raw_rects)
    before = rects.copy()
    del treemap, tree, raw_rects
    gc.collect()
    assert np.array_equal(rects, before)


def test_layout_geometry_hit_test_and_repeat_render(tmp_path: Path) -> None:
    tree = make_tree(tmp_path)
    options = TreemapOptions()
    options.max_rects = 8
    treemap: TreemapLayout = treemap_layout(tree, tree.roots()[0], 64, 40, options)
    assert len(treemap.rects) <= 8
    assert treemap.width == 64
    assert treemap.height == 40
    root_id = tree.roots()[0]
    rects = treemap.rects
    assert treemap.hit_test(0.25, 0.25) == root_id
    leaf_rects = rects[
        (rects["flags"] & int(TmFlags.DIRECTORY) == 0) & (rects["flags"] & int(TmFlags.OTHER) == 0)
    ]
    leaf = leaf_rects[0]
    assert treemap.hit_test(
        float(leaf["x"] + leaf["w"] / 2), float(leaf["y"] + leaf["h"] / 2)
    ) == int(leaf["node"])
    assert treemap.hit_test(-1, -1) is None
    assert treemap.hit_test(treemap.width, treemap.height) is None
    palette = Palette()
    palette.by_class = [0x123456FF] * 16
    palette.dir_by_depth = [0xABCDEFFF] * 8
    palette.background = 0x010203FF
    palette.border = 0xFFFFFFFF
    first = treemap_render(treemap, palette, False)
    assert isinstance(first, bytes)
    assert len(first) == 64 * 40 * 4
    assert treemap_render(treemap, palette, False) == first


def test_zero_geometry_returns_empty_layout(tmp_path: Path) -> None:
    tree = make_tree(tmp_path)
    treemap = treemap_layout(tree, tree.roots()[0], 0, 10)
    assert treemap.width == 0
    assert treemap.height == 10
    assert len(treemap.rects) == 0
    assert treemap_render(treemap, Palette()) == b""


def test_float_record_conversion_never_creates_overlapping_siblings(tmp_path: Path) -> None:
    """Check exact stored edges in double precision, without hiding subpixel overlaps."""
    tree = TreeBuilder.flat(tmp_path, 201)
    options = TreemapOptions()
    options.min_px = 0
    options.padding = 0
    options.max_depth = 1
    treemap = treemap_layout(tree, tree.roots()[0], 1234.567, 765.432, options)
    rects = treemap.rects[1:]
    left = rects["x"].astype(np.float64)
    top = rects["y"].astype(np.float64)
    right = left + rects["w"].astype(np.float64)
    bottom = top + rects["h"].astype(np.float64)
    horizontal = np.minimum(right[:, None], right[None, :]) > np.maximum(
        left[:, None], left[None, :]
    )
    vertical = np.minimum(bottom[:, None], bottom[None, :]) > np.maximum(top[:, None], top[None, :])
    assert not np.any(np.triu(horizontal & vertical, k=1))
    assert np.all(left >= 0) and np.all(top >= 0)
    assert np.all(right <= treemap.width) and np.all(bottom <= treemap.height)


@pytest.mark.parametrize(
    "width,height", [(-1, 10), (10, -1), (10, float("inf")), (10, float("nan"))]
)
def test_invalid_geometry_raises(tmp_path: Path, width: float, height: float) -> None:
    tree = make_tree(tmp_path)
    with pytest.raises(ValueError):
        treemap_layout(tree, tree.roots()[0], width, height)
