"""Owner names resolve lazily by identity, or eagerly before scan completion."""

import getpass
import sys
from pathlib import Path

import pytest

from dafree.api import OwnerMode, ScanRequest, scan
from dafree.api.testing import MockEntry, MockSpec, make_mock_backend
from dafree.api.types import EntryKind

RESOLVED_IDENTITIES = 2


@pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX owner lookup; Windows SID support is later"
)
@pytest.mark.parametrize("mode", [OwnerMode.LAZY, OwnerMode.EAGER])
def test_owner_current_user_resolves(tmp_path: Path, mode: OwnerMode) -> None:
    """A real current-user file resolves to the operating system's account name."""
    path = tmp_path / "owned"
    path.write_bytes(b"owned")
    result = scan(ScanRequest([tmp_path], owner=mode))
    node_id = result.tree.find_path(path)
    assert node_id is not None
    if mode == OwnerMode.LAZY:
        assert result.tree.node(node_id).owner is None
        result.tree.resolve_owners([node_id])
    assert result.tree.node(node_id).owner == getpass.getuser()


def test_unknown_uid_formats_numeric(tmp_path: Path) -> None:
    """An unknown mock UID falls back to its decimal identity."""
    uid = 4_000_000_001
    backend = make_mock_backend(MockSpec([MockEntry(tmp_path, EntryKind.DIR, owner_uid=uid)]))
    tree = scan(ScanRequest([tmp_path]), backend=backend).tree
    root = tree.roots()[0]
    tree.resolve_owners([root])
    assert tree.node(root).owner == str(uid)


def test_lazy_resolves_only_requested(tmp_path: Path) -> None:
    """Only requested identities trigger lookups; shared and repeated IDs reuse the cache."""
    backend = make_mock_backend(
        MockSpec(
            [
                MockEntry(tmp_path, EntryKind.DIR, owner_uid=100),
                MockEntry(tmp_path / "a", owner_uid=101),
                MockEntry(tmp_path / "same-owner", owner_uid=101),
                MockEntry(tmp_path / "b", owner_uid=102),
            ],
            owner_names={100: "root-owner", 101: "alice", 102: "bob"},
        )
    )
    tree = scan(ScanRequest([tmp_path]), backend=backend).tree
    root = tree.roots()[0]
    first = tree.find_path(tmp_path / "a")
    same = tree.find_path(tmp_path / "same-owner")
    second = tree.find_path(tmp_path / "b")
    assert first is not None and same is not None and second is not None
    assert backend.owner_resolution_calls == 0
    tree.resolve_owners([first, first])
    assert backend.owner_resolution_calls == 1
    assert tree.node(first).owner == tree.node(same).owner == "alice"
    assert tree.node(root).owner is None
    assert tree.node(second).owner is None
    tree.resolve_owners([same])
    assert backend.owner_resolution_calls == 1
    tree.resolve_owners([second])
    assert tree.node(second).owner == "bob"
    assert backend.owner_resolution_calls == RESOLVED_IDENTITIES
    with pytest.raises(IndexError):
        tree.resolve_owners([len(tree)])


def test_eager_and_off_owner_policies(tmp_path: Path) -> None:
    """Eager resolves each identity once; off retains no identities to resolve."""
    spec = MockSpec(
        [
            MockEntry(tmp_path, EntryKind.DIR, owner_uid=100),
            MockEntry(tmp_path / "a", owner_uid=101),
            MockEntry(tmp_path / "b", owner_uid=101),
        ],
        owner_names={100: "root-owner", 101: "alice"},
    )
    eager = make_mock_backend(spec)
    tree = scan(ScanRequest([tmp_path], owner=OwnerMode.EAGER), backend=eager).tree
    assert eager.owner_resolution_calls == RESOLVED_IDENTITIES
    assert tree.node(tree.roots()[0]).owner == "root-owner"
    assert all(tree.node(i).owner == "alice" for i in tree.children(tree.roots()[0]))
    off = make_mock_backend(spec)
    tree = scan(ScanRequest([tmp_path], owner=OwnerMode.OFF), backend=off).tree
    tree.resolve_owners(list(range(len(tree))))
    assert off.owner_resolution_calls == 0
    assert all(tree.node(i).owner is None for i in range(len(tree)))
