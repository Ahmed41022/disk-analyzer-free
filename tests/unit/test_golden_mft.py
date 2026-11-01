"""Synthetic MFT vectors are deterministic, verifiable, and never overwrite existing data."""

import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path

_SCRIPT = Path(__file__).parents[2] / "tools/golden_mft.py"
_COMMITTED = Path(__file__).parents[2] / "core/tests/golden/mft"


def run_generator(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Invoke the fixed generator script with argument-list quoting and a bounded runtime."""
    return subprocess.run(  # noqa: S603 -- fixed source script; output paths are test-owned.
        [sys.executable, str(_SCRIPT), *arguments],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )


def files_at(root: Path) -> dict[str, bytes]:
    """Read only known generator artifacts from a fixture directory."""
    return {
        path.name: path.read_bytes() for path in root.iterdir() if path.suffix in (".bin", ".json")
    }


def test_golden_generator_matches_committed_bytes(tmp_path: Path) -> None:
    """Committed synthetic records are exactly reproducible without host-volume access."""
    output = tmp_path / "generated"
    result = run_generator("--output-dir", str(output))
    assert result.returncode == 0, result.stderr
    assert files_at(output) == files_at(_COMMITTED)
    assert run_generator("--output-dir", str(output), "--check").returncode == 0
    before = {path.name: path.stat().st_mtime_ns for path in output.iterdir()}
    assert run_generator("--output-dir", str(output)).returncode == 0
    assert before == {path.name: path.stat().st_mtime_ns for path in output.iterdir()}


def test_golden_metadata_describes_bytes_and_restoration(tmp_path: Path) -> None:
    """JSON hashes and field expectations agree with the generated little-endian record bytes."""
    output = tmp_path / "generated"
    assert run_generator("--output-dir", str(output)).returncode == 0
    for path in sorted(output.glob("*.bin")):
        raw = path.read_bytes()
        metadata = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        fields = struct.unpack_from("<HHQHHHHIIQ", raw, 4)
        names = (
            "usa_offset",
            "usa_count",
            "lsn",
            "sequence",
            "link_count",
            "attrs_offset",
            "flags",
            "bytes_used",
            "bytes_allocated",
            "base_record",
        )
        assert dict(zip(names, fields, strict=True)) == {
            name: metadata["header"][name] for name in names
        }
        assert raw[:4] == metadata["header"]["signature"].encode("ascii")
        assert hashlib.sha256(raw).hexdigest() == metadata["sha256"]
        assert len(raw) == metadata["record_size"]
        sector, usa = metadata["sector_size"], metadata["header"]["usa_offset"]
        assert metadata["header"]["usa_count"] == len(raw) // sector + 1
        fixed = bytearray(raw)
        for index, original in enumerate(metadata["saved_sector_words"]):
            tail = (index + 1) * sector - 2
            assert struct.unpack_from("<H", raw, tail)[0] == metadata["usa_number"]
            assert struct.unpack_from("<H", raw, usa + (index + 1) * 2)[0] == original
            struct.pack_into("<H", fixed, tail, original)
        assert hashlib.sha256(fixed).hexdigest() == metadata["fixed_sha256"]


def test_check_missing_fixtures_never_creates_directory(tmp_path: Path) -> None:
    """Check mode reports missing artifacts without creating its requested destination."""
    output = tmp_path / "missing"
    result = run_generator("--output-dir", str(output), "--check")
    assert result.returncode == 1
    assert not output.exists()


def test_generator_refuses_existing_different_data(tmp_path: Path) -> None:
    """Neither generation nor checking overwrites a differing existing fixture."""
    output = tmp_path / "generated"
    assert run_generator("--output-dir", str(output)).returncode == 0
    damaged = output / "file_1024.bin"
    damaged.write_bytes(b"preserve this different file")
    before = files_at(output)
    for mode in ((), ("--check",)):
        result = run_generator("--output-dir", str(output), *mode)
        assert result.returncode == 1
        assert files_at(output) == before


def test_generator_refuses_final_links(tmp_path: Path) -> None:
    """A fixture-name link cannot redirect generation into another temporary file."""
    output = tmp_path / "generated"
    output.mkdir()
    target = tmp_path / "untouched.bin"
    target.write_bytes(b"preserve target")
    link = output / "file_1024.bin"
    link.symlink_to(target)
    result = run_generator("--output-dir", str(output))
    assert result.returncode == 1
    assert target.read_bytes() == b"preserve target" and link.is_symlink()
    assert sorted(path.name for path in output.iterdir()) == ["file_1024.bin"]


def test_generator_refuses_linked_output_directory(tmp_path: Path) -> None:
    """An output directory link is rejected before any missing fixture is created."""
    target = tmp_path / "target"
    target.mkdir()
    output = tmp_path / "output"
    output.symlink_to(target, target_is_directory=True)
    result = run_generator("--output-dir", str(output))
    assert result.returncode == 1 and list(target.iterdir()) == []
