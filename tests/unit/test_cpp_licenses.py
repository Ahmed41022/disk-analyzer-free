"""Tests for C++ dependency license policy validation."""

import subprocess
import sys
from pathlib import Path


def test_cpp_licenses_rejects_gpl(tmp_path: Path) -> None:
    """The dependency checker rejects an explicitly declared GPL dependency."""
    fake_dependencies = tmp_path / "Dependencies.cmake"
    fake_dependencies.write_text(
        "# dafree-dep: name=gpl-lib license=GPL-3.0 url=https://example.invalid/gpl-lib\n"
        "FetchContent_Declare(\n"
        "  gpl-lib\n"
        "  URL https://example.invalid/gpl-lib.tar.gz\n"
        f"  URL_HASH SHA256={'a' * 64}\n"
        ")\n",
        encoding="utf-8",
    )
    script = Path(__file__).parents[2] / "tools" / "cpp_licenses.py"

    result = subprocess.run(  # noqa: S603
        [sys.executable, str(script), str(fake_dependencies)],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode != 0
    assert "GPL-3.0" in result.stderr
