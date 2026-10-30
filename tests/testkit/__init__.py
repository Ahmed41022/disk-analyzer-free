"""Temporary filesystem fixtures and a pure expected-results oracle."""

from tests.testkit.builder import Fixture
from tests.testkit.oracle import Expected, oracle
from tests.testkit.platform_caps import Caps
from tests.testkit.presets import (
    deep,
    dupes_mix,
    hardlinks,
    junction,
    long_paths,
    permission_denied,
    small_mixed,
    sparse_big,
    symlink_loop,
    unicode_zoo,
    wide,
)
from tests.testkit.spec import Dir, File, HardLink, Item, Junction, Symlink, Unreadable

__all__ = [
    "Caps",
    "Dir",
    "Expected",
    "File",
    "Fixture",
    "HardLink",
    "Item",
    "Junction",
    "Symlink",
    "Unreadable",
    "deep",
    "dupes_mix",
    "hardlinks",
    "junction",
    "long_paths",
    "oracle",
    "permission_denied",
    "small_mixed",
    "sparse_big",
    "symlink_loop",
    "unicode_zoo",
    "wide",
]
