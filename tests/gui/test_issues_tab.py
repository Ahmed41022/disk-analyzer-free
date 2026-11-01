"""Retained issue filtering, lossless clipboard payloads, and exclusive CSV report creation."""

# ruff: noqa: PLR2004 -- retention bounds and expected row counts are assertions.

import csv
import io
import json
import os
from collections.abc import Iterator
from importlib.util import find_spec
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

if find_spec("PySide6") is None:
    if os.environ.get("DAFREE_REQUIRE_GUI") == "1":
        pytest.fail("PySide6 is required when DAFREE_REQUIRE_GUI=1", pytrace=False)
    pytest.skip("PySide6 is not installed", allow_module_level=True)

from PySide6.QtCore import QCoreApplication, QEvent, QLocale
from PySide6.QtTest import QAbstractItemModelTester
from PySide6.QtWidgets import QApplication, QFileDialog

from dafree.api.types import IssueKind, ScanIssue
from dafree.gui.controllers.task_runner import TaskRunner
from dafree.gui.views import issues_tab as module
from dafree.gui.views.issues_tab import IssuesTab
from dafree.i18n import current_locale, setup

pytestmark = pytest.mark.gui


@pytest.fixture
def issues(qtbot: QtBot) -> Iterator[IssuesTab]:
    previous, language = QLocale(), current_locale()
    QLocale.setDefault(QLocale("en_US"))
    setup("en_US")
    runner = TaskRunner()
    view = IssuesTab(runner=runner)
    qtbot.addWidget(view)
    view.show()
    yield view
    qtbot.waitUntil(lambda: not runner.busy, timeout=5000)
    runner.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QLocale.setDefault(previous)
    setup(language)


def test_issues_filter_by_kind(issues: IssuesTab, tmp_path: Path) -> None:
    """Exact enum matching includes kind zero and preserves the active filter across updates."""
    tester = QAbstractItemModelTester(
        issues.model, QAbstractItemModelTester.FailureReportingMode.Fatal, issues
    )
    rows = [
        ScanIssue(str(tmp_path / "denied"), IssueKind.ACCESS_DENIED, "Denied"),
        ScanIssue(str(tmp_path / "io"), IssueKind.IO, "I/O"),
        ScanIssue(str(tmp_path / "missing"), IssueKind.NOT_FOUND, "Missing"),
    ]
    issues.set_issues(rows, 3)
    assert issues.model.rowCount() == 3
    issues.kind_filter.setCurrentIndex(issues.kind_filter.findData(IssueKind.ACCESS_DENIED.value))
    assert issues.model.rowCount() == 1 and issues.model.index(0, 0).data() == "Access denied"
    issues.set_issues([*rows, ScanIssue(str(tmp_path / "new"), IssueKind.IO, "I/O")], 4)
    assert issues.model.rowCount() == 1
    issues.kind_filter.setCurrentIndex(0)
    assert issues.model.rowCount() == 4 and issues.summary.text() == "Showing 4 of 4 issues"
    assert tester.model() is issues.model


def test_copy_all_copies_filtered_diagnostics_and_raw_json(
    issues: IssuesTab, tmp_path: Path
) -> None:
    """Copy means every displayed retained row; diagnostic text and raw native strings coexist."""
    raw = ScanIssue(str(tmp_path / "bad-\udcff"), IssueKind.IO, 'bad,"line"\nnext')
    issues.set_issues([raw, ScanIssue(str(tmp_path / "other"), IssueKind.NOT_FOUND, "Missing")], 2)
    issues.kind_filter.setCurrentIndex(issues.kind_filter.findData(IssueKind.IO.value))
    issues.copy.click()
    mime = QApplication.clipboard().mimeData()
    rows = list(csv.reader(io.StringIO(mime.text(), newline="")))
    assert rows == [
        ["Kind", "Path", "Message"],
        ["I/O error", str(tmp_path / r"bad-\udcff"), raw.message],
    ]
    payload = json.loads(bytes(mime.data("application/x-dafree-issues+json")))
    assert payload == [{"kind": "IO", "path": raw.path, "message": raw.message}]


