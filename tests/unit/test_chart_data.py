"""Public chart-data facade contracts."""

from pathlib import Path

import pytest

from dafree.api import (
    ChartKind,
    ChartSlice,
    EntryKind,
    ExcludeRules,
    ScanRequest,
    analysis,
    chart_data,
    scan,
)
from dafree.api.testing import MockEntry, MockSpec, make_mock_backend


def make_chart_tree(tmp_path: Path):
    folder = tmp_path / "folder"
    backend = make_mock_backend(
        MockSpec(
            [
                MockEntry(tmp_path, EntryKind.DIR),
                MockEntry(folder, EntryKind.DIR),
                MockEntry(folder / "nested.jpg", size=20, alloc=16),
                MockEntry(tmp_path / "a.txt", size=10, alloc=8),
                MockEntry(tmp_path / "b.jpg", size=10, alloc=4),
                MockEntry(tmp_path / "c", size=5, alloc=0),
                MockEntry(tmp_path / "excluded.bin", size=100, alloc=100),
            ]
        )
    )
    return scan(
        ScanRequest([tmp_path], exclude=ExcludeRules(globs=["excluded.bin"])), backend=backend
    ).tree


def test_children_chart_kinds_use_direct_child_values(tmp_path: Path) -> None:
    tree = make_chart_tree(tmp_path)
    root = tree.roots()[0]
    size = chart_data(tree, root, ChartKind.CHILDREN_BY_SIZE, top=10)
    assert [(item.label, item.value, item.node) for item in size] == [
        ("folder", 20, next(i for i in tree.children(root) if tree.name(i) == "folder")),
        ("a.txt", 10, next(i for i in tree.children(root) if tree.name(i) == "a.txt")),
        ("b.jpg", 10, next(i for i in tree.children(root) if tree.name(i) == "b.jpg")),
        ("c", 5, next(i for i in tree.children(root) if tree.name(i) == "c")),
    ]
    alloc = chart_data(tree, root, ChartKind.CHILDREN_BY_ALLOC)
    assert [item.value for item in alloc] == [16, 8, 4]
    files = chart_data(tree, root, ChartKind.CHILDREN_BY_FILES)
    assert [(item.label, item.value) for item in files] == [
        ("a.txt", 1),
        ("b.jpg", 1),
        ("c", 1),
        ("folder", 1),
    ]
    folder_id = next(i for i in tree.children(root) if tree.name(i) == "folder")
    nested = chart_data(tree, folder_id, ChartKind.CHILDREN_BY_SIZE)
    assert [(item.label, item.value) for item in nested] == [("nested.jpg", 20)]


def test_extensions_categories_and_remainder(tmp_path: Path) -> None:
    tree = make_chart_tree(tmp_path)
    root = tree.roots()[0]
    by_size = chart_data(tree, root, ChartKind.EXT_BY_SIZE, top=1)
    assert by_size == [ChartSlice(".jpg", 30), ChartSlice("Other", 15, None, True)]
    assert chart_data(tree, root, ChartKind.EXT_BY_COUNT, top=1) == [
        ChartSlice(".jpg", 2),
        ChartSlice("Other", 2, None, True),
    ]
    assert chart_data(tree, root, ChartKind.CATEGORY_BY_SIZE, top=10) == [
        ChartSlice("Images", 30),
        ChartSlice("Documents", 10),
        ChartSlice("Other file types", 5),
    ]


def test_top_zero_other_ties_empty_and_validation(tmp_path: Path) -> None:
    tree = make_chart_tree(tmp_path)
    root = tree.roots()[0]
    result = chart_data(tree, root, ChartKind.CHILDREN_BY_SIZE, top=0)
    assert result == [ChartSlice("Other", 45, None, True)]
    tied = chart_data(tree, root, ChartKind.CHILDREN_BY_SIZE, top=2)
    assert [item.label for item in tied[:2]] == ["folder", "a.txt"]
    with pytest.raises(ValueError, match="top"):
        chart_data(tree, root, ChartKind.CHILDREN_BY_SIZE, top=-1)
    with pytest.raises(IndexError):
        chart_data(tree, len(tree), ChartKind.CHILDREN_BY_SIZE)
    with pytest.raises(TypeError, match="ChartKind"):
        chart_data(tree, root, "children_by_size")  # type: ignore[arg-type]
    empty_path = tmp_path / "empty"
    empty = scan(
        ScanRequest([empty_path]),
        backend=make_mock_backend(MockSpec([MockEntry(empty_path, EntryKind.DIR)])),
    ).tree
    empty_root = empty.roots()[0]
    assert chart_data(empty, empty_root, ChartKind.CHILDREN_BY_ALLOC) == []
    assert chart_data(empty, empty_root, ChartKind.EXT_BY_COUNT) == []


def test_merged_byte_values_saturate_at_uint64(tmp_path: Path) -> None:
    maximum = (1 << 64) - 1
    backend = make_mock_backend(
        MockSpec(
            [
                MockEntry(tmp_path, EntryKind.DIR),
                MockEntry(tmp_path / "a.txt", size=maximum),
                MockEntry(tmp_path / "b.pdf", size=maximum),
                MockEntry(tmp_path / "c.docx", size=maximum),
            ]
        )
    )
    tree = scan(ScanRequest([tmp_path]), backend=backend).tree
    root = tree.roots()[0]
    assert chart_data(tree, root, ChartKind.CATEGORY_BY_SIZE, top=0) == [
        ChartSlice("Other", maximum, None, True)
    ]
    assert chart_data(tree, root, ChartKind.EXT_BY_SIZE, top=1)[1] == ChartSlice(
        "Other", maximum, None, True
    )


def test_category_ties_use_stable_ids_when_translated_labels_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = make_mock_backend(
        MockSpec(
            [
                MockEntry(tmp_path, EntryKind.DIR),
                MockEntry(tmp_path / "a.mp4", size=5),
                MockEntry(tmp_path / "z.jpg", size=5),
            ]
        )
    )
    tree = scan(ScanRequest([tmp_path]), backend=backend).tree
    translated = {"Images": "Z Images", "Videos": "A Videos"}
    monkeypatch.setattr(analysis, "_", lambda text: translated.get(text, text))
    root = tree.roots()[0]
    assert [item.label for item in chart_data(tree, root, ChartKind.CATEGORY_BY_SIZE)] == [
        "Z Images",
        "A Videos",
    ]
