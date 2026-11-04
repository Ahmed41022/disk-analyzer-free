"""Exercise the scan command and its native report writers."""

import csv
import io
import json
import re
import signal
import subprocess
import sys
from pathlib import Path
from queue import Queue
from threading import Thread
from time import sleep

import pytest
from click.testing import CliRunner, Result
from jsonschema import Draft202012Validator
from syrupy.assertion import SnapshotAssertion

from dafree import api
from dafree.api.testing import MockEntry, MockSpec, make_mock_backend
from dafree.cli.exit_codes import Exit
from dafree.cli.main import cli

_SCHEMA = Path(__file__).parents[2] / "schemas" / "report.v1.json"


def _run(path: Path, format_: str, *options: str) -> Result:
    return CliRunner().invoke(
        cli,
        ["--format", format_, "--units", "b", "scan", "--files", str(path), *options],
        env={"COLUMNS": "120"},
    )


def _mock(monkeypatch: pytest.MonkeyPatch, spec: MockSpec) -> None:
    start_scan = api.start_scan
    backend = make_mock_backend(spec)
    monkeypatch.setattr(api, "start_scan", lambda req, **_kwargs: start_scan(req, backend=backend))


def test_scan_small_mixed_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snapshot: SnapshotAssertion
) -> None:
    root = tmp_path / "mixed"
    _mock(
        monkeypatch,
        MockSpec(
            [
                MockEntry(root, api.EntryKind.DIR),
                MockEntry(root / "empty", api.EntryKind.DIR),
                MockEntry(root / "second.bin", size=2),
                MockEntry(root / "first.bin", size=8),
            ]
        ),
    )
    result = _run(root, "table")
    assert result.exit_code == Exit.OK, result.output
    output = re.sub(r"\d{4}-\d{2}-\d{2}T\S+", "<timestamp>", result.stdout)
    header, root_row, *children = output.rstrip().splitlines()
    root_row = root_row[: header.index("Name")] + "<root>"
    assert "\n".join(row.rstrip() for row in [header, root_row, *children]) == snapshot


def test_scan_json_validates_schema(tmp_path: Path) -> None:
    (tmp_path / "payload.txt").write_bytes(b"payload")
    stats = tmp_path / "stats.json"
    result = _run(tmp_path, "json", "--stats-json", str(stats))
    assert result.exit_code == Exit.OK, result.output
    assert not result.stderr
    report = json.loads(result.stdout)
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(
        report
    )
    assert report["roots"][0]["children"][0]["name"] == "payload.txt"
    measured = json.loads(stats.read_text(encoding="utf-8"))
    assert set(measured) == {"wall_ms", "peak_rss_bytes", "nodes", "mode"}
    expected_nodes = 2
    assert measured["nodes"] == expected_nodes and measured["mode"] == "walk"
    assert measured["wall_ms"] > 0 and measured["peak_rss_bytes"] > 0


def test_scan_ndjson_one_object_per_line(tmp_path: Path) -> None:
    path = tmp_path / "child"
    path.write_bytes(b"x")
    result = _run(tmp_path, "ndjson")
    assert result.exit_code == Exit.OK, result.output
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert [Path(row["path"]) for row in rows] == [tmp_path, path]


def test_scan_csv_quotes_commas_and_newlines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = "report,\n2026.txt"
    _mock(
        monkeypatch,
        MockSpec([MockEntry(tmp_path, api.EntryKind.DIR), MockEntry(tmp_path / name, size=1)]),
    )
    result = _run(tmp_path, "csv")
    assert result.exit_code == Exit.OK, result.output
    rows = list(csv.DictReader(io.StringIO(result.stdout_bytes.decode("utf-8"), newline="")))
    root, child = rows
    assert root["type"] == "directory" and child["name"] == name
    assert '"report,\n2026.txt"' in result.stdout_bytes.decode("utf-8")


def test_scan_strict_access_denied_exit_4(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blocked = tmp_path / "blocked"
    _mock(
        monkeypatch,
        MockSpec(
            [
                MockEntry(tmp_path, api.EntryKind.DIR),
                MockEntry(blocked, api.EntryKind.DIR),
                MockEntry(tmp_path / "visible", size=3),
            ],
            errors={str(blocked): api.IssueKind.ACCESS_DENIED},
        ),
    )
    result = _run(tmp_path, "json", "--strict")
    assert result.exit_code == Exit.PARTIAL, result.output
    report = json.loads(result.stdout)
    assert report["meta"]["issues"] == 1 and not report["meta"]["cancelled"]
    assert any(child["name"] == "visible" for child in report["roots"][0]["children"])


def test_scan_sigint_exit_130_json_valid(tmp_path: Path) -> None:
    windows = sys.platform == "win32"
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if windows else 0
    command = [
        sys.executable,
        "-c",
        "from dafree.cli.main import main; raise SystemExit(main())",
        "--format",
        "json",
        "--progress",
        "always",
        "scan",
        "--test-slow-backend",
        str(tmp_path),
    ]
    with subprocess.Popen(  # noqa: S603 -- Fixed interpreter and arguments, no shell.
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
    ) as process:
        assert process.stderr is not None
        stderr = process.stderr
        ready: Queue[bytes] = Queue()
        reader = Thread(target=lambda: ready.put(stderr.readline()), daemon=True)
        reader.start()
        try:
            assert ready.get(timeout=15).startswith(b"Scanning")
            sleep(0.2)
            process.send_signal(signal.CTRL_BREAK_EVENT if windows else signal.SIGINT)
            stdout, diagnostics = process.communicate(timeout=15)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=15)
            reader.join(timeout=15)
    assert process.returncode == Exit.INTERRUPTED, diagnostics
    report = json.loads(stdout)
    assert report["meta"]["cancelled"] is True
    Draft202012Validator(json.loads(_SCHEMA.read_text(encoding="utf-8"))).validate(report)


def test_scan_progress_is_separate_from_report(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        cli, ["--format", "json", "--progress", "always", "scan", str(tmp_path)]
    )
    assert result.exit_code == Exit.OK, result.output
    assert result.stderr.startswith("Scanning")
    assert json.loads(result.stdout)["meta"]["cancelled"] is False


def test_scan_stats_preserves_an_existing_file(tmp_path: Path) -> None:
    stats = tmp_path / "stats.json"
    stats.write_bytes(b"existing contents")
    result = _run(tmp_path, "json", "--stats-json", str(stats))
    assert result.exit_code == Exit.RUNTIME
    assert stats.read_bytes() == b"existing contents"
