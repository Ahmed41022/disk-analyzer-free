# Decision log

## D-0001 — 2026-10-30 — Windows stable ABI loading

Question: How should local Windows venv tests load the stable ABI module with the available managed CPython and MinGW toolchain?

Choice: Add the interpreter base directory before loading the native module and statically link MinGW runtime libraries for MinGW builds.

Reasoning: This keeps local package tests runnable without changing the stable ABI module contract or adding runtime dependencies to MSVC builds.

Alternatives: Require a manually configured DLL search path, or bundle compiler runtime DLLs with the package. Both add setup or packaging burden.

Task: T0.1

## D-0002 — 2026-10-30 — CLI exit code names

Question: How should `exit_codes.py` expose values when the plan only specifies the missing-GUI exit status?

Choice: Provide an `ExitCode` integer enum with `SUCCESS = 0`, `ERROR = 1`, and `USAGE = 2`.

Reasoning: Named values make the scaffold's exit statuses clear while preserving Click's specified usage error code of 2.

Alternatives: Use bare integer constants; these provide no additional clarity over the enum.

Task: T0.4

## D-0003 — 2026-10-30 — Staged CI rollout

Question: How can CI stay green while the plan's complete workflow refers to presets, tools, and feature tests that are scheduled for later tasks?

Choice: Start with a required `ci-success` check covering the current lint, C++ build, Python tests, and dependency audits; add the remaining workflow jobs when their planned prerequisites are implemented.

Reasoning: This lets every push be checked without pulling later milestone work forward or hiding missing checks behind skipped jobs.

Alternatives: Add the full workflow immediately, which would fail on files and test suites that do not exist yet; or mark those jobs skipped, which would not verify them.

Task: T0.5

## D-0004 — 2026-10-30 — NumPy license expression

Question: How should the runtime allowlist treat NumPy's compound license expression, which the planned exact allowlist does not include?

Choice: Add NumPy's exact expression `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0` to the exact allowlist.

Reasoning: NumPy is an explicitly required dependency and the listed identifiers are permissive; exact matching keeps mixed expressions from passing through a broad partial match.

Alternatives: Use partial matching, which could admit an expression containing a forbidden license, or remove NumPy contrary to the plan.

Task: T0.5

## Project assumptions A1–A15 — 2026-10-30 — Platform and product contracts

These are the product owner's global assumptions from §0.3 of `docs/PLAN.md`; they remain the source of truth for implementation.

- **A1 — Supported operating systems:** Windows 10 22H2+/11 x86_64 (arm64 best-effort per A12), macOS 13+ arm64 and x86_64, and Linux with glibc 2.35+ x86_64 and aarch64.
- **A2 — Python and ABI:** Python 3.12–3.15 for pip installs; frozen apps bundle CPython 3.14; the extension uses the stable ABI (`abi3`, `cp312`).
- **A3 — Native toolchain:** C++20; MSVC 2022 v143 on Windows, GCC 12+ on Linux, Apple Clang 15+ on macOS; CMake 3.26+.
- **A4 — Size units:** base 1024 by default with KB/MB/GB/TB labels; settings may choose IEC labels or base 1000; CLI options will include `--si` and `--iec-labels`.
- **A5 — Size meaning:** size is logical file length; allocated is on-disk allocation; directory entries add zero to either total.
- **A6 — Link and mount policy:** scans do not follow symlinks or junctions and do not cross file-system boundaries unless requested.
- **A7 — Hard links:** count a file once per scan; later entries are marked `HARDLINK_DUP` and add zero to totals.
- **A8 — Windows streams:** Alternate Data Streams are excluded by default; `include_ads` enables them.
- **A9 — Timestamps:** store seconds since Unix epoch in `uint32`; zero means unknown, pre-1970 maps to 1, and post-2106 clamps to `UINT32_MAX`.
- **A10 — Owner lookup:** resolve lazily for visible rows, owner queries, or exports that include owners.
- **A11 — Scheduling:** use OS schedulers only (Task Scheduler, launchd, systemd user timers, or crontab fallback).
- **A12 — Windows arm64:** produce installers only when PySide6-Essentials has a win_arm64 wheel for the bundled Python; always build the Qt-free pip wheel.
- **A13 — Languages:** en-US is primary; ship Arabic (RTL) and German; use gettext catalogues managed by Babel for CLI and GUI.
- **A14 — Signing:** use Authenticode and Apple notarization only when repository secrets are configured; otherwise builds are unsigned.
- **A15 — GUI toolkit:** use Qt Widgets rather than QML for accessibility, native-feeling tables, and lower memory use.

