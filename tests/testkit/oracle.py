"""Pure expected totals for a fixture specification."""

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

from tests.testkit.spec import Dir, File, HardLink, Item, Junction, Symlink, Unreadable


@dataclass(frozen=True)
class Expected:
    """Logical bytes and entry counts at a fixture path."""

    size: int
    files: int
    dirs: int
    hardlink_dups: int


def _file_size(item: File) -> int:
    return item.size if item.size or not isinstance(item.content, bytes) else len(item.content)


def _key(target: str) -> str:
    path = PurePosixPath(target)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"fixture target escapes root: {target}")
    return "" if target in {"", "."} else path.as_posix()


def oracle(
    spec: Dir,
    *,
    hardlinks: Literal["dedup", "count_all"] = "dedup",
    follow_symlinks: bool = False,
) -> dict[str, Expected]:
    """Compute expected subtree totals without touching the filesystem."""
    if hardlinks not in {"dedup", "count_all"}:
        raise ValueError("unknown hard-link mode")
    items: dict[str, Item] = {"": spec}

    def index(parent: str, directory: Dir | Unreadable) -> None:
        for child in directory.children:
            path = f"{parent}/{child.name}" if parent else child.name
            items[path] = child
            if isinstance(child, (Dir, Unreadable)):
                index(path, child)

    index("", spec)
    result: dict[str, Expected] = {}

    def walk(item: Item, path: str, seen_dirs: frozenset[str]) -> Expected:
        if isinstance(item, File):
            value = Expected(_file_size(item), 1, 0, 0)
        elif isinstance(item, HardLink):
            target = items.get(_key(item.target))
            if not isinstance(target, File):
                raise ValueError(f"hard-link target is not a fixture file: {item.target}")
            value = Expected(_file_size(target) if hardlinks == "count_all" else 0, 1, 0, 1)
        elif isinstance(item, (Symlink, Junction)):
            if not follow_symlinks:
                value = Expected(0, 0 if isinstance(item, Junction) else 1, 0, 0)
            else:
                target_path = _key(item.target)
                target = items.get(target_path)
                if target is None or target_path in seen_dirs:
                    value = Expected(0, 0 if isinstance(item, Junction) else 1, 0, 0)
                else:
                    value = walk(target, target_path, seen_dirs)
        elif isinstance(item, Unreadable):
            value = Expected(0, 0, 0, 0)
        else:
            total = Expected(0, 0, 0, 0)
            current_seen = seen_dirs | {path}
            for child in item.children:
                child_path = f"{path}/{child.name}" if path else child.name
                child_total = walk(child, child_path, current_seen)
                is_directory = isinstance(child, (Dir, Unreadable, Junction)) or (
                    follow_symlinks and isinstance(child, Symlink) and child.is_dir
                )
                total = Expected(
                    total.size + child_total.size,
                    total.files + child_total.files,
                    total.dirs + child_total.dirs + int(is_directory),
                    total.hardlink_dups + child_total.hardlink_dups,
                )
            value = total
        result[path] = value
        return value

    walk(spec, "", frozenset())
    return result
