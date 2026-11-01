# Synthetic MFT header fixtures

These records are generated entirely by [tools/golden_mft.py](../../../../tools/golden_mft.py).
They contain an original deterministic byte pattern, explicit little-endian
header values, an update-sequence array, and an attribute end marker. No record
was captured from a disk or copied from another implementation. They are not
complete filesystem images and contain no real filenames or user data.

The layout facts come from Microsoft's NTFS version 3 documentation:

- [FILE_RECORD_SEGMENT_HEADER](https://learn.microsoft.com/en-us/windows/win32/devnotes/file-record-segment-header)
- [MULTI_SECTOR_HEADER](https://learn.microsoft.com/en-us/windows/win32/devnotes/multi-sector-header)

The implementation plan defines `usa_count` as the number of 16-bit words,
including the update sequence number. Microsoft's multisector remarks describe
the same storage formula; this avoids the ambiguous “bytes” wording in that
page's member summary. The fixup stride in these vectors is 512 bytes.

| File | Size | USA offset/count | Attributes offset | Flags |
| --- | ---: | --- | --- | --- |
| `file_1024.bin` | 1,024 | `0x30` / 3 | `0x38` | In use |
| `directory_2048.bin` | 2,048 | `0x30` / 5 | `0x40` | In use, directory |
| `ntfs30_1024.bin` | 1,024 | `0x2A` / 3 | `0x30` | In use |

The `0x2A` USA case exercises the older header boundary without assuming the
later record-number field is present. Each companion JSON records every
expected public header field, original sector-tail words, and SHA-256 values
before and after restoration. C++ tests assert the field values independently
and compare the complete restored byte sequence.

Regenerate missing files or verify committed bytes from the repository root:

```console
python tools/golden_mft.py
python tools/golden_mft.py --check
python tools/golden_mft.py --output-dir path/to/new/fixture-directory
```

The generator writes missing files exclusively, accepts identical existing
files without rewriting, and rejects differing existing files or final links.
`--check` never creates or modifies anything. Runtime mutations and malformed
vectors are built in test memory; Python filesystem tests use their own
pytest temporary directories. T3.5 will add a separately identified record
captured from the CI runner's own fixture, with expected JSON, when the reader
exists. No captured record is included in T3.1.