## Architecture and dependency decisions — 2026-10-30

The product is Python-based with a C++20 core. Per-entry scanning, parsing, tree storage, aggregation, filtering, and other hot paths belong in C++; Python owns orchestration, CLI, and GUI. `dafree.api` is the only Python layer that imports `_core`. Native dependencies are fetched as pinned release archives with SHA-256 hashes; no submodules are used.

The selected stack and licenses are:

| Dependency or component | License | Use / distribution note |
| --- | --- | --- |
| CMake / Ninja | BSD-3-Clause / Apache-2.0 | Build tools, not shipped in runtime packages. |
| scikit-build-core | Apache-2.0 | Python/CMake build backend. |
| nanobind | BSD-3-Clause | Native Python bindings. |
| cibuildwheel | BSD-2-Clause | Wheel build tool, not shipped. |
| NumPy | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | Runtime; exact compound expression is allowlisted by CI. |
| Click / Rich | BSD-3-Clause / MIT | Runtime CLI. |
| platformdirs / Send2Trash / tomli-w | MIT / BSD-3-Clause / MIT | Runtime paths, trash integration, and TOML writing. |
| PySide6-Essentials / shiboken6 / Qt | LGPL-3.0 | Optional GUI dependency; kept separately replaceable and documented per §8.6. GPL-only Qt modules are excluded. |
| Babel | BSD-3-Clause | Build-time `.mo` compilation and translation checks; not a runtime dependency. |
| Unicode 17.0.0 case-fold data | Unicode License V3 | Generated BMP mapping table; source and license are checked in, with no runtime dependency. |
| pytest / pytest-qt / pytest-timeout | MIT / MIT / MIT | Test-only. |
| Hypothesis | MPL-2.0 | Test-only. |
| syrupy / jsonschema / pypdf | MIT / MIT / BSD-3-Clause | Test-only. |
| Ruff / mypy | MIT / MIT | Development checks. |
| coverage.py / gcovr | Apache-2.0 / BSD-3-Clause | Development and coverage checks. |
| pip-licenses / pip-audit | MIT / Apache-2.0 | Development policy and vulnerability checks. |
| MkDocs Material / mkdocs-click | MIT / MIT | Documentation tooling. |
| PyInstaller | GPL-2.0 with bootloader exception | Build-only; onedir distributions keep Qt libraries separate. |
| robin-map / doctest | MIT / MIT | C++ dependency and test framework. |
| zstd / xxHash / BLAKE3 / PCRE2 / Google Benchmark | BSD-3-Clause / BSD-2-Clause / Apache-2.0 or CC0 / BSD-3-Clause / Apache-2.0 | Pinned C++ compression, hashing, regex, and benchmark dependencies. |

The current Python runtime allowlist is checked against the installed runtime set. Development-only dependencies are not shipped. GPL, AGPL, and SSPL runtime dependencies are prohibited.

The repository and package use the name **Disk Analyzer Free**, import name `dafree`, and repository name `disk-analyzer-free`. The product owner selected the descriptive name; the name check recorded in §0.1 found no exact well-known product but noted generic-name search and trademark limitations. Do not rename it. Do not use TreeSize branding, assets, screenshots, wording, or code. The app icon will be original.

