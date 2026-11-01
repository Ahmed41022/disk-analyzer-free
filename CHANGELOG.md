# Changelog

All notable changes to Disk Analyzer Free are documented here. This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Tree rendering reuses frame colours, font and delegate context while preserving standalone rendering, RTL, selection and disabled text.

- Native mock delays now enforce their minimum steady-clock duration; completed GUI tasks and context menus release captured tree owners promptly.

- Linux wheel compilation with older manylinux headers retains statx mount-root detection through the stable UAPI flag and its supported-attribute mask.

### Added

- NTFS mapping-pair decoding with signed-delta and sparse-extent checks, exact bounded output allocation, 1,000 roundtrip seeds and a sanitizer-backed run-list fuzzer.

- Bounded NTFS attribute iteration for timestamps, raw UTF-16 filenames, resident and nonresident streams, sparse/compressed allocation and attribute markers; no parser heap allocations.

- Bounds-checked NTFS v3 record headers and all-or-nothing sector fixups, with synthesized golden records and malformed/unaligned-input tests on every OS.

- Read-only node properties with lazy owner lookup, human flag badges, timestamps and captured volume data; Issues kind filtering, clipboard copy, and exclusive new CSV reports.
- Three-platform Python coverage gates/artifacts and conditional Codecov upload, retaining the existing native model/scanner thresholds.

- Live progress panel with smoothed throughput, shared toolbar controls, elapsed time/current path, bounded estimates, partial-result status, and accessible lifecycle alerts.

- Scan dialog with multiple folder/volume targets, asynchronous directory validation, traversal/exclusion options, atomic saved defaults, and explicit acceptance of forwarded launch targets.

- Main window with lazy Tree/Issues views, background native volume discovery, capacity bars, recent targets, breadcrumbs, live status, and asynchronous scan shutdown.

- Virtual tree table with RTL chevrons, depth percentage bars, original category icons, row navigation, debounced column preferences, and a strict 60-jump repaint budget on ten million native rows.

- A bounded, paged Qt tree table model with correct structural notifications, native column sorting, accessible row descriptions, and selection restoration by node ID.

- A Qt scan controller with asynchronous root validation and result collection, 250 ms progress/diagnostic polling, throttled partial trees, queued startup controls, and recoverable failures.

- Desktop bootstrap with initial Fusion palettes, locale/Qt translator setup, acknowledged single-instance argument forwarding, bounded background tasks, and dated diagnostic logs with copyable error details.

- Native paged tree views with natural sibling sorting, bounded regex/expression filtering, preserved expansion paths, lazy owners, and a typed Python tuple API. Release view budgets and Python sanitizer coverage join the full CI tier.

- Shared typed JSON preferences with atomic saves, corruption backups, v0 migration, and `config get/set/path` commands.

- Three-platform installed abi3 wheel verification with MSVC on Windows, nightly full CI, explicit PR/full test routing, and incremental Linux contributor setup.

- M1 milestone gates for 1,000 generated scan-accounting examples, full native ASan/UBSan checks, and separate 85% model/scanner line coverage.

- Million-node scanner heap budgets, aligned allocation instrumentation restricted to native tests, mock scan benchmarks, deterministic sparse fixture generation, and Google Benchmark regression comparison.

- Parallel POSIX owner resolution with lazy identity caching, eager scan finalization, and coherent reads during owner-name updates.

- Typed Python scanning API with asynchronous controls, shared tree ownership, classified exceptions, GIL-free waits, and lossless native paths.
- Real-filesystem integration coverage for Unicode names, hard links, link cycles, junctions, permissions, mount boundaries, sparse files, deep directories, wide directories, and long paths.

- Initial Python and C++20 package scaffold with a version command and Qt window stub.
- Cross-platform build, test, lint, type, and dependency-policy checks.
- Contributor and project documentation.
- gettext locale negotiation and Arabic, German, and English catalogue scaffolding.
- Segmented C++ storage with indexed, forward, and reverse iteration.
- Chunked native-name storage, extension interning, and owner identity interning.
- Compact tree nodes, contiguous child ranges, native path reconstruction, and platform-aware path lookup.
- Saturating directory aggregation and incremental deletion updates.
- Locale-aware size formatting and parsing with traditional, IEC, and SI units.
- Temporary filesystem fixtures and a pure expected-totals oracle for scanner tests.
- POSIX directory enumeration, native metadata, volume information, and owner lookup.
- Windows batched directory enumeration, verbatim paths, file identities, reparse-point classification, and volume metadata.
- Local and deterministic mock filesystem backends with injected errors, delays, and call counters.
- Compiled path, glob, hidden, and system exclusions with Unicode-aware matching and a sanitizer-backed glob fuzz target.
- Asynchronous C++ walk scanning with progress, pause/resume, cancellation, immutable partial snapshots, and bounded diagnostic queues.
- Hard-link deduplication, explicit symlink/junction traversal with cycle detection, and filesystem boundary controls.
