# Changelog

All notable changes to Disk Analyzer Free are documented here. This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Linux wheel compilation with older manylinux headers retains statx mount-root detection through the stable UAPI flag and its supported-attribute mask.

### Added

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