The project license is MIT, Copyright (c) 2026 Disk Analyzer Free contributors. This maximizes reuse and is compatible with the chosen dependencies; the accepted trade-off is that MIT permits closed-source forks and does not grant an explicit patent license. PySide6/Qt is the named LGPL-3.0 exception: frozen builds will be onedir, ship Qt and shiboken as replaceable shared libraries, include LGPL/GPL text and source pointers, and not prevent library replacement. The pip wheel does not bundle Qt.

Task: T0.6

## D-0005 — 2026-10-30 — Code of Conduct contact placeholder

Question: Which contact should the code of conduct name before a project support address exists?

Choice: Use `conduct@Ahmed41022.invalid` as an explicit non-deliverable placeholder and direct security reports to GitHub private vulnerability reporting.

Reasoning: No verified conduct mailbox was provided; the reserved `.invalid` domain cannot accidentally route reports to an unrelated person.

Alternatives: Invent a real-looking email address, which could send private reports to an unrelated recipient, or omit the contact required by the plan.

Task: T0.6

## D-0006 — 2026-10-30 — Babel in isolated builds

Question: How can the CMake translation-compilation step find Babel during an isolated wheel build, where development extras are not installed?

Choice: Declare Babel as a build-system requirement and compile each checked-in `.po` catalogue through Python during the CMake build.

Reasoning: The built wheel must contain `.mo` files without adding Babel to runtime dependencies; build-system requirements are installed in the isolated build environment.

Alternatives: Ship precompiled catalogues without a build step, or make Babel a runtime dependency. The former can leave generated translations stale and the latter unnecessarily expands runtime dependencies.

Task: T0.7

## D-0007 — 2026-10-30 — Owner key identity and display

Question: How should the owner table distinguish its UID, SID, and remote-string keys, and what should a duplicate key do when given a different display name?

Choice: Use a tagged key for POSIX UIDs, Windows SID bytes, and remote strings; return the existing ID and retain the first display name for duplicate keys.

Reasoning: The tag prevents identical byte sequences in different identity domains from colliding. Keeping the first display makes an already assigned owner ID stable during a scan.

Alternatives: Use untagged strings, which could merge unrelated identity domains, or replace display names on later calls, which makes display values depend on traversal order.

Task: T1.2

## D-0008 — 2026-10-30 — Unicode simple case folding data

Question: How should extension interning fold non-ASCII BMP letters without adding a runtime library dependency?

Choice: Generate a checked-in lookup table from Unicode 17.0.0 `CaseFolding.txt`, using common and simple one-code-point mappings whose source and target are in the BMP. Keep the source data, generator, and Unicode License V3 with the repository.

Reasoning: The plan requires UTF-8-aware BMP simple folding. A generated table gives deterministic behavior on every supported OS without locale-dependent system calls or a runtime Unicode dependency.

Alternatives: Fold ASCII only, which misses the specified BMP behavior, or add a Unicode runtime library, which adds a dependency outside the plan.

Task: T1.2

## D-0009 — 2026-10-30 — Staged tree metadata and aggregation

Question: How can `Tree` and `TreeBuilder` be introduced in T1.3 while scan metadata and aggregation are assigned to later tasks?

Choice: Keep `ScanMeta` empty until the scan API types are introduced, expose the planned tree and builder signatures, and defer aggregation, deletion, and subtree-replacement definitions to T1.4 and later. `MemoryReport` reports reserved storage by core category and estimates interner storage.

Reasoning: The plan stages these APIs across tasks. Defining scan options and issue types inside the model prematurely would duplicate scan ownership; implementing aggregation early would pull T1.4 into T1.3.

Alternatives: Move scan-owned types into the model now, or omit the corresponding tree API until later tasks, both of which would drift from the planned module boundaries and interfaces.

Task: T1.3

## D-0010 — 2026-10-30 — Saturated totals during deletion

Question: How should incremental deletion update an ancestor whose size has saturated at `UINT64_MAX`?

Choice: Subtract and add the changed child contribution along ordinary ancestor paths. Recompute a saturated ancestor from its direct children before continuing upward. Use a direct segment-index fast path for the usual full-size `SegVector` segments, with binary-search fallback after `shrink_last` followed by an append.

