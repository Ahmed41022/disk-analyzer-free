"""Build and clean up test fixtures inside caller-owned temporary space."""

import contextlib
import os
import random
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import Self

from tests.testkit.platform_caps import Caps
from tests.testkit.spec import Dir, File, HardLink, Item, Junction, Symlink, Unreadable

_WINDOWS_PATH_PROBE_LIMIT = 240


def _valid_name(name: str) -> bool:
    return bool(name) and name not in {".", ".."} and "/" not in name and "\\" not in name


def _inside(root: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"fixture target escapes root: {relative}")
    return root.joinpath(*path.parts)


def _run_tool(name: str, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    executable = shutil.which(name)
    if executable is None:
        return subprocess.CompletedProcess([name, *arguments], 127, b"", b"tool unavailable")
    # The executable is resolved locally and arguments point inside the fixture's temp tree.
    return subprocess.run([executable, *arguments], capture_output=True, check=False)  # noqa: S603


class Fixture:
    """A generated filesystem tree scoped to a temporary directory."""

    def __init__(self, spec: Dir, temporary: tempfile.TemporaryDirectory[str]) -> None:
        """Keep the fixture description and its owned temporary directory."""
        self.spec = spec
        self._temporary = temporary
        self.root = Path(temporary.name) / spec.name
        self.caps = Caps()
        self._links: list[tuple[Path, HardLink | Symlink | Junction]] = []
        self._unreadable: list[Path] = []
        self._regular_files: set[Path] = set()
        self._directories: set[Path] = set()

    @classmethod
    def create(cls, spec: Dir, base: Path) -> "Fixture":
        """Create a fixture below a temporary base supplied by the test."""
        if not _valid_name(spec.name):
            raise ValueError("fixture root must have a simple name")
        temporary = tempfile.TemporaryDirectory(prefix="dafree-", dir=base)
        fixture = cls(spec, temporary)
        try:
            fixture._build_dir(spec, fixture.root)
            fixture._create_links()
            fixture._deny_reading()
        except BaseException:
            fixture._restore_permissions()
            temporary.cleanup()
            raise
        return fixture

    def __enter__(self) -> Self:
        """Return the live temporary fixture."""
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        """Restore permissions and remove only the owned temporary tree."""
        self._restore_permissions()
        self._temporary.cleanup()

    def _build_dir(self, spec: Dir | Unreadable, path: Path, parent_fd: int | None = None) -> None:
        try:
            if parent_fd is None:
                path.mkdir()
            else:
                os.mkdir(path.name, dir_fd=parent_fd)
        except OSError as error:
            if sys.platform == "win32" and len(str(path)) > _WINDOWS_PATH_PROBE_LIMIT:
                self.caps.unavailable("long_paths", str(error))
                return
            raise
        self._directories.add(path)
        directory_fd = None
        if os.name != "nt":
            directory_fd = os.open(
                path if parent_fd is None else path.name,
                os.O_RDONLY | os.O_DIRECTORY,
                dir_fd=parent_fd,
            )
        try:
            for child in spec.children:
                self._build_child(child, path, directory_fd)
        finally:
            if directory_fd is not None:
                os.close(directory_fd)

    def _build_child(self, child: Item, parent: Path, parent_fd: int | None) -> None:
        if not _valid_name(child.name):
            raise ValueError(f"fixture entry has an invalid name: {child.name!r}")
        destination = parent / child.name
        if isinstance(child, (Dir, Unreadable)):
            self._build_dir(child, destination, parent_fd)
            if isinstance(child, Unreadable):
                self._unreadable.append(destination)
        elif isinstance(child, File):
            try:
                self._write_file(child, destination, parent_fd)
            except (OSError, UnicodeError) as error:
                if sys.platform.startswith("linux") and any(
                    "\udc80" <= char <= "\udcff" for char in child.name
                ):
                    self.caps.unavailable("invalid_utf8", str(error))
                    return
                if sys.platform == "win32" and len(str(destination)) > _WINDOWS_PATH_PROBE_LIMIT:
                    self.caps.unavailable("long_paths", str(error))
                    return
                raise
        else:
            self._links.append((destination, child))

    def _write_file(self, spec: File, path: Path, parent_fd: int | None) -> None:
        if spec.size < 0:
            raise ValueError("fixture file size must be non-negative")
        if spec.content == "sparse" and sys.platform == "win32":
            path.touch()
            result = _run_tool("fsutil", "sparse", "setflag", str(path))
            if result.returncode != 0:
                self.caps.unavailable("sparse", result.stderr.decode(errors="replace"))
        output = (
            os.fdopen(
                os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600, dir_fd=parent_fd),
                "wb",
            )
            if parent_fd is not None
            else path.open("wb")
        )
        if isinstance(spec.content, bytes):
            with output:
                output.write(spec.content)
                if spec.size:
                    output.truncate(spec.size)
            self._regular_files.add(path)
            return
        if spec.content == "sparse":
            with output:
                output.truncate(spec.size)
            self._regular_files.add(path)
            return
        random_bytes = random.Random(spec.seed)  # noqa: S311 -- deterministic test bytes
        remaining = spec.size
        with output:
            while remaining:
                count = min(remaining, 64 * 1024)
                if spec.content == "zeros":
                    output.write(bytes(count))
                else:
                    output.write(random_bytes.randbytes(count))
                remaining -= count
        self._regular_files.add(path)

    def _create_links(self) -> None:
        for path, item in self._links:
            target = _inside(self.root, item.target)
            if isinstance(item, HardLink):
                if target not in self._regular_files:
                    raise ValueError("hard-link target must be a fixture regular file")
                try:
                    os.link(target, path)
                except OSError as error:
                    self.caps.unavailable("hardlink", str(error))
            elif isinstance(item, Symlink):
                try:
                    path.symlink_to(
                        os.path.relpath(target, path.parent), target_is_directory=item.is_dir
                    )
                except OSError as error:
                    self.caps.unavailable("symlink", str(error))
            elif sys.platform == "win32":
                if target not in self._directories:
                    raise ValueError("junction target must be a fixture directory")
                result = _run_tool("cmd", "/c", "mklink", "/J", str(path), str(target))
                if result.returncode != 0:
                    self.caps.unavailable("junction", result.stderr.decode(errors="replace"))
            else:
                self.caps.unavailable("junction", "junctions require Windows")

    def _deny_reading(self) -> None:
        for path in self._unreadable:
            if sys.platform == "win32":
                result = _run_tool("icacls", str(path), "/deny", "*S-1-1-0:(RX)")
                if result.returncode != 0:
                    self.caps.unavailable(
                        "permission_denied", result.stderr.decode(errors="replace")
                    )
            else:
                try:
                    path.chmod(0)
                except OSError as error:
                    self.caps.unavailable("permission_denied", str(error))
                else:
                    if os.access(path, os.R_OK):
                        self.caps.unavailable("permission_denied", "current user bypasses mode 000")

    def _restore_permissions(self) -> None:
        for path in reversed(self._unreadable):
            if sys.platform == "win32":
                # The Everyone RX deny also blocks reading the ACL; ownership restores
                # the ability to edit that deny before removing the temp tree.
                _run_tool("takeown", "/F", str(path))
                _run_tool("icacls", str(path), "/remove:d", "*S-1-1-0")
            else:
                with contextlib.suppress(FileNotFoundError):
                    path.chmod(stat.S_IRWXU)
