"""Tests for JUnit failure summaries."""

import subprocess
import sys
from pathlib import Path


def _run_summary(report: Path) -> subprocess.CompletedProcess[str]:
    """Run the summary tool against a report path."""
    script = Path(__file__).parents[2] / "tools" / "junit_summary.py"
    return subprocess.run(  # noqa: S603
        [sys.executable, str(script), str(report)],
        capture_output=True,
        check=False,
        text=True,
    )


def test_junit_summary_ignores_missing_reports(tmp_path: Path) -> None:
    """A missing test report is informational and does not fail the job."""
    result = _run_summary(tmp_path / "missing.xml")

    assert result.returncode == 0
    assert result.stdout.strip() == "No JUnit reports found."


def test_junit_summary_renders_failures(tmp_path: Path) -> None:
    """JUnit failures become readable Markdown rows."""
    report = tmp_path / "results.xml"
    report.write_text(
        '<testsuites><testsuite name="unit"><testcase name="broken">'
        '<failure message="expected | actual">trace</failure>'
        "</testcase></testsuite></testsuites>",
        encoding="utf-8",
    )

    result = _run_summary(report)

    assert result.returncode == 0
    assert "| unit | broken | failure | expected \\| actual |" in result.stdout