Reasoning: Saturating addition cannot be reversed by subtraction; the recompute path preserves the result of a fresh aggregation. The segment lookup avoids repeated binary searches in the 10-million-node aggregation pass while preserving random access after shrinking.

Alternatives: Always reaggregate the whole tree after deletion, or subtract from saturated totals and risk incorrect values.

Task: T1.4

## D-0011 — 2026-10-30 — Unit API and Python parity

Question: What are the unspecified C++ `UnitMode` and `UnitStyle` shapes, and how can the required Python JSON parity test exercise the C++ formatter?

Choice: Use `UnitMode` for auto, bytes, and fixed powers; `UnitSystem` for traditional binary labels, IEC, and SI; and `UnitStyle` for the system and caller-supplied decimal separator. Bind these types through nanobind and expose matching Python enums and a frozen style dataclass from `dafree.api`. Parse decimal values with checked integer arithmetic and at most nine fractional digits.

Reasoning: The style object makes locale behavior explicit and deterministic. The Python parity test calls the native formatter and parser through the typed facade, so its JSON table checks the same implementation that GUI delegates will use.

Alternatives: Depend on process locale, use floating-point conversion near `UINT64_MAX`, or keep a separate Python formatter whose output could diverge from C++.

Task: T1.5

## D-0012 — 2026-10-30 — Fixture oracle paths and capability handling

Question: How should the testkit represent the fixture root, unreadable directory contents, links, and unavailable OS features in expected results?

Choice: Use an empty string for the root and POSIX-style relative keys for descendants. Count each file or hard-link directory entry as a file; in dedup mode only the first regular file contributes bytes and each extra hard link increments `hardlink_dups`. Treat unreadable directory contents as unseen. Keep links unfollowed by default. Create every fixture inside a test-owned temporary directory and expose observed feature support through `Caps.require`, which fails in CI when `DAFREE_REQUIRE_ALL_CAPS=1`.

Reasoning: The keys can be compared independent of the host OS. The totals reflect what a scanner can observe without access or link following. Explicit capability checks keep platform limitations visible, while cleanup restores directory permissions before removing the owned fixture. Linux long paths use directory-relative operations so the preset can exceed `PATH_MAX`. On an elevated Windows CI runner, `icacls` successfully applies the deny ACE but directory enumeration can still succeed; the Windows fixture test checks ACL setup and cleanup, while POSIX tests also assert that enumeration is denied.

Alternatives: Use absolute platform paths in the oracle, count hidden unreadable children, or silently skip unsupported features in CI; these would make cross-platform assertions or failure diagnosis unreliable.

Task: T1.6

## D-0013 — 2026-10-31 — Platform metadata prerequisites

Question: Where should the platform enumeration types live before the backend and scan tasks introduce their consumers, and how should missing bulk metadata be handled?

Choice: Introduce `platform.hpp` with the planned entry, listing, issue, volume, and platform interfaces needed by T1.7. Add an `access_denied` marker to `RawEntry` for the specified per-entry permission failure. Linux uses `getdents64` and `statx`, with `fstatat` fallback on `ENOSYS`. macOS requests bulk metadata and falls back to `fstatat` for entries with unsupported attributes, or reopens the directory for `readdir` when bulk enumeration is unsupported.

Reasoning: Enumeration needs these shared types before `FsBackend` exists. Keeping one definition avoids incompatible duplicates in later tasks. Optional birth times remain absent when unsupported, and bulk fallback preserves metadata and raw names across filesystems.

Alternatives: Delay the types until T1.9, duplicate them privately, or reject filesystems that do not return every bulk attribute.

Task: T1.7

## D-0014 — 2026-10-31 — Windows metadata and serial lifetime

Question: How should Windows walk mode obtain reparse tags on the legacy listing fallback and retain volume identities without stale mount information?

Choice: Use extended directory records normally and legacy records when the filesystem rejects the extended class. Query legacy reparse tags with `FindFirstFileW` only for reparse entries. Inspect mount-point reparse data through a no-follow handle to distinguish volume mounts from junctions; cloud entries never take that path. Query the directory handle's volume serial once per listing and reuse it for every returned entry, rather than keeping a process-wide per-volume serial cache. Preserve UTF-16 names through explicit WTF-8 conversion, including lone surrogates.

