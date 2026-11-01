"""Tests for C++ dependency license policy validation."""

import subprocess
import sys
from pathlib import Path

from tools.cpp_licenses import check_dependencies


def test_cpp_licenses_accepts_exact_pcre2_spdx_expression(tmp_path: Path) -> None:
    """Recognize the upstream binary-redistribution exception without broadening policy."""
    path = tmp_path / "Dependencies.cmake"
    expression = "BSD-3-Clause WITH PCRE2-exception"
    document = (
        f"# dafree-dep: name=pcre2 license={expression} url=https://example.invalid/pcre2\n"
        "FetchContent_Declare(pcre2\n"
        f"  URL_HASH SHA256={'a' * 64}\n)\n"
    )
    path.write_text(document, encoding="utf-8")
    assert check_dependencies(path) == []
    path.write_text(document.replace(expression, "BSD-3-Clause OR GPL-3.0"), encoding="utf-8")
    assert any("disallowed license" in error for error in check_dependencies(path))


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
