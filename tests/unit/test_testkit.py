"""The testkit creates only temporary files and computes independent totals."""

import os
import sys
from pathlib import Path

from tests.testkit import Expected, Fixture, hardlinks, oracle, small_mixed, symlink_loop
from tests.testkit.presets import junction, long_paths, permission_denied, unicode_zoo
from tests.testkit.spec import Dir, File

LINUX_LONG_PATH_BYTES = 4200
WINDOWS_LONG_PATH_CHARS = 400


def test_fixture_creates_and_cleans_up(tmp_path: Path) -> None:
    """A fixture materializes under pytest's temp path and removes its tree."""
    alpha_bytes = 10
    beta_bytes = 20
    with Fixture.create(small_mixed(), tmp_path) as fixture:
        root = fixture.root
        assert root.is_relative_to(tmp_path)
        assert (root / "alpha.bin").stat().st_size == alpha_bytes
        assert (root / "sub" / "beta.bin").stat().st_size == beta_bytes
        assert (root / "sub" / "empty").is_file()
    assert not root.exists()


def test_oracle_small_mixed_hand_values() -> None:
    """The pure oracle agrees with hand-counted subtree totals."""
    assert oracle(small_mixed()) == {
        "": Expected(size=30, files=3, dirs=1, hardlink_dups=0),
        "alpha.bin": Expected(size=10, files=1, dirs=0, hardlink_dups=0),
        "sub": Expected(size=20, files=2, dirs=0, hardlink_dups=0),
        "sub/beta.bin": Expected(size=20, files=1, dirs=0, hardlink_dups=0),
        "sub/empty": Expected(size=0, files=1, dirs=0, hardlink_dups=0),
    }


def test_fixture_hardlinks_and_oracle(tmp_path: Path) -> None:
    """Additional links share one inode while dedup keeps one byte contribution."""
    with Fixture.create(hardlinks(), tmp_path) as fixture:
        fixture.caps.require("hardlink")
        original = fixture.root / "original"
        assert original.stat().st_ino == (fixture.root / "copy-a").stat().st_ino
        assert original.stat().st_ino == (fixture.root / "copy-b").stat().st_ino
    assert oracle(hardlinks())[""] == Expected(size=11, files=3, dirs=0, hardlink_dups=2)
    assert oracle(hardlinks(), hardlinks="count_all")[""] == Expected(
        size=33, files=3, dirs=0, hardlink_dups=2
    )


def test_symlink_loop_is_not_followed(tmp_path: Path) -> None:
    """A symlink loop is represented without recursively walking its target."""
    with Fixture.create(symlink_loop(), tmp_path) as fixture:
        fixture.caps.require("symlink")
        assert (fixture.root / "child" / "back").is_symlink()
    assert oracle(symlink_loop())[""] == Expected(size=0, files=1, dirs=1, hardlink_dups=0)


def test_unicode_zoo_materializes_names(tmp_path: Path) -> None:
    """Unicode, byte-boundary, and platform-specific names survive creation."""
    with Fixture.create(unicode_zoo(), tmp_path) as fixture:
        assert (fixture.root / "ملف.txt").is_file()
        assert (fixture.root / "文件.txt").is_file()
        assert (fixture.root / "📁" / "😀.bin").is_file()
        assert (fixture.root / ("x" * 255)).is_file()
        if sys.platform.startswith("linux"):
            fixture.caps.require("invalid_utf8")
            assert (fixture.root / os.fsdecode(b"\xff")).is_file()
            assert (fixture.root / "café").is_file()
            assert (fixture.root / "cafe\u0301").is_file()


def test_sparse_file_and_long_path(tmp_path: Path) -> None:
    """Sparse and long path fixtures have their declared logical shapes."""
    sparse = Dir("root", (File("sparse.bin", 32 * 1024**2, "sparse"),))
    with Fixture.create(sparse, tmp_path) as fixture:
        fixture.caps.require("sparse")
        assert (fixture.root / "sparse.bin").stat().st_size == 32 * 1024**2
    with Fixture.create(long_paths(), tmp_path) as fixture:
        fixture.caps.require("long_paths")
        leaf = fixture.root
        directory = fixture.spec
        while directory.children and isinstance(directory.children[0], Dir):
            directory = directory.children[0]
            leaf /= directory.name
        if sys.platform.startswith("linux"):
            assert len(os.fsencode(leaf)) >= LINUX_LONG_PATH_BYTES
            fd = os.open(fixture.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                for component in leaf.relative_to(fixture.root).parts:
                    next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY, dir_fd=fd)
                    os.close(fd)
                    fd = next_fd
                assert os.stat("data.bin", dir_fd=fd).st_size == 1
            finally:
                os.close(fd)
        else:
            assert (leaf / "data.bin").is_file()
            assert len(str(leaf)) >= WINDOWS_LONG_PATH_CHARS


def test_permission_denial_restored_for_cleanup(tmp_path: Path) -> None:
    """The denied directory is restored and fully removed on exit."""
    with Fixture.create(permission_denied(), tmp_path) as fixture:
        fixture.caps.require("permission_denied")
        root = fixture.root
        if sys.platform != "win32":
            try:
                list((root / "private").iterdir())
            except PermissionError:
                pass
            else:
                raise AssertionError("fixture directory remains readable")
    assert not root.exists()


def test_windows_junction(tmp_path: Path) -> None:
    """Windows creates a junction to a directory inside the fixture."""
    if sys.platform != "win32":
        return
    with Fixture.create(junction(), tmp_path) as fixture:
        fixture.caps.require("junction")
        assert (fixture.root / "junction" / "child").is_file()
