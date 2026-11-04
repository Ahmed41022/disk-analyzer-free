"""Snapshot the CLI analysis reports on the shared small fixture."""

import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner
from syrupy.assertion import SnapshotAssertion

from dafree.cli.exit_codes import Exit
from dafree.cli.main import cli
from tests.testkit.builder import Fixture
from tests.testkit.presets import small_mixed

_NOW = 1_750_000_000
_DAY = 86_400


@pytest.mark.parametrize("command", ["top", "types", "age"])
def test_small_mixed_analysis_snapshot(
    command: str, tmp_path: Path, snapshot: SnapshotAssertion
) -> None:
    with Fixture.create(small_mixed(), tmp_path) as fixture:
        timestamps = {"alpha.bin": 10, "sub/beta.bin": 60, "sub/empty": 2_000}
        for name, days in timestamps.items():
            timestamp = _NOW - days * _DAY
            os.utime(fixture.root / name, (timestamp, timestamp))
        flags = ["--now", str(_NOW)] if command == "age" else []
        result = CliRunner().invoke(
            cli, ["--locale", "en-US", "--format", "json", command, str(fixture.root), *flags]
        )
        assert result.exit_code == Exit.OK, result.output
        rows = json.loads(result.stdout)
        assert rows
        for row in rows:
            assert row["alloc"] >= 0
            row["alloc"] = "<filesystem allocation>"
            if "path" in row:
                row["path"] = Path(row["path"]).relative_to(fixture.root).as_posix()
        assert rows == snapshot


def test_analysis_table_and_custom_age_cutoffs(tmp_path: Path) -> None:
    (tmp_path / "file.txt").write_bytes(b"x")
    runner = CliRunner()
    result = runner.invoke(
        cli, ["--format", "table", "--units", "b", "age", str(tmp_path), "--buckets", "1d,1y"]
    )
    assert result.exit_code == Exit.OK, result.output
    assert all(title in result.stdout for title in ("Age", "Files", "Size", "Alloc", "<1d"))
    invalid = runner.invoke(cli, ["age", str(tmp_path), "--buckets", "1y,1d"])
    assert invalid.exit_code == Exit.USAGE
    assert "strictly increasing" in invalid.stderr


def test_types_csv_records_use_crlf(tmp_path: Path) -> None:
    (tmp_path / "file.txt").write_bytes(b"x")
    result = CliRunner().invoke(cli, ["--format", "csv", "types", str(tmp_path)])
    assert result.exit_code == Exit.OK, result.output
    lines = result.stdout_bytes.splitlines(keepends=True)
    header, row = lines
    assert header == b"ext,files,size,alloc,category\r\n"
    assert row.startswith(b"txt,1,1,") and row.endswith(b",document\r\n")
