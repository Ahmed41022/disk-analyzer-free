"""Reusable fixture descriptions for platform and scanner tests."""

import os
import sys

from tests.testkit.spec import Dir, File, HardLink, Item, Junction, Symlink, Unreadable


def small_mixed() -> Dir:
    """Return a small tree with hand-checkable totals."""
    return Dir("root", (File("alpha.bin", 10), Dir("sub", (File("beta.bin", 20), File("empty")))))


def unicode_zoo() -> Dir:
    """Return names that exercise UTF-8, normalization, and byte limits."""
    children: list[Item] = [
        File("café"),
        File("ملف.txt"),
        File("文件.txt"),
        Dir("📁", (File("😀.bin"),)),
        File("space name .txt"),
        File("-rf.txt"),
        File("x" * 255),
    ]
    if sys.platform.startswith("linux"):
        children.extend((File("cafe\u0301"), File(os.fsdecode(b"\xff"))))
    return Dir("root", tuple(children))


def symlink_loop() -> Dir:
    """Return a directory symlink that points back at the fixture root."""
    return Dir("root", (Dir("child", (Symlink("back", "", is_dir=True),)),))


def hardlinks() -> Dir:
    """Return one file with two additional directory entries."""
    return Dir(
        "root",
        (File("original", 11), HardLink("copy-a", "original"), HardLink("copy-b", "original")),
    )


def deep(levels: int) -> Dir:
    """Return a nested directory chain with one terminal file."""
    if levels < 0:
        raise ValueError("levels must be non-negative")
    current = Dir(f"level-{levels}", (File("leaf", 1),))
    for level in reversed(range(levels)):
        current = Dir(f"level-{level}", (current,))
    return Dir("root", (current,))


def wide(files: int) -> Dir:
    """Return a root with many small direct file children."""
    if files < 0:
        raise ValueError("files must be non-negative")
    return Dir("root", tuple(File(f"file-{index:08d}", index % 16) for index in range(files)))


def sparse_big() -> Dir:
    """Return a five-gibibyte sparse file without filling disk space."""
    return Dir("root", (File("sparse.bin", 5 * 1024**3, "sparse"),))


def permission_denied() -> Dir:
    """Return an unreadable directory containing a file."""
    return Dir("root", (Unreadable("private", (File("secret", 8),)),))


def long_paths() -> Dir:
    """Return a path beyond Windows MAX_PATH or Linux PATH_MAX."""
    current = Dir("leaf", (File("data.bin", 1),))
    levels = 20 if sys.platform.startswith("linux") else 12
    width = 200 if sys.platform.startswith("linux") else 20
    for index in reversed(range(levels)):
        current = Dir(f"segment-{index:02d}-" + "x" * width, (current,))
    return Dir("root", (current,))


def dupes_mix() -> Dir:
    """Return equal and unequal deterministic file contents."""
    return Dir(
        "root",
        (
            File("same-a.bin", 4096, "random", 17),
            File("same-b.bin", 4096, "random", 17),
            File("different.bin", 4096, "random", 18),
            File("zero.bin", 4096, "zeros"),
            Dir("nested", (File("same-c.bin", 4096, "random", 17),)),
        ),
    )


def junction() -> Dir:
    """Return a directory and a Windows junction that targets it."""
    return Dir("root", (Dir("target", (File("child", 1),)), Junction("junction", "target")))
