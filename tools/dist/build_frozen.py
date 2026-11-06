"""Build a minimal, replaceable-library PyInstaller GUI bundle for smoke checks."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from importlib.metadata import distribution
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def _repository_path(value: Path, *, label: str) -> Path:
    """Resolve a build path and require it to remain inside the checkout."""
    resolved = value.resolve()
    try:
        resolved.relative_to(_REPO)
    except ValueError as error:
        raise ValueError(f"{label} must be inside the repository: {resolved}") from error
    if resolved == _REPO:
        raise ValueError(f"{label} cannot be the repository root")
    return resolved


def _write_licenses(bundle: Path) -> None:
    """Include LGPL/GPL texts and matching Qt/PySide source pointers beside shared libraries."""
    from PySide6.QtCore import qVersion  # noqa: PLC0415 -- build environment dependency.

    licenses = bundle / "licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_REPO / "LICENSE", licenses / "LICENSE")
    for name in ("LGPL-3.0.txt", "GPL-3.0.txt"):
        shutil.copyfile(_REPO / "packaging" / "licenses" / name, licenses / name)
    pyside = distribution("PySide6-Essentials").version
    qt = qVersion()
    notice = (
        "Qt / PySide6 / Shiboken notices\n"
        "==============================\n\n"
        f"Qt {qt}; PySide6-Essentials {pyside}; shiboken6 {distribution('shiboken6').version}\n"
        "Used under LGPL-3.0; LGPL-3.0.txt and the incorporated GPL-3.0.txt are included.\n"
        f"Qt source: https://code.qt.io/cgit/qt/qtbase.git/tree/?h=v{qt}\n"
        f"PySide/Shiboken source: https://code.qt.io/cgit/pyside/pyside-setup.git/tree/?h=v{pyside}\n"
        "Official Qt source archives: https://download.qt.io/official_releases/qt/\n"
        "The Qt/PySide/Shiboken shared libraries remain separate and replaceable in this\n"
        "onedir bundle. This smoke bundle is for testing, not a release installer.\n"
        "License text sources: https://www.gnu.org/licenses/lgpl-3.0.txt and\n"
        "https://www.gnu.org/licenses/gpl-3.0.txt\n"
    )
    (licenses / "THIRD_PARTY_NOTICES.txt").write_text(notice, encoding="utf-8")


def _check_shared_qt(bundle: Path) -> None:
    """Reject a smoke bundle that does not retain Qt Core as a separate shared library."""
    names = {"Qt6Core.dll", "libQt6Core.so.6", "QtCore"}
    if not any(path.is_file() and path.name in names for path in bundle.rglob("*")):
        raise RuntimeError("Frozen bundle is missing a separate Qt Core shared library")


def _build_environment() -> dict[str, str]:
    """Keep unrelated Windows tool DLLs from shadowing Qt's OS dependencies."""
    environment = os.environ.copy()
    if os.name == "nt":
        system = Path(os.environ["SYSTEMROOT"])
        directories = [
            Path(distribution("PySide6-Essentials").locate_file("PySide6")),
            Path(distribution("shiboken6").locate_file("shiboken6")),
            Path(sys.executable).parent,
            Path(sys.base_prefix),
            system / "System32",
            system,
        ]
        environment["PATH"] = os.pathsep.join(map(str, directories))
    return environment


def build(out: Path) -> Path:
    """Run PyInstaller and return the built GUI executable path."""
    output = _repository_path(out, label="Output directory")
    bundle = output / "DiskAnalyzerFree"
    if bundle.exists():
        raise FileExistsError(f"Refusing to overwrite an existing bundle directory: {bundle}")

    work = _repository_path(
        _REPO / "build" / f"frozen-{sys.platform}" / output.name, label="Work directory"
    )
    work.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--console",
        "--name",
        "DiskAnalyzerFree",
        "--distpath",
        str(output),
        "--workpath",
        str(work),
        "--specpath",
        str(work),
        "--collect-data",
        "dafree",
        str(_REPO / "tools" / "dist" / "gui_entry.py"),
    ]
    subprocess.run(  # noqa: S603 -- fixed interpreter/module; repository-validated output paths.
        command, cwd=_REPO, env=_build_environment(), check=True
    )
    _check_shared_qt(bundle)
    _write_licenses(bundle)
    executable = bundle / ("DiskAnalyzerFree.exe" if os.name == "nt" else "DiskAnalyzerFree")
    if not executable.is_file():
        raise FileNotFoundError(f"PyInstaller did not create the expected executable: {executable}")
    return executable.resolve()


def main() -> int:
    """Parse the requested output directory and build the frozen GUI bundle."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="repository-local output directory")
    args = parser.parse_args()
    try:
        executable = build(args.out)
    except (
        FileExistsError,
        FileNotFoundError,
        RuntimeError,
        ValueError,
        subprocess.CalledProcessError,
    ) as error:
        parser.error(str(error))
    print(executable)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
