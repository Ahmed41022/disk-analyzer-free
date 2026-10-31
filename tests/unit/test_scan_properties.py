"""A thousand generated scans check saturation, exclusions, and physical identities."""

import sys
from collections import Counter

from hypothesis import given, settings
from hypothesis import strategies as st

from dafree.api import ExcludeRules, HardlinkMode, NodeFlags, ScanRequest, scan
from dafree.api.testing import MockEntry, MockSpec, make_mock_backend
from dafree.api.types import EntryKind

MAX_SIZE = (1 << 64) - 1


@st.composite
def _files(draw: st.DrawFn) -> tuple[list[int], list[tuple[int, bool, bool]]]:
    sizes = draw(st.lists(st.integers(0, MAX_SIZE), min_size=1, max_size=8))
    entries = draw(
        st.lists(
            st.tuples(st.integers(0, len(sizes) - 1), st.booleans(), st.booleans()), max_size=24
        )
    )
    return sizes, entries


@settings(max_examples=1000, database=None, derandomize=True, deadline=None)
@given(case=_files(), dedup=st.booleans(), exclude_hidden=st.booleans(), exclude_tmp=st.booleans())
def test_scan_matches_generated_accounting(
    case: tuple[list[int], list[tuple[int, bool, bool]]],
    dedup: bool,
    exclude_hidden: bool,
    exclude_tmp: bool,
) -> None:
    """Independent Python accounting agrees for duplicate links and excluded first links."""
    sizes, entries = case
    root = "C:/generated-mock" if sys.platform == "win32" else "/generated-mock"
    links = Counter(group for group, _, _ in entries)
    mock = [MockEntry(root, EntryKind.DIR)]
    selected = []
    for index, (group, hidden, temporary) in enumerate(entries):
        name = f"file-{index}.{'tmp' if temporary else 'bin'}"
        mock.append(
            MockEntry(
                f"{root}/{name}",
                size=sizes[group],
                ino_lo=group + 10,
                nlink=links[group],
                hidden=hidden,
            )
        )
        if not ((exclude_hidden and hidden) or (exclude_tmp and temporary)):
            selected.append(group)
    backend = make_mock_backend(MockSpec(mock))
    rules = ExcludeRules(hidden=exclude_hidden, globs=["*.tmp"] if exclude_tmp else [])
    mode = HardlinkMode.DEDUP if dedup else HardlinkMode.COUNT_ALL
    result = scan(ScanRequest([root], threads=1, exclude=rules, hardlinks=mode), backend=backend)
    contributions = set(selected) if dedup else selected
    expected_size = min(MAX_SIZE, sum(sizes[group] for group in contributions))
    assert result.summary.bytes == result.summary.alloc == expected_size
    assert result.summary.files == len(selected)
    assert result.summary.issues.total == 0
    assert len(result.tree) == len(selected) + 2
    duplicate_nodes = sum(
        bool(result.tree.node(i).flags & NodeFlags.HARDLINK_DUP) for i in range(len(result.tree))
    )
    expected_duplicates = len(selected) - len(set(selected)) if dedup else 0
    assert duplicate_nodes == expected_duplicates