Reasoning: Legacy records lack the extended reparse tag. The fallback reads metadata without opening ordinary files or cloud data. Scoping the serial to the live directory handle avoids stale identities after a volume is remounted and keeps the per-file loop free of serial queries. Native tests clean up their own temporary trees with verbatim Windows APIs because MinGW filesystem cleanup hangs on paths beyond MAX_PATH.

Alternatives: Open every file for metadata, follow reparse points to classify them, or retain serials across mount changes.

Task: T1.8

## D-0015 — 2026-10-31 — Mock filesystem shape and staged backend hooks

Question: What concrete shape should the unspecified `MockSpec` and `DirHint` types use, and what does a vanish-after-listing fault represent?

Choice: Represent mock entries as native paths plus `RawEntry` metadata. Index direct children once, assign deterministic file identities when omitted, and keep faults and owner names in explicit tables. A vanish fault omits the affected child with a `NotFound` issue during its parent's listing and makes later stats fail, modeling disappearance between OS enumeration and metadata lookup. Count every attempted directory read atomically and apply the configured delay to each operation. Keep `DirHint` empty until traversal hints are needed; forward-declare fast-scan types. The mock reports local semantics. Local Windows owner resolution returns no value until the SID implementation in T3.6.

Reasoning: The plan specifies behavior but not these type layouts. A precomputed child index avoids repeatedly searching the whole mock tree, and immutable metadata plus synchronized vanish state supports concurrent scanner workers. The staged hooks preserve the planned backend signatures without introducing later scan or MFT features.

Alternatives: Rebuild directory contents by scanning every mock path on each call, depend on real filesystem failures, or introduce later scan implementations early.

Task: T1.9

## D-0016 — 2026-10-31 — macOS thread-library availability

Question: How should concurrency tests run on the supported macOS runner when its Apple libc++ does not expose `std::jthread`?

Choice: Use `std::thread` and explicit joins in the backend counter test. Retain the same concurrent operations and assertions. Apply explicit RAII joining if the scanner needs a compatibility implementation on this standard library.

Reasoning: The CI compile logs show that the supported Apple toolchain accepts C++20 but lacks `std::jthread`. This test needs concurrent reads and completed workers, without stop-token behavior. Explicit joins provide those semantics on all three operating systems.

Alternatives: Disable the macOS test, require a different standard library, or omit concurrent coverage.

Task: T1.9

## D-0017 — 2026-10-31 — Glob semantics and bounded matching

Question: Which unspecified gitignore-style details should exclusion globs support, and how should matching avoid recursive backtracking?

Choice: Match `*` and `?` within a path component, `**` across separators, and `**/` across zero or more directory prefixes. Support negated character classes and backslash escapes. Leading `/` anchors a glob to the scan root; trailing `/` limits it to directories. A trailing `/**` also prunes its directory prefix. Use Unicode code points with the existing BMP simple-fold table on Windows and macOS, preserve invalid native bytes, and leave POSIX byte names unnormalized. Compile patterns once and evaluate an iterative state machine with stack storage for ordinary patterns and linear heap storage for longer ones. Excluded absolute paths match complete subtrees by component boundaries.

Reasoning: These choices make zero-directory `**/` cases and directory pruning deterministic. Iterative matching bounds work by pattern length times input length instead of exponential backtracking and avoids per-entry allocations for ordinary patterns. `scan.hpp` introduces exclusion types before the engine task because the planned class needs them. The development-only fuzz target uses Clang/libFuzzer (Apache-2.0 WITH LLVM-exception), with address and undefined-behavior sanitizers; no runtime dependency is added.

Alternatives: Use platform-dependent filesystem glob APIs, recursively backtrack, compare UTF-8 one byte at a time, or keep excluded directory placeholders in the scan tree.

Task: T1.10
