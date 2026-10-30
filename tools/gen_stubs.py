"""Generate committed type stubs for the installed native extension."""

import subprocess
import sys
from pathlib import Path


def main() -> int:
    """Generate and format the native extension's type stub."""
    project_root = Path(__file__).parents[1]
    output_file = project_root / "src" / "dafree" / "_core.pyi"
    # Both commands have fixed module names and argument lists; neither invokes a shell.
    subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "nanobind.stubgen",
            "-m",
            "dafree._core",
            "-o",
            str(output_file),
        ],
        check=True,
    )
    subprocess.run(  # noqa: S603
        [sys.executable, "-m", "ruff", "format", str(output_file)],
        check=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