def test_export_csv_quotes_and_preserves_selection(
    issues: IssuesTab, tmp_path: Path, qtbot: QtBot, monkeypatch
) -> None:
    """CSV uses a worker and the selected subset, quoting commas/newlines and UTF-8 names."""
    raw = ScanIssue(str(tmp_path / "Arabic-ملف,one"), IssueKind.IO, 'bad,"line"\nnext')
    issues.set_issues([raw, ScanIssue(str(tmp_path / "other"), IssueKind.NOT_FOUND, "Missing")], 2)
    issues.kind_filter.setCurrentIndex(issues.kind_filter.findData(IssueKind.IO.value))
    output = tmp_path / "issues.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(output), ""))
    with qtbot.waitSignal(issues.exportFinished) as exported:
        issues.export.click()
    assert exported.args == [True]
    with output.open(encoding="utf-8", newline="") as stream:
        assert list(csv.reader(stream)) == [
            ["Kind", "Path", "Message"],
            ["I/O error", raw.path, raw.message],
        ]
    assert issues.kind_filter.currentData() == IssueKind.IO.value
    assert issues.export.isEnabled() and issues.model.rowCount() == 1


@pytest.mark.parametrize("symlink", [False, True])
def test_export_never_overwrites_existing_file_or_link(
    issues: IssuesTab, tmp_path: Path, qtbot: QtBot, symlink: bool
) -> None:
    """Existing reports and symlink targets remain byte-for-byte unchanged on export failure."""
    target = tmp_path / "keep.csv"
    target.write_bytes(b"keep original")
    output = target
    if symlink:
        output = tmp_path / "link.csv"
        output.symlink_to(target)
    issues.set_issues([ScanIssue(str(tmp_path), IssueKind.IO, "I/O")], 1)
    with qtbot.waitSignal(issues.exportFinished) as exported:
        issues.export_to(output)
    assert exported.args == [False] and target.read_bytes() == b"keep original"
    assert output.is_symlink() is symlink
    assert "existing files are preserved" in issues.message.text()


def test_empty_filter_and_retention_bound(issues: IssuesTab, tmp_path: Path) -> None:
    """Filters cannot reveal diagnostics beyond the core cap or enable empty report actions."""
    issues.set_issues(
        [ScanIssue(str(tmp_path / str(i)), IssueKind.IO, "I/O") for i in range(1005)], 1005
    )
    assert issues.model.rowCount() == 1000
    issues.kind_filter.setCurrentIndex(issues.kind_filter.findData(IssueKind.ACCESS_DENIED.value))
    assert (
        issues.model.rowCount() == 0
        and not issues.copy.isEnabled()
        and not issues.export.isEnabled()
    )
    issues.kind_filter.setCurrentIndex(0)
    assert (
        issues.model.rowCount() == 1000 and issues.summary.text() == "Showing 1000 of 1005 issues"
    )


def test_write_error_reports_incomplete_new_file(
    issues: IssuesTab, tmp_path: Path, qtbot: QtBot, monkeypatch
) -> None:
    """An interrupted new report is reported explicitly and never removed through unsafe helpers."""
    native_writer = csv.writer

    class FailingWriter:
        def __init__(self, stream):
            self.writer = native_writer(stream)

        def writerow(self, row):
            return self.writer.writerow(row)

        def writerows(self, rows):
            raise OSError("simulated disk full")

    monkeypatch.setattr(module.csv, "writer", FailingWriter)
    output = tmp_path / "partial.csv"
    issues.set_issues([ScanIssue(str(tmp_path), IssueKind.IO, "I/O")], 1)
    with qtbot.waitSignal(issues.exportFinished) as exported:
        issues.export_to(output)
    assert exported.args == [False]
    assert output.exists() and output.read_text(encoding="utf-8").startswith("Kind,Path,Message")
    assert (
        "may be incomplete" in issues.message.text()
        and "simulated disk full" in issues.message.text()
    )
