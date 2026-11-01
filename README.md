# Disk Analyzer Free

Find out what's using your disk space — fast, free and open source.

[![CI](https://github.com/Ahmed41022/disk-analyzer-free/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Ahmed41022/disk-analyzer-free/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/Ahmed41022/disk-analyzer-free/branch/main/graph/badge.svg)](https://codecov.io/gh/Ahmed41022/disk-analyzer-free)
[![Release](https://img.shields.io/github/v/release/Ahmed41022/disk-analyzer-free)](https://github.com/Ahmed41022/disk-analyzer-free/releases)
[![PyPI](https://img.shields.io/pypi/v/disk-analyzer-free)](https://pypi.org/project/disk-analyzer-free/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Platforms](https://img.shields.io/badge/platforms-Windows%20%7C%20macOS%20%7C%20Linux-blue)

> **Project status:** early development. The Python API supports cross-platform walk scanning, progress controls, link policies, exclusions, and owner resolution. The CLI provides version and configuration commands; its scan/report commands and the full GUI are still in development. Packaged releases are planned.

## Screenshots

Screenshots of the light and dark interfaces will be added when the GUI milestone is complete.

## Project scope

The implementation plan stages these capabilities:

- **Scanning:** fast directory walks, Windows NTFS fast mode, progress controls, multiple targets, and safe handling of links and permissions.
- **Views:** virtualized directory tables, treemaps, charts, file counts, logical size, and allocated size.
- **Search and analysis:** filters, largest files, extension and age breakdowns, empty folders, duplicates, snapshots, and comparisons.
- **Actions:** reveal and inspect files, and carefully confirmed delete or move operations with trash as the default.
- **Network:** scanning network shares with suitable defaults.
- **Reports and automation:** CSV, JSON, HTML, and PDF exports, scheduled scans, and alerts.
- **Languages:** English is the initial interface language; Arabic (right-to-left) and German catalogues are being scaffolded.

See the [implementation plan](docs/PLAN.md) for milestone status and the complete scope.

## Install

There are no published installers or PyPI package yet. When packaged releases are available, the planned downloads are an MSI, EXE, or portable ZIP for Windows; a DMG for macOS (Gatekeeper may warn while unsigned); and AppImage, deb, or rpm packages for Linux. The pip package is intended for the CLI, with the GUI available as an extra.

To build from a source checkout, install Python 3.12+, a C++20 compiler, CMake 3.26+, and Ninja, then run:

```console
python -m pip install .
```

For the desktop window, install the optional Qt dependencies too:

```console
python -m pip install ".[gui]"
```

Windows, macOS, and Linux packaging instructions will be added with the release milestone. The pip package will provide the CLI; the GUI is an optional extra. Qt is distributed under LGPL-3.0 as replaceable shared libraries when bundled.

## Quick start

For the current desktop scaffold:

1. Install the source package with the `[gui]` extra as shown above.
2. Open a terminal in the environment where it was installed.
3. Launch the app:

```console
dafree --version
dafree gui
```

The CLI version command is:

```console
dafree --version
```

Shared preferences are available now:

```console
dafree config path
dafree config get theme
dafree config set theme dark
dafree config set default_scan.threads 4
```

See [configuration commands](docs/cli.md) for typed values, migrations, and storage paths.

The Python API can scan and page sorted tree rows without walking entries in Python:

```python
from dafree.api import ScanRequest, SortKey, TreeView, ViewOptions, scan

tree = scan(ScanRequest(["."])).tree
view = TreeView(tree, ViewOptions(sort=SortKey.SIZE, descending=True))
for row in view.rows(0, 100):  # at most 500 rows per call
    node_id, depth, _, _, name, size, *_ = row
    print("  " * depth + name, size)
```

`expand(id)`, `collapse(id)`, and `expand_to(id)` control visible paths. `FilterSpec`
expressions evaluate in C++; query-text parsing remains planned. Rows are copied
15-field tuples, documented in the API and native stub. Extension category IDs
currently report `Other`; classification arrives with the deferred analysis task.

The following shows the planned CLI syntax; scan and report commands are not implemented yet:

```console
dafree scan C:\ --depth 2
dafree find ~/ "size>1GB"
dafree dupes ~/Pictures
dafree export / --to html -o report.html
```

Use `from dafree.api import scan, ScanRequest` for Python scans; see [Python scanning](#python-scanning) below for progress controls and asynchronous usage.

Size formatting and parsing are available now:

```python
from dafree.api import UnitStyle, UnitSystem, format_size, parse_size

format_size(1536)  # "1.5 KB"
format_size(1500, style=UnitStyle(UnitSystem.SI, ","))  # "1,5 kB"
parse_size("500 MiB")  # 524288000
```

## Windows fast mode

The planned Windows NTFS fast mode reads file-system metadata to avoid opening every file individually. It can require administrator privileges and will fall back to a regular directory walk when unavailable.

## Safety

Destructive operations are planned with safety as a default: confirmation, dry-run support, trash or recycle bin by default, protected paths, and no link following when deleting. Scanning is available through the Python API; deleting and moving files are not implemented.

## Python scanning

```python
from dafree.api import ScanRequest, scan

result = scan(ScanRequest(["."]))
print(result.summary.bytes, result.summary.files)
for node_id in result.tree.children(result.tree.roots()[0]):
    print(result.tree.name(node_id), result.tree.node(node_id).size)
```

`start_scan(request)` returns a handle with progress, pause, resume, cancel,
`wait(timeout_ms)`, partial snapshots, and a once-only `take_result()`. Waiting
releases the Python GIL. Trees remain usable after their scan handle is discarded.
Paths preserve POSIX undecodable bytes and Windows lone surrogates. Links are not
followed by default. Blocking `scan` invokes optional progress callbacks on its
calling thread; native workers never call Python. Errors derive from
`dafree.api.errors.DafreeError`, with classified `ScanError` and `ExcludeError` values.

Owner names are lazy by default: call `tree.resolve_owners(node_ids)` to resolve
selected identities. Nodes sharing an owner identity reuse its cached display
name. `ScanRequest(..., owner=OwnerMode.EAGER)` resolves names before completion;
`OwnerMode.OFF` omits owner identities and lookups. Unknown POSIX UIDs display as
decimal numbers. A cancelled eager scan skips further owner lookups. Windows SID
resolution remains scheduled for M3.

The scanner integration suite creates every fixture in test-owned temporary
directories. It includes 100,000 siblings, 300 nested levels, a sparse 5 GiB file,
and paths beyond ordinary platform limits. Linux mount tests use a temporary
tmpfs mount and always unmount it during cleanup; CI requires these checks to run.

## Contributing and support

- [Documentation](docs/index.md)
- [Memory budgets, benchmarks, and fixture tools](docs/performance.md)
- [Contributing guide](CONTRIBUTING.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Security policy](SECURITY.md)
- [Report a bug or request a feature](https://github.com/Ahmed41022/disk-analyzer-free/issues)

## License and third-party software

The project is licensed under the [MIT License](LICENSE). PySide6-Essentials and shiboken6 use LGPL-3.0 and remain separate dependencies. Distribution notices and source pointers will accompany packaged builds.

Disk Analyzer Free is not affiliated with or endorsed by JAM Software. TreeSize is a trademark of JAM Software.
