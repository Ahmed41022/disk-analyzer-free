"""MockBackend-free fixture sizes and paths cross the public/native boundary."""

from pathlib import Path

import pytest

from dafree import api
from dafree.api.testing import TreeBuilder


@pytest.mark.parametrize("rows", [1, 2, 701])
def test_flat_native_builder_has_exact_visible_rows(tmp_path: Path, rows: int) -> None:
    """Fixture construction touches no file and returns a normal owned native tree."""
    root = tmp_path / "synthetic"
    tree = TreeBuilder.flat(root, rows)
    view = api.TreeView(tree)
    assert view.row_count == rows
    assert len(tree) == rows + 1  # The synthetic root is not visible.
    assert tree.path(tree.roots()[0]) == str(root)
    assert tree.node(tree.roots()[0]).files == rows - 1
    assert tree.node(tree.roots()[0]).size == sum(range(rows))
    if rows > 1:
        assert view.rows(1, 1)[0][4:7] == ("file0.bin", rows - 1, rows - 1)
        assert view.rows(rows - 1, 1)[0][5] == 1
    assert not root.exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("rows", [-1, 0, (1 << 32) - 1, 1 << 100])
def test_flat_native_builder_rejects_invalid_sizes(tmp_path: Path, rows: int) -> None:
    """Reject empty/overflowing shapes before narrowing or allocating native storage."""
    with pytest.raises(ValueError, match="visible row count"):
        TreeBuilder.flat(tmp_path / "synthetic", rows)
