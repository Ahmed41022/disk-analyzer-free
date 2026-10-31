"""Create deterministic sparse fixture trees in a new output directory."""

import argparse
import ctypes
import hashlib
import json
import os
import random
import stat
import sys
from ctypes import wintypes
from pathlib import Path
from typing import BinaryIO

PRESETS = {"small": 1000, "ci_500k": 500_000, "1m": 1_000_000, "10m": 10_000_000, "dupes_mix": 1000}
SEED = 2026
DUPLICATE_MEMBERS = 2

if sys.platform == "win32":
    import msvcrt


def _new_output(out: Path) -> Path:
    # Resolve lexically so checking for symlinks does not first follow them.
    out = Path(os.path.abspath(out))  # noqa: PTH100
    for component in (out, *out.parents):
        if component.is_symlink() or component.is_junction():
            raise ValueError(f"output must not traverse a link: {component}")
    out.mkdir(exist_ok=False)
    return out


def _mark_sparse(stream: BinaryIO) -> None:
    if sys.platform != "win32":
        return
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.DeviceIoControl.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel.DeviceIoControl.restype = wintypes.BOOL
    returned = wintypes.DWORD()
    fsctl_set_sparse = 0x000900C4
    if not kernel.DeviceIoControl(
        msvcrt.get_osfhandle(stream.fileno()),
        fsctl_set_sparse,
        None,
        0,
        None,
        0,
        ctypes.byref(returned),
        None,
    ):
        raise ctypes.WinError(ctypes.get_last_error())


def _listing(out: Path) -> dict[str, int | str]:
    digest = hashlib.sha256()
    files = dirs = total_size = 0
    pending = sorted(out.iterdir(), reverse=True)
    while pending:
        path = pending.pop()
        if path.is_symlink() or path.is_junction():
            raise ValueError(f"unexpected link in fixture: {path}")
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            kind, size = "dir", 0
            dirs += 1
            pending.extend(sorted(path.iterdir(), reverse=True))
        elif stat.S_ISREG(info.st_mode):
            kind, size = "file", info.st_size
            files += 1
            total_size += size
        else:
            raise ValueError(f"unexpected non-regular fixture entry: {path}")
        row = [path.relative_to(out).as_posix(), kind, size]
        digest.update((json.dumps(row, separators=(",", ":")) + "\n").encode())
    return {
        "files": files,
        "dirs": dirs,
        "total_size": total_size,
        "listing_sha256": digest.hexdigest(),
    }


def generate_fixtures(preset: str, out: Path) -> dict[str, int | str]:
    """Create a new tree; refuse existing outputs and link ancestors without changing them."""
    nodes = PRESETS[preset]
    out = _new_output(out)
    rng = random.Random(SEED)  # noqa: S311 -- repeatable fixture sizes, not security tokens
    entries = nodes
    directory_count = (entries + 9) // 10
    directories = [out]
    for index in range(1, entries):
        parent = directories[(index - 1) // 10]
        is_dir = index < directory_count
        name = f"{'d' if is_dir else 'f'}{index:08d}"
        if is_dir:
            path = parent / name
            path.mkdir()
            directories.append(path)
            continue
        size = 0 if index % 50 == 0 else min(1024**3, int(rng.lognormvariate(10, 2)))
        if preset == "dupes_mix" and index % 5 < DUPLICATE_MEMBERS:
            size = 4096 * (1 + index // 5 % 4)
        path = parent / (name + ".bin")
        with path.open("xb") as stream:
            _mark_sparse(stream)
            os.truncate(stream.fileno(), size)
    manifest = {"preset": preset, "seed": SEED, "nodes": nodes, **_listing(out)}
    with (out / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, sort_keys=True, indent=2)
        stream.write("\n")
    return manifest


def main(argv: list[str] | None = None) -> int:
    """Generate the selected fixture and print its manifest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset", required=True, choices=PRESETS)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = generate_fixtures(args.preset, args.out)
    except (OSError, ValueError) as error:
        parser.exit(2, f"{error}\n")
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
