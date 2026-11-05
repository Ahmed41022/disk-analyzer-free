"""Capture and independently verify one fixture record on the elevated Windows runner."""

import hashlib
import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    """Keep all fixture writes in a new temporary directory and print its artifact path."""
    executable = Path(sys.argv[1]).resolve(strict=True)
    volume = Path("D:/") if Path("D:/").is_dir() else Path("C:/")
    root = Path(tempfile.mkdtemp(prefix="dafree-mft-golden-", dir=volume))
    result = subprocess.run(  # noqa: S603 -- fixed build helper and test-created directory.
        [str(executable), str(root)], capture_output=True, text=True, timeout=120, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    raw = (root / "captured_file.bin").read_bytes()
    metadata_path = root / "captured_file.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
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
    assert dict(zip(names, struct.unpack_from("<HHQHHHHIIQ", raw, 4), strict=True)) == {
        name: metadata["header"][name] for name in names
    }
    assert raw[:4] == b"FILE"
    assert len(raw) == metadata["record_size"] == metadata["header"]["bytes_allocated"]
    sector = metadata["sector_size"]
    usa = metadata["header"]["usa_offset"]
    used = metadata["header"]["bytes_used"]
    assert metadata["header"]["usa_count"] == len(raw) // sector + 1
    fixed = bytearray(raw)
    for index, original in enumerate(metadata["saved_sector_words"]):
        tail = (index + 1) * sector - 2
        assert struct.unpack_from("<H", raw, tail)[0] == metadata["usa_number"]
        assert struct.unpack_from("<H", raw, usa + (index + 1) * 2)[0] == original
        struct.pack_into("<H", fixed, tail, original)
    assert not any(fixed[used:]), "Unused record tail must be scrubbed before upload"
    assert "dafree-captured-mft-fixture.bin".encode("utf-16le") in fixed[:used]
    assert b"DAFREE-MFT-GOLDEN-FIXTURE-V1\x00\x7f\x81\xff" in fixed[:used]
    metadata["sha256"] = hashlib.sha256(raw).hexdigest()
    metadata["fixed_sha256"] = hashlib.sha256(fixed).hexdigest()
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    repeated = subprocess.run(  # noqa: S603 -- same test-owned directory and fixed helper.
        [str(executable), str(root)], capture_output=True, text=True, timeout=120, check=False
    )
    assert repeated.returncode != 0
    assert before == {path.name: path.read_bytes() for path in root.iterdir()}
    target, link = root / "empty-directory", root / "linked-directory"
    target.mkdir()
    link.symlink_to(target, target_is_directory=True)
    linked = subprocess.run(  # noqa: S603 -- link and target both belong to this test.
        [str(executable), str(link)], capture_output=True, text=True, timeout=120, check=False
    )
    assert linked.returncode != 0 and list(target.iterdir()) == []
    print(root)


if __name__ == "__main__":
    main()
