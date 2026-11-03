"""Exercise the native JSON stream through the public Python API."""

import io
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dafree import api
from dafree.api.testing import MockEntry, MockSpec, TreeBuilder, make_mock_backend

_SCHEMA = Path(__file__).parents[2] / "schemas" / "report.v1.json"


def test_json_validates_against_schema(tmp_path: Path) -> None:
    folder = tmp_path / "folder"
    folder.mkdir()
    path = folder / "résumé.txt"
    content = b"abcdef"
    path.write_bytes(content)
    tree = api.scan(api.ScanRequest([tmp_path])).tree
    schema = json.loads(_SCHEMA.read_text(encoding="utf8"))
    Draft202012Validator.check_schema(schema)
    checker = Draft202012Validator.FORMAT_CHECKER

    output = io.BytesIO()
    api.write_json(tree, output, pretty=True)
    document = json.loads(output.getvalue())
    Draft202012Validator(schema, format_checker=checker).validate(document)
    assert document["schema"] == schema["$id"]
    assert document["version"] == 1 and document["meta"]["cancelled"] is False
    root = document["roots"][0]
    assert root["size"] == len(content) and root["dirs"] == 1 and root["files"] == 1
    leaf = root["children"][0]["children"][0]
    assert leaf["name"] == path.name and leaf["ext"] == "txt"
    assert leaf["mtime"].endswith("Z")

    scope = tree.find_path(folder)
    assert scope is not None
    flat = io.BytesIO()
    api.write_json(tree, flat, scopes=[scope], ndjson=True, pretty=True)
    assert flat.getvalue().endswith(b"\n")
    rows = [json.loads(line) for line in flat.getvalue().splitlines()]
    line_schema = {
        "$schema": schema["$schema"],
        "$defs": schema["$defs"],
        "$ref": "#/$defs/line",
    }
    line_validator = Draft202012Validator(line_schema, format_checker=checker)
    for row in rows:
        line_validator.validate(row)
    leaf_id = tree.find_path(path)
    assert leaf_id is not None
    assert [row["path"] for row in rows] == [tree.path(scope), tree.path(leaf_id)]


def test_json_native_name_and_lazy_owner(tmp_path: Path) -> None:
    suffix = chr(0xD800 if sys.platform == "win32" else 0xDCFF)
    raw = b"\xed\xa0\x80" if sys.platform == "win32" else b"\xff"
    folder = tmp_path / ("broken-" + suffix)
    path = folder / "entry.txt"
    uid = 123
    backend = make_mock_backend(
        MockSpec(
            [
                MockEntry(tmp_path, api.EntryKind.DIR),
                MockEntry(folder, api.EntryKind.DIR),
                MockEntry(path, size=7, owner_uid=uid),
            ],
            owner_names={uid: "local owner"},
        )
    )
    tree = api.scan(api.ScanRequest([tmp_path]), backend=backend).tree
    output = io.BytesIO()
    api.write_json(tree, output, ndjson=True, include_owner=True)
    _, directory, leaf = [json.loads(line) for line in output.getvalue().splitlines()]
    assert directory["name"] == "broken-\ufffd"
    assert bytes.fromhex(directory["name_raw_hex"]) == b"broken-" + raw
    assert leaf["owner"] == "local owner" and "name_raw_hex" not in leaf
    assert (b"broken-" + raw) in bytes.fromhex(leaf["path_raw_hex"])
    assert backend.owner_resolution_calls == 1


def test_json_stream_chunks_allow_short_writes_and_tree_reads(tmp_path: Path) -> None:
    files = 1199
    chunk_size = 64 * 1024
    tree = TreeBuilder.flat(tmp_path, files + 1)
    root = tree.roots()[0]
    calls: list[int] = []

    class ShortWriter(io.BytesIO):
        def write(self, data: bytes, /) -> int:
            assert tree.node(root).files == files
            calls.append(len(data))
            return super().write(data[:8192])

    stream = ShortWriter()
    api.write_json(tree, stream)
    assert len(calls) > 1 and max(calls) <= chunk_size
    assert len(json.loads(stream.getvalue())["roots"][0]["children"]) == files


def test_json_sink_error_is_preserved(tmp_path: Path) -> None:
    tree = TreeBuilder.flat(tmp_path, 2)

    class BrokenWriter(io.BytesIO):
        def write(self, data: bytes, /) -> int:
            raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        api.write_json(tree, BrokenWriter())


def test_json_validates_scopes_before_writing(tmp_path: Path) -> None:
    tree = TreeBuilder.flat(tmp_path, 2)
    output = io.BytesIO()
    with pytest.raises(IndexError, match="scope"):
        api.write_json(tree, output, scopes=[tree.roots()[0], 0])
    assert output.getvalue() == b""
