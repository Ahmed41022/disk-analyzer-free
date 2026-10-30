"""Immutable descriptions of temporary filesystem fixtures."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Dir:
    """A directory and its direct children."""

    name: str
    children: tuple["Item", ...] = ()


@dataclass(frozen=True)
class File:
    """A regular file with deterministic content or a sparse extent."""

    name: str
    size: int = 0
    content: Literal["zeros", "random", "sparse"] | bytes = "zeros"
    seed: int = 0


@dataclass(frozen=True)
class HardLink:
    """A second directory entry for a file relative to the fixture root."""

    name: str
    target: str


@dataclass(frozen=True)
class Symlink:
    """A symbolic link to a path relative to the fixture root."""

    name: str
    target: str
    is_dir: bool = False


@dataclass(frozen=True)
class Junction:
    """A Windows directory junction to a path relative to the fixture root."""

    name: str
    target: str


@dataclass(frozen=True)
class Unreadable:
    """A directory whose listing permission is removed after creation."""

    name: str
    children: tuple["Item", ...] = ()


type Item = Dir | File | HardLink | Symlink | Junction | Unreadable
