"""Build deterministic synthetic NTFS record headers and update-sequence arrays."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

_SECTOR_SIZE = 512
_NTFS31_USA_OFFSET = 0x30
_USA_NUMBER = 0xA55A
_HEADER_LSN = 0x0102030405060708
_BASE_REFERENCE = 0xFEDCBA9876543210


def _record(name: str, size: int, usa_offset: int, flags: int) -> dict[str, bytes]:
    """Create an original byte pattern with a valid fixed header and protected sector tails."""
    count = size // _SECTOR_SIZE + 1
    attrs_offset = (usa_offset + count * 2 + 7) // 8 * 8
    bytes_used = attrs_offset + 8
    data = bytearray((index * 37 + 11) % 256 for index in range(size))
    data[:4] = b"FILE"
    struct.pack_into(
        "<HHQHHHHIIQ",
        data,
        4,
        usa_offset,
        count,
        _HEADER_LSN,
        0x1234,
        0x2345,
        attrs_offset,
        flags,
        bytes_used,
        size,
        _BASE_REFERENCE,
    )
    struct.pack_into("<H", data, 0x28, 0x42)
    if usa_offset >= _NTFS31_USA_OFFSET:
        struct.pack_into("<HI", data, 0x2A, 0, 0x10203040)
    struct.pack_into("<I", data, attrs_offset, 0xFFFFFFFF)
    data[attrs_offset + 4 : bytes_used] = bytes(4)
    tails = [0xB000 + index for index in range(size // _SECTOR_SIZE)]
    struct.pack_into("<H", data, usa_offset, _USA_NUMBER)
    for index, original in enumerate(tails):
        struct.pack_into("<H", data, usa_offset + (index + 1) * 2, original)
        struct.pack_into("<H", data, (index + 1) * _SECTOR_SIZE - 2, _USA_NUMBER)
    fixed = bytearray(data)
    for index, original in enumerate(tails):
        struct.pack_into("<H", fixed, (index + 1) * _SECTOR_SIZE - 2, original)
    metadata = {
        "provenance": "Synthetic bytes; no filesystem record was captured or copied.",
        "record_size": size,
        "sector_size": _SECTOR_SIZE,
        "usa_number": _USA_NUMBER,
        "saved_sector_words": tails,
        "sha256": hashlib.sha256(data).hexdigest(),
        "fixed_sha256": hashlib.sha256(fixed).hexdigest(),
        "header": {
            "signature": "FILE",
            "usa_offset": usa_offset,
            "usa_count": count,
            "lsn": _HEADER_LSN,
            "sequence": 0x1234,
            "link_count": 0x2345,
            "attrs_offset": attrs_offset,
            "flags": flags,
            "bytes_used": bytes_used,
            "bytes_allocated": size,
            "base_record": _BASE_REFERENCE,
        },
    }
    return {
        f"{name}.bin": bytes(data),
        f"{name}.json": (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    }


def fixtures() -> dict[str, bytes]:
    """Return all committed T3.1 vectors without reading a host filesystem or disk volume."""
    return (
        _record("file_1024", 1024, 0x30, 1)
        | _record("directory_2048", 2048, 0x30, 3)
        | _record("ntfs30_1024", 1024, 0x2A, 1)
    )


def main(argv: list[str] | None = None) -> int:
    """Generate missing vectors or check their bytes; never replace existing differing files."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "core/tests/golden/mft",
    )
    parser.add_argument(
        "--check", action="store_true", help="Check existing vectors without writing"
    )
    args = parser.parse_args(argv)
    directory: Path = args.output_dir
    try:
        if directory.is_symlink() or directory.is_junction():
            raise OSError("fixture output directory must not be a link")
        expected = fixtures()
        missing: list[str] = []
        wrong: list[str] = []
        for name, value in expected.items():
            path = directory / name
            if path.is_symlink():
                wrong.append(name)
            elif not path.exists():
                missing.append(name)
            elif path.read_bytes() != value:
                wrong.append(name)
        if wrong or (args.check and missing):
            print(
                "Golden fixtures differ or are missing: " + ", ".join(sorted(wrong + missing)),
                file=sys.stderr,
            )
            return 1
        if not args.check:
            directory.mkdir(parents=True, exist_ok=True)
            for name in missing:
                with (directory / name).open("xb") as output:
                    output.write(expected[name])
        return 0
    except OSError as error:
        print(f"Could not prepare golden fixtures: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
