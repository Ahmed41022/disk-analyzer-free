"""Parse the native CSV output with Python's standard library."""

import csv
import io
import locale
from pathlib import Path

import pytest

from dafree import api
from dafree.api.testing import MockEntry, MockSpec, make_mock_backend


def test_csv_roundtrip_with_stdlib_reader(tmp_path: Path) -> None:
    name = 'quote "and", comma\r\nthen newline.txt'
    size = 7
    uid = 123
    backend = make_mock_backend(
        MockSpec(
            [
                MockEntry(tmp_path, api.EntryKind.DIR),
                MockEntry(tmp_path / name, size=size, owner_uid=uid, hidden=True),
            ],
            owner_names={uid: "owner, name"},
        )
    )
    tree = api.scan(api.ScanRequest([tmp_path]), backend=backend).tree
    output = io.BytesIO()
    api.write_csv(tree, output, include_owner=True)
    data = output.getvalue()
    assert not data.startswith(b"\xef\xbb\xbf")
    assert data.endswith(b"\r\n")
    root, leaf = list(csv.DictReader(io.StringIO(data.decode("utf8"), newline=""), strict=True))
    assert root["type"] == "directory" and root["files"] == "1"
    assert leaf["name"] == name
    assert leaf["path"] == str(tmp_path / name)
    assert leaf["size"] == str(size) and leaf["pct_parent"] == "1"
    assert leaf["owner"] == "owner, name" and leaf["flags"] == "hidden"
    assert leaf["mtime_iso"] == "" and leaf["ext"] == "txt"


def test_csv_excel_bom_semicolon(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "report;segment.txt").write_bytes(b"x")
    tree = api.scan(api.ScanRequest([tmp_path])).tree
    monkeypatch.setattr(locale, "localeconv", lambda: {"decimal_point": ","})
    output = io.BytesIO()
    api.write_csv(tree, output, excel=True)
    data = output.getvalue()
    assert data.startswith(b"\xef\xbb\xbfpath;name;type;")
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""), delimiter=";")
    _, leaf = list(reader)
    assert leaf["name"] == "report;segment.txt" and leaf["pct_parent"] == "1"

    explicit = io.BytesIO()
    api.write_csv(tree, explicit, excel=True, delimiter=",", depth=0)
    assert explicit.getvalue().startswith(b"\xef\xbb\xbfpath,name,type,")
    explicit_rows = csv.DictReader(io.StringIO(explicit.getvalue().decode("utf-8-sig"), newline=""))
    assert len(list(explicit_rows)) == 1


@pytest.mark.parametrize("delimiter", ["", '"', "\r", "\n", "\0", "é", "::"])
def test_csv_rejects_invalid_delimiter_before_writing(tmp_path: Path, delimiter: str) -> None:
    tree = api.scan(api.ScanRequest([tmp_path])).tree
    output = io.BytesIO()
    with pytest.raises(ValueError, match="delimiter"):
        api.write_csv(tree, output, delimiter=delimiter)
    assert output.getvalue() == b""
