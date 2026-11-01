# Decision log

Entries are newest-first. Product-owner overrides take precedence over earlier choices.

## Pending CI jobs

This inventory covers every §7.3 job absent from `ci.yml`. Remove a row when its job lands. Existing jobs: `lint`, `cpp`, `python`, `sanitizers`, `coverage`, `wheels`, `audit`, `docs`, `ci-success`; additional `tsan`, `fuzz`, and `view-perf` jobs retain their separate required gates.

| Missing §7.3 job | Task that will add it | Remaining prerequisite / scope |
| --- | --- | --- |
| `frozen-smoke` | T10.1, using T4.14's deferred self-test hook | Build the actual frozen bundle, verify CLI/GUI fixture totals and bundle size. |
| `bench` | T2.2, after M4-core | Add executable CLI wall-time/RSS comparison to existing `bench_compare`; run on main/nightly under D-0030 until M4-core completes. |
| `pr-title` | T0.5 follow-up after these prerequisites | Enforce Conventional Commits on PR titles; no feature prerequisite. |

Partial job scope still pending (these are existing jobs, not missing rows): `lint` needs automated clang-format/typos (T0.5 follow-up); `cpp` needs compiler caches/clang-tidy (T0.5 follow-up); `coverage` needs cross-OS Python coverage and Codecov upload (T4.13 follow-up); `python` needs SMB/scheduler integration in T9.5–T9.7. Its GUI scroll performance lands in T4.5. Native model/scanner line thresholds remain 85% each. This inventory does not claim the unimplemented packaging or analysis checks are complete.

## D-0046 — 2026-11-01 — Repaint profiling and local Release compiler correction

Question: How should the table meet the unchanged repaint budget, and how should local Windows Release validation handle an observed compiler crash?

Choice: Profile the actual ten-million-row viewport without reducing its size, jumps, or thresholds. Avoid generic unsupported-role probes and QVariant round trips in Python delegates by sharing the model's bounded tuple pages and display formatting directly. Cache the model's notified row count, keeping strict Qt before/after notifications. Add `row_data` and `display_value` as documented GUI model helpers. Iterate only the viewport's row and column ranges in `TreeTable.paintEvent`, using Qt's own geometry and delegates directly. Qt continues to own scrolling, selection, headers, navigation, and accessibility. Test complete visible-cell coverage and exact Qt rectangles in both directions, plus clearing after collapse.

Choice: Paint supplied palette backgrounds/text directly, retaining the native focus primitive, mirrored chevrons, depth bars, and icons. Prepare the frame font and row backgrounds once, avoiding redundant per-cell font setup and fills; standalone delegates retain their complete paint path. Normalize style-state masks to primitive integers in the paint path, avoiding repeated Python flag allocations. Bound prepared plain-text layouts to 256 per delegate; invalidate them on font change and key them by text, width, and direction. Keep an owned font copy: the font wrapper borrowed from a style option expires after painting. Tests cover that lifetime, cache bounds, selected/alternate colours, focus, and lazy owner resolution when its column is shown. No garbage collection is disabled or excluded from measured frames.

Choice: Correct the performance test's duplicate widget disposal: it manually closes/deletes the table, so do not also register it for pytest-qt deletion. Configure the Windows offscreen Qt plugin to read existing system fonts from `SystemRoot/Fonts`; require a nonempty Qt font database in the performance test on every OS, avoiding a measurement with missing-font boxes. No font is copied or bundled. Retain every assertion and require a real paint event for every measured jump. Record paint counts as well as all durations; no samples are dropped. Explain these fixture corrections in the task commit.

Choice: Local MinGW GCC 15.1.0 crashes in its LTO alias pass on nanobind's `wrap_move` during Release linking. Disable only `_core`'s Release IPO for that exact optional compiler/version combination, preserving Release optimization. All supported compilers, including Windows MSVC and its wheel jobs, retain LTO. The same cached local Release build succeeds after this narrow workaround. No compiler or dependency is changed.

Choice: Make Linux QA fonts explicit with the existing system package `fonts-dejavu-core` (upstream DejaVu 2.37; observed Ubuntu package 2.37-8). Its installed copyright declares the Bitstream Vera font license and public-domain DejaVu changes. It supplies real glyphs to offscreen tests; no font is copied into the repository or redistributed in application artifacts. Windows/macOS use their existing OS fonts. This is a test-system prerequisite, not an application dependency.

Reasoning: Profiling exposed repeated native/Python callbacks in generic cell painting, not a scanner bottleneck. Reusing bounded pages and painting only Qt's visible geometry removes those callbacks while preserving behavior. Owned Qt values avoid invalid borrowed wrappers in caches. A toolchain internal compiler error warrants a narrowly identified build workaround, not a test skip or a lower performance threshold.

Task: T4.5

## D-0045 — 2026-11-01 — Virtual table ownership, preferences, and repaint measurement

Question: How should the table persist columns and expose navigation/actions before deferred settings, file actions, and analysis, and how should the required large-tree repaint test run?

Choice: Use `TreeTable(model, settings, parent=None, *, paths=None)`. Own an otherwise unparented model and retain the table's Python selection-model wrapper so its weak model registration survives resets. Use fixed global row height and per-item scrolling, without resizing, moving, hiding, or allocating individual vertical-header sections. Enabling header sorting preserves the existing native sort; an unchanged sort is a no-op instead of rebuilding millions of rows.

Choice: Header visibility, width, and order update the shared `Settings.columns`, retaining widths while hidden and preserving preferences absent from a subset model. Debounce atomic application-settings writes for 250 ms when paths are supplied, and flush pending changes on close. Without paths, update shared preferences without creating files; the owning main window can persist them. A dirty flag covers timer callbacks, whose single-shot timer is already inactive when it fires. Do not write configuration on every drag movement.

Choice: Implement the specified physical Right/Left expansion/parent navigation, one-level `*`, and ordinary row/page keys. Qt's table default Home/End moves between columns, so override them to reach first/last rows. Enter and Menu emit node-ID action requests for later properties/context wiring; they do not implement deferred file actions. Use Python-object signals for unsigned node IDs. Draw category icons from original geometric code, mirror chevrons and hit regions in RTL, and keep numeric selection contrast. Categories remain `Other` until T2.5; no classification algorithm is brought forward.

Choice: Add `_core.testing.TreeBuilder.flat(root, visible_rows)` in a native testing namespace, exposed through `api.testing.TreeBuilder`. The namespace is a nested binding class so generated abi3 stubs retain its exact typed path without adding a Python package under the extension. The builder creates an exactly sized flat tree in C++ memory with contiguous temporary names and descending file sizes; it uses no MockBackend, Python per-node loop, or filesystem enumeration. The supplied synthetic root is inside each test's temporary directory. Normal tests verify shape, aggregate size, invalid counts, and no filesystem changes.

Choice: The slow performance test uses the actual Fusion bootstrap/stylesheet, 1280×720 table, exactly ten million visible rows, and 60 distinct jumps including both ends. Each measured interval includes scrolling, synchronous viewport repaint, and pending Qt events. Require an actual paint event in every sample. Record all 60 durations, median, and nearest-rank p95 in JUnit; retain the unchanged median ≤16.7 ms and p95 ≤33 ms assertions. Build a Release extension before the explicit CI performance step: Linux Python 3.12 on main, plus Windows/macOS on nightly. PRs never run it; heavy checks remain main/nightly only. No new dependency is introduced.

Reasoning: Explicit ownership avoids Qt wrapper lifetime surprises, and stable row geometry keeps viewport work independent of total row count. Debounced application-owned persistence keeps UI interaction responsive. Measuring actual paint delivery prevents a hidden/offscreen no-op from passing the budget. The fixture namespace is testing infrastructure required by the plan, separate from production scanning and future analysis.

Task: T4.5

## D-0044 — 2026-11-01 — Native structural previews and Qt model selection

Question: How can Qt receive correct before-change row ranges when the planned native expansion methods return counts only after mutation, and how can an otherwise standalone model retain table selection?

Choice: Add pure native `expansion_count(id)` and `collapse_count(id)` queries. They count eligible descendants or the visible removal span without sorting, populating sibling caches, resolving owners, or modifying expansion preferences. The model brackets native mutation with `begin/endInsertRows` or `begin/endRemoveRows`, rather than changing the tree before notifying Qt. Add native `expand_children(id)` for the specified one-level operation, avoiding a Python traversal. Preserve existing descendant expansion preferences. Update §2.5's interface accordingly. These additions do not change existing budgets or introduce a dependency.

Choice: Retain the source facade as the read-only Python `TreeView.tree` property for individual path/parent lookups. Add `TreeTableModel.bind_selection_model` so the table can explicitly register its external Qt selection model. Hold that registration weakly and restore visible selected/current node IDs after reset, dropping filtered-out nodes. A failed option change still ends the reset and restores the previous selection. Cache only fifty 200-row native pages, clear them on structural changes, and return immediately for unsupported Qt roles.

Choice: Keep the native 15-field tuple for `ROW_ROLE`; an actual `QModelIndex.data()` regression verifies the Qt boundary preserves its surrogate string and uint64 maximum size. Escape surrogates only in display/accessibility/tooltip strings using the existing diagnostic display helper. Use native flags for file/folder descriptions. Extension categories remain `Other` until deferred T2.5. Tests dispose Qt models, signal connections, and strict model testers before native binding leak checks.

Reasoning: Qt requires accurate old row counts during its about-to-change signals. Preview queries satisfy that contract while retaining native ownership of enumeration and sorting. Selection is owned by a view, so explicit registration avoids searching global widgets or inventing a second selection store. No user-file action or later milestone algorithm is introduced.

Task: T4.4

## D-0043 — 2026-11-01 — Scan-controller startup, failures, and partial trees

Question: How should the selected polling interface avoid GUI blocking and report failures before deferred settings/main-window tasks?

Choice: Run native `start_scan` as well as `take_result` through `TaskRunner`. Inspection found root `stat_root` and volume discovery are synchronous in the native constructor; releasing the GIL alone would still block Qt's event loop. Snapshot the request before submission, retain pause/resume/cancel requests made during startup, and reject a second start while startup, scanning, or final collection is pending. Final result consumption and failure cleanup wait/join only in a worker.

Choice: Add `failed = Signal(str)` to the planned controller interface and update T4.3's plan declaration. Startup and result errors cannot be represented as `ScanResult` without weakening the typed `finished` contract. Reset to idle before emitting either terminal signal, so a listener may start another scan. Distinguish this controller's generations/jobs when using a shared runner. Injection of the existing native `Backend` and an optional shared runner is a constructor/testing seam, not a Python filesystem backend.

Choice: Poll every 250 ms, drain at most 1,000 live issues per tick, forward notices, and request partial trees every fourth tick with a monotonic one-second lower bound. `partialTreeReady` carries the existing public `api.Tree` facade over its shared native handle; do not add a second Python TreeHandle class. Deliver terminal progress and a final diagnostic drain after background result collection and before `finished`, covering diagnostics that arrived at the completion boundary. Unexpected polling failure cancels/consumes the handle in a worker before releasing it.

Choice: Use one active scan per controller, with one controller intended per window. The persisted settings schema defines no parallel-scan switch, and its dialog remains deferred, so do not invent that setting now. Main-window buttons/actions remain later M4-core tasks. Extend the existing GUI smoke file with bootstrap plus one real test-owned temporary-file scan so Windows/macOS PR checks exercise the new path without running heavy fixtures. Native delayed mocks cover the named progress/cancel/pause acceptance tests. Tests explicitly flush Qt DeferredDelete events when disposing controllers, preventing test-owned backends from surviving until native binding shutdown; no leak warning is suppressed.

Reasoning: These additions fill the interface's missing asynchronous failure path and preserve the owner-approved milestone order. All tree enumeration stays in C++; the controller only polls the public API and passes shared snapshots onward. The one-second bound covers timer jitter as well as nominal four-tick scheduling.

Task: T4.3

## D-0042 — 2026-11-01 — Bootstrap before deferred GUI settings and actions

Question: What should application startup implement before the deferred settings/RTL tasks and later main-window actions?

Choice: T4.2 applies Fusion, the persisted initial light/dark/system palette, gettext locale, available Qt base translators, and initial layout direction. Live theme switching, settings dialogs, complete GUI translations, and RTL refinement remain deferred. Every new custom UI string uses `_()`. Public `main(argv)` takes explicit arguments after the executable name; `dafree gui` passes an empty list so its Click subcommand token is not forwarded as a target. Validate the optional Qt runtime before reading user configuration, including when the bootstrap module is cached.

Choice: Use a `QLockFile` in the application data directory and a user-access-only `QLocalServer` endpoint. Hash the data-directory identity into a short endpoint name in Qt's temporary directory (named pipe on Windows), avoiding Unix socket path limits. Messages are bounded ASCII-escaped JSON arrays, retaining native surrogate characters without normalization. Use a Python-object signal to preserve them across Qt. The first instance acknowledges delivery before the second exits. Bootstrap activates the first window and retains its latest launch arguments; actual target opening belongs to later main-window actions. Tests exercise actual second processes while servicing the first process's Qt event loop, with both config and IPC locations in test-created temporary directories.

Choice: Disable age-based lock expiry with `setStaleLockTime(0)` while retaining Qt's PID/host checks. This follows [Qt's long-lived lock guidance](https://doc.qt.io/qt-6/qlockfile.html#details). The live-lock integration test deliberately ages the lock file before launching its peer; no test waits for an expiry timeout or bypasses locking.

Choice: Background callables use an owned `QThreadPool` capped at four workers. Internal completion/failure slots run on the owning GUI thread before emitting the specified public signals; arbitrary task IDs, including unhashable objects, are preserved. Native calls remain behind the existing public API. Unhandled main/thread Python exceptions are logged and delivered to a non-blocking error dialog with Copy details.

Choice: Escape surrogate code points in displayed exception text before transporting it through Qt string signals. A regression reproduced `bad-\ud800` being truncated to `bad-` by QString conversion; the GUI/log now retain the explicit `\ud800` diagnostic spelling. Keep pending launch arguments in a Python list on the window, avoiding QVariant string-list conversion. Native paths, result objects, and forwarded argument lists remain unchanged and lossless. This is display formatting, not filename normalization.

Choice: Select the dated UTF-8 log at launch, keeping a session's diagnostics together in that file. Keep its launch-date log plus six newest other dated regular app logs, including when the clock moved backward. No runtime rollover timer is specified or introduced. Retention and stale IPC/lock cleanup are application-owned housekeeping, separate from operations on user-selected scan targets. Touch only the named application namespace; reject linked data/log directories and today's linked log path, leave old links/unrelated files untouched. M8's explicit confirmation/trash/dry-run and fd-relative no-follow C++ remover requirements remain mandatory for user-file actions. Initial path/permission failures propagate rather than silently redirect application storage. Attach bootstrap state to the QApplication only after successful initialization, so a failed log open leaves no partial object behind.

Reasoning: These choices implement the selected bootstrap task without enabling deferred settings, action, or localization features. A delivery acknowledgment prevents a short-lived second process from losing its message before the first accepts it. Qt wraps Fusion in QStyleSheetStyle when CSS is active; the palette test temporarily removes CSS to inspect the actual base style rather than incorrectly expecting the wrapper's object name to be Fusion.

Task: T4.2

## D-0041 — 2026-11-01 — Enforce the owner's main/nightly-only heavy tier

Question: Should manual branch or merge-queue runs inherit all heavy jobs just because they are not PR events?

Choice: No. Until M4-core completes, full CI is enabled only when the ref is `refs/heads/main` or the event is the nightly schedule. Main manual runs are full; manual branch and merge-queue runs use the same light tier as PRs. Keep lint, the full Linux correctness suite, cross-platform C++ correctness, and Windows/macOS GUI smoke required on that tier. Retain every heavy job, wide fixture, performance threshold, and sanitizer assertion on main/nightly. The aggregation gate permits only the named full-tier skips when the full-tier flag is false; a skipped job on main/nightly still fails the gate.

Reasoning: D-0030's broad non-PR guard also enabled manual branch validation, exceeding the owner's explicit main/nightly-only instruction. Two one-off T4.1 branch runs exposed the D-0040 fixes, but do not justify changing that instruction for later groups. Correct both workflow routing and the decision log rather than treating the earlier assumption as authorization. This entry supersedes D-0030's manual-branch and merge-queue full-tier exceptions.

Task: T4.1 CI verification / owner-requested temporary policy

## D-0040 — 2026-11-01 — T4.1 full-CI fixture and build corrections

Question: How should full validation exercise invalid native names on macOS and build the sanitizer extension on a fresh runner?

Choice: APFS rejects the invalid UTF-8 filename used by the view codec test (`EILSEQ`). Keep the same row, option-roundtrip, glob, and regex assertions on every OS. On macOS supply that name through the native MockBackend, representing an imported or remote tree; retain real filesystem creation/scanning on Linux and Windows. This fixes an incorrect test-fixture assumption without skipping or weakening a test.

Choice: Let pip install the build requirements declared in `pyproject.toml` in its normal isolated build environment for the CI sanitizer extension. Its previous `--no-build-isolation` command failed because the dev lock does not install scikit-build-core. Keep the instrumented native build directory inside the repo and retain every sanitizer test and option. No new runtime dependency is added.

Reasoning: The first full branch run exposed these two issues after the PR-tier checks passed. A filesystem's filename restrictions do not limit which lossless names the native view can receive. Honoring declared build requirements makes a fresh CI build reproducible without assuming a contributor's existing environment.

Task: T4.1 CI verification

## D-0039 — 2026-11-01 — PCRE2 activation and view verification

Question: How should native regex filters meet their compilation limit and run against lossless filenames?

Choice: Activate the already pinned **PCRE2 10.46**, **BSD-3-Clause WITH PCRE2-exception**, for the view evaluator. This is the exact SPDX expression in its upstream `LICENCE.md`; correct the earlier abbreviated dependency label and allow only this exact expression in the license checker. Link only the static 8-bit library with Unicode support, three-byte internal links, PIC, and JIT disabled. Keep upstream tools, archives, headers, and manuals out of application wheels; install that license as `dafree/licenses/PCRE2.txt`. No new dependency is introduced beyond the plan's declared dependency.

Choice: Limit the pattern and live compilation allocations to 1 MiB, including compiler workspace; use case-insensitive UTF/UCP matching with invalid-subject-UTF support so valid filename fragments remain matchable around native invalid bytes or lone surrogates. Invalid patterns and exhausted compilation/match budgets raise explicitly. Matching has bounded heap and step counts. Each filter worker reuses its match and long-glob workspace; the scanner's existing glob interface remains unchanged.

Choice: The `sanitizers` job retains the full native GCC ASan/UBSan suite with leak detection, and adds Python unit/integration suites against a Clang-instrumented extension with its matching ASan runtime preloaded. CPython leak detection is disabled as specified in §7.3. The Qt pytest plugin is disabled for those non-GUI suites; no test is deselected for that reason. Existing TSan and fuzz gates remain required; TSan now also runs the view suite. A separate release `view-perf` job enforces the unchanged strict 150 ms and 2 ms budgets on main/nightly, with five repetitions and reports retained as artifacts. Heavy jobs stay off PRs under D-0030.

Reasoning: PCRE2 is the planned permissively licensed native regex engine. Explicit resource failures avoid silently hiding matching files. Real cold-cache expansion and a tail window in exactly ten million visible rows exercise the acceptance criteria without timing fixture generation or warming the sibling cache. The full CLI comparison `bench` job remains pending T2.2.

Task: T4.1 / assigned sanitizer follow-up

## D-0038 — 2026-11-01 — Tree-view ownership and reordered analysis prerequisites

Question: How should T4.1 expose lazy owners and row categories before deferred analysis and GUI tasks?

Choice: Preserve the planned immutable-snapshot `TreeView(tree, options)` constructor, whose owner names come from cached metadata. Add an overload taking the original `TreeHandle` and backend; Python always uses this overload, retaining coherent reader locks and lazy owner context after the original facade is dropped. Add a copying `options()` accessor (Python property) so later sort handlers preserve filters and unrelated options. These additions are reflected in §2.5. Do not mutate a genuinely const tree through the snapshot constructor or create a separate lock for an existing mutable owner context.

Choice: Stage only the shared `TimeField` and `ExtCategory` declarations in `analysis.hpp`/API types. Extension categorization and other T2.5 algorithms remain deferred; row category is `Other` until that task. No query-text parser or GUI feature is included. Filters match names against the target basename and path globs against its full path. Unknown times fail ordered comparisons and may be selected by `Eq 0`. Registered owners with empty unresolved placeholders display as `None`; only cheap-predicate candidates force owner lookup.

Choice: Keep expansion preferences when collapsing or changing filters. Eligible ancestor rows are retained but filtering does not automatically expand paths. Store visible references in indexed blocks of 512 with an implicit treap and direct node-to-block mapping, avoiding shifts of every subsequent visible row on expansion. Cache sibling sorts in the planned 256-entry LRU. Use the shared analysis `ThreadPool` singleton (one worker per logical CPU) with disjoint-word filter writes; small filters run inline. Every binding that can block releases the GIL, and `rows()` constructs the planned 15-field tuples directly in C++.

Choice: Register native worker shutdown with Python's `atexit` before DLL unloading. Joining live workers from a Windows DLL static destructor can deadlock under the loader lock; a subprocess regression must complete both filtering and interpreter exit. Native-only programs retain ordinary RAII shutdown.

Reasoning: Owner resolution already mutates through the scan's `TreeHandle`; retaining that handle prevents competing reader locks and stale ownership lifetimes. The accessor avoids Python duplicating mutable option state. Staging required value types supports the owner-approved order without implementing deferred analysis. Indexed blocks make deep scrolling and local expansion independent of the length of the visible tail.

Task: T4.1

## D-0037 — 2026-10-31 — T2.7 settings before the CLI framework

Question: How should T2.7 run before deferred T2.1, and what fills the unspecified nested settings and v0 schema?

Choice: Register only `config get/set/path` on the existing Click scaffold; keep its existing exit enum until the single `Exit` replacement in T2.1. Use typed JSON-native dataclasses for columns, scan defaults, duplicate defaults, window state, and treemap options. Column IDs mirror the nine T4.5 columns; owner and extension start hidden. Duplicate filter defaults persist nullable query text, with parsing/evaluation deferred. These models store preferences only and implement no duplicate, treemap, or portable features.

Choice: Treat unversioned/v0 JSON as the same named fields without schema metadata; retain known values, supply typed defaults, and save as v1 on the next explicit write. Reject unknown fields, bool-as-int errors, invalid enum choices, non-finite numbers, invalid native numeric ranges, nonpositive column/window dimensions, duplicate column IDs, and empty column lists. Keep the first ten recent targets. Future schema versions raise without renaming or overwriting their file. Corrupt JSON/UTF-8/type data is renamed to a timestamped backup, adding a suffix if a backup already exists. JSON escapes preserve raw filesystem surrogate characters.

Choice: The portable path detector remains a stub with the planned signature; explicit portable requests fail rather than silently write outside portable storage. The documented test-only `DAFREE_CONFIG_DIR` override contains all application directories. Default paths use platformdirs with `appauthor=False`. No directories are created by detection or `config path`.

Reasoning: The owner explicitly selected T2.7 before T2.1 and deferred the algorithms/portable tasks. A strict shared schema gives CLI and GUI one format without adding another framework. There is no shipped legacy settings format to infer beyond v0's missing version, so the migration avoids invented renames. Atomic sibling-file replacement follows a flush and fsync; failed saves preserve the previous document and remove only the newly created temp file.

Task: T2.7

## D-0036 — 2026-10-31 — Linux setup and installed catalogue data

Question: Which pip installation mode makes the Linux quick setup work on a clean checkout while keeping native rebuilds incremental?

Choice: Use an ordinary `pip install ".[gui]" --no-build-isolation -Cbuild-dir=build/python-dev`, with FetchContent cached under ignored `.deps`. Repeat the pip command after edits. Preserve the same Python environment path when recreating it. On WSL the Python environment may live on the Linux filesystem; native build and FetchContent paths remain inside the repository. Leave editable catalogue lookup as a documented follow-up for deferred T4.12.

Reasoning: Inspection of a fresh editable installation confirmed gettext resolves `src/dafree/i18n/locales`; a clean checkout has no tracked compiled `.mo` files there. Ordinary installation loads the catalogues produced by the build from the installed package, without copying generated data into the source tree. This changes the setup recipe rather than skipping translation tests. Different interpreter paths can legitimately invalidate scikit-build's native cache.

Task: T0.5 Linux contributor setup follow-up; T4.12 editable catalogue lookup

## D-0035 — 2026-10-31 — manylinux statx header compatibility

Question: How should Linux wheels retain mount-root detection when manylinux_2_28 headers omit `STATX_ATTR_MOUNT_ROOT`?

Choice: Interpret the stable Linux UAPI mount-root attribute value `0x00002000` through a small private compatibility header, intersecting the attributes with the kernel's supported-attribute mask. Assert agreement with the named constant when newer headers provide it. Add a native regression test that needs no Linux headers and runs on all three OSes. Keep the directory-fd-relative syscall and fstatat fallback unchanged.

Reasoning: The first real manylinux wheel build exposed this missing-header constant; Windows MSVC and macOS wheels already passed installed-wheel testing and ABI audits. Disabling mount detection or raising the Linux baseline would change the plan's behavior. The constant is a public ABI value, not copied implementation code. This is a build compatibility fix, not a change from path-based to fd-relative metadata, so the requested conditional before/after enumeration benchmark does not apply.

Task: T0.5 wheel CI follow-up / T1.7 compatibility

## D-0034 — 2026-10-31 — Prerequisite PR and persistent Linux builds

Question: How should the requested prerequisites fit the new PR groups and Linux setup?

Choice: Put the CI/doc prerequisites in a separate `ci-wheels-and-m4-core-policy` PR before `[T2.7]`. After each group passes its required PR checks, merge its PR to main, preserving the task commits, and verify main's full CI tier before the next group. This honors the owner's earlier request for main commits together with the new one-PR-per-group requirement. Linux quick setup uses `build/python-dev` and `.deps` inside the repository, both ignored, with the same interpreter path when recreating the environment. CMake explicitly maps the `FETCHCONTENT_BASE_DIR` environment variable to its cache variable when no CMake value was supplied.

Reasoning: Prerequisites must be verifiable before M2. Persistent CMake and FetchContent directories avoid repeated downloads and native compilation after a fresh pip environment. Manual full CI validates the prerequisite branch before T2.7 starts.

Task: T0.5 follow-up / T2.7 prerequisites

## D-0033 — 2026-10-31 — Deferred exit enum correction

Question: When should the scaffold's `ExitCode` be replaced?

Choice: In T2.1, replace it with the plan's single `Exit` enum and update every consumer; retain no compatibility enum or alias. T2.1 stays deferred until after M4-core.

Reasoning: This records the owner's explicit correction without implementing a deferred task early. D-0002 is superseded when T2.1 lands.

Task: T2.1

## D-0032 — 2026-10-31 — Descriptor-relative metadata and destructive operations

Question: Does POSIX `read_dir` resolve per-entry metadata relative to its open directory, and may M8 reuse the path helpers?

Choice: Verified Linux `add_entry` calls `stat_entry_at(fd, name, false, ...)`, whose `statx` syscall receives that dirfd and whose fallback uses `fstatat(dirfd, name, ..., AT_SYMLINK_NOFOLLOW)`. macOS uses `getattrlistbulk(fd, ...)` and the same fd-relative fallback for omitted metadata. No enumeration change is needed, so there is no before/after `bench_compare` delta to report. M8 delete/move must use only the fd-relative, no-follow C++ remover. Never reuse path-based `stat_nofollow`, `stat_follow`, or removal helpers for destructive actions.

Reasoning: An anchored directory descriptor prevents per-entry path re-resolution. Path-based scanning helpers are not a safe basis for destructive operations, even when the final component is no-follow. M8 retains trash by default, explicit confirmation, and dry-run requirements.

Task: T1.7 verification / T8.1–T8.3 safety constraint

## D-0031 — 2026-10-31 — robin-map dependency

Question: Which robin-map dependency is used and why?

Choice: Tessil robin-map **1.3.0**, **MIT**, fetched from the pinned release archive with the SHA-256 in `cmake/Dependencies.cmake`. Use its flat hash sets for scan identities and cycle detection; nanobind also consumes the pinned dependency.

Reasoning: Open addressing avoids per-entry node allocations in the scanner's identity sets and helps meet the existing memory budgets. The permissive license is compatible with the MIT project. No proprietary code is used.

Task: T1.12 / dependency documentation follow-up

## D-0030 — 2026-10-31 — CI tiers through M4-core and wheel gate

Question: Which checks run on PRs while the reordered core UI work is underway?

Choice: PRs require lint, the full Linux suite except the explicitly main-only wide 100k fixture/performance categories, and C++ correctness plus GUI smoke on Windows/macOS. Retain all assertions and thresholds. Main, nightly, merge queue, and manual full validation run every existing test, wide fixture, performance budgets, coverage, sanitizers, and the new cibuildwheel job. Wheel builds target `cp312-abi3` on native Linux/macOS/Windows; Windows explicitly uses MSVC (`cl`) and a CMake compiler guard. The installed-wheel test checks the tag, module origin, native scan totals, paths, and unit conversion in a test-owned temporary directory. `ci-success` accepts skips only for the named full-tier jobs on PR events. Each PR summary records every job's elapsed duration from GitHub Actions.

Reasoning: This is the product owner's temporary policy, overriding the plan's PR benchmark routing without reducing test coverage on the full tier. A manual full run verifies all three wheel platforms before starting T2.7. Missing §7.3 work remains visible in the inventory above.

Task: T0.5 follow-up / M0 definition of done

## D-0029 — 2026-10-31 — Product-owner milestone order override

Question: What order supersedes the original milestone dependencies?

Choice: Pause M3 and resume it after M4-core. Do only T2.7 from M2 now; defer T2.1–T2.6 until after M4-core. M4-core is T4.1–T4.8 and T4.13. Defer T4.9, T4.10, T4.11, T4.12, and T4.14; wrap all new UI strings in `_()` nevertheless. Use one PR per group: `[T2.7]`, `[T4.1]`, `[T4.2–T4.3]`, `[T4.4–T4.5]`, `[T4.6–T4.8]`, `[T4.13]`. Complete and verify tasks sequentially inside each group.

Reasoning: This is an explicit product-owner decision dated 2026-10-31. Record adaptations when a selected task depends on deferred work; do not implement those deferred features early. Deferring whole tasks is the only permitted scope shortcut.

Task: M2 / M3 / M4 execution order

## D-0028 — 2026-10-31 — Amortized builder growth for small directory batches

Question: How should the builder grow its populated-node bitset without repeated copies during million-node scans?

Choice: Remove the exact reserve(size + next_batch_size) call before each append and let vector manage geometric growth. Extend test-only allocation snapshots with successful allocation-call counts. Add a regression requiring no more than 64 allocations for 20,000 one-child directory appends, plus node/count correctness assertions. Keep the one-million-node tests, two-minute timeout, and 100/140-byte limits unchanged. Add progress counts to timeout diagnostics.

Reasoning: macOS CI passed the other 63 native cases but both million-node memory scans reached the two-minute timeout. Inspection found repeated exact reserve requests, whose reallocation/copy costs differ across standard libraries. The allocation regression fails before the fix with 625 allocations on MinGW and passes afterward with 10. Both Windows and Linux full native suites pass after the change. This removes an algorithmic growth problem rather than relaxing the failing test. macOS must also pass CI before completion.

Alternatives: Increase the timeout, reduce fixture size, mark macOS memory checks ignored, or retain repeated bitset copies.

Task: T1.16 / M1 performance verification
## D-0027 — 2026-10-31 — Atomic coverage counters for scanner workers

Question: How should GCC coverage builds collect valid profiling counts from concurrent scanner workers?

Choice: Compile coverage builds with -fprofile-update=atomic. Keep gcovr parse errors fatal, retain every source file and assertion, and leave both 85% component thresholds unchanged.

Reasoning: The first coverage CI run passed its native tests but gcovr rejected a negative branch hit count in mock_backend.cpp. Scanner functions execute concurrently; non-atomic profiling-counter updates can produce inconsistent counts. Atomic updates address collection at compilation instead of ignoring invalid report data. The change affects coverage instrumentation only.

Alternatives: Ignore negative-hit parse errors, drop the affected source, lower thresholds, or serialize scanner tests solely to hide the profiling issue.

Task: T1.16 / M1 CI verification

## D-0026 — 2026-10-31 — Explicit M1 verification gates

Question: How should the milestone-level Hypothesis, sanitizer, and coverage requirements be enforced beyond individual task checks?

Choice: Add a deterministic 1,000-valid-example Hypothesis property over native mock scans, checking saturated totals, duplicate identities, exclusions, and hidden flags against independent Python accounting. Add a full GCC ASan/UBSan native job with leak detection. Enable GCC/gcov instrumentation through the coverage preset and require at least 85% line coverage for model and scanner separately, including their public headers. Retain HTML/XML/JSON reports as CI artifacts. All new jobs are required by ci-success. Hypothesis and gcovr were already development dependencies.

Reasoning: Final M1 review found these milestone requirements were not yet explicit gates. Initial measured combined coverage was 81.6%, below the unchanged 85% target. New contract tests exercise model-type container iteration and standard algorithms, const access, growth after shrinking, tree accessors and invalid IDs, name-range validation, and actual local owner lookup. These tests increase coverage to 88.2% combined, 88.8% model, and 87.7% scanner. No tests, source files, or valid error paths were excluded to pass the threshold. These checks complete M1 verification and do not implement M2 features.

Alternatives: Rely only on seeded native tests, lower the coverage target, omit public headers, or mark M1 complete based solely on its task checklist.

Task: T1.16 / M1 definition of done

## D-0025 — 2026-10-31 — Memory measurement and performance tooling scope

Question: What belongs in the scanner heap budget, how should allocation instrumentation coexist with runtimes, and which performance-tool behaviors are available before M2?

Choice: Measure requested C++ allocation bytes above a stable, externally held MockBackend baseline, from before start_scan through take_result and handle destruction. Retain the result tree for the steady measurement. Exclude counting headers, allocator bookkeeping, and the mock filesystem input. Add private testing headers for the allocation-counter interface and shared balanced mock input. The default native test executable supplies all standard new/delete replacement forms. MinGW tests use a static C++ runtime; Linux Clang TSan uses its dynamic runtime and an explicit runtime search path, keeping allocation interception and race instrumentation enabled. Both memory assertions remain present and unchanged.

Reasoning: A real filesystem is external input; charging a stored RawEntry description for every mock file would measure the fixture instead of scanner overhead. The same backend remains alive throughout, so subtracting its baseline cannot hide released input storage. MinGW's separately linked C++ runtime allocated strings outside the replacement allocator and caused a heap-corruption exit. Clang's static TSan C++ allocation symbols conflicted with replacement new/delete; dynamic runtime interposition preserves both test instrumentation and sanitizer coverage. No runtime dependencies were added; the existing development compiler/runtime licenses apply.

Choice: Generate only new output trees, rejecting existing paths and link ancestors. Preset node counts include the filesystem root but exclude manifest.json. Manifest totals exclude its own file; the hash covers actual lexical relative-path/kind/size rows. Use sparse zero ranges, fixed-seed log-normal sizes, and a balanced 10%-directory layout. Compare supplied Google Benchmark JSON only in M1, with iteration medians, normalized units, aggregate-median fallback, and failure for missing head benchmarks. CLI binary wall-time/RSS comparison remains explicitly deferred to T2.2 as the plan requires; reserved flags are accepted and documented.

Reasoning: Deterministic relative paths make manifests comparable across output locations and operating systems. Sparse Windows files must be marked through their existing file handle before truncation. A manifest cannot include its own final listing hash without self-reference. New-only outputs avoid overwriting user files. Benchmark medians resist outliers; removed benchmark cases cannot silently vanish from regression checks.

Alternatives: Charge mock input to scanner RAM, omit aligned allocation forms, disable failing tests or sanitizers, overwrite existing fixture trees, write large physical zero files, or implement the future CLI early.

Task: T1.16

## D-0024 — 2026-10-31 — Owner identity caching and reader synchronization

Question: How should lazy resolution update interned identities without racing readers, and what should eager, off, and cancelled scans do?

Choice: Keep a reverse identity vector in OwnerTable and fill an existing empty display name without changing its stable ID or replacing an already resolved name. Serialize resolution batches per shared TreeHandle. Copy only unresolved requested identities under a reader lock, deduplicate by owner ID, perform at most eight parallel backend lookups outside the tree lock, then insert results under one writer lock. Nodes sharing an identity share the cached display. Eager scans resolve before completion, off scans retain no owner hints, and cancelled scans skip eager resolution. Retain the backend with the Python tree so lazy lookups work after handle destruction. Windows native SID lookup remains in its planned milestone; synthetic UID tests run on all platforms.

Reasoning: Metadata initially interns UID hints with empty names; returning the original empty display forever prevented lazy updates. Stable owner IDs let one successful lookup resolve that identity throughout the tree. Readers continue during slow I/O and observe a complete insertion batch. Repeated and concurrent requests reuse resolved identities. A reverse vector avoids scanning the identity map for each selected node. No dependencies were added.

Alternatives: Resolve every file during enumeration, perform lookups under the tree writer lock, replace owner IDs, or call Python from worker threads.

Task: T1.15

## D-0023 — 2026-10-31 — Permission checks on privileged Windows CI

Question: How should a real denied-directory integration test behave when the Windows runner can bypass its fixture ACL?

Choice: Temporarily disable SeBackupPrivilege and SeRestorePrivilege on the test process token only while the permission test scans. Save the exact prior token privilege state, restore it in a finally block, and close the token handle. Keep the real ACL fixture, all denied flags and issue assertions, and the accessible-sibling byte assertion unchanged. Product privilege handling is unchanged.

Reasoning: Windows CI enumerated the ACL-denied directory while the ordinary local process was denied. Windows directory handles require FILE_FLAG_BACKUP_SEMANTICS; enabled backup privileges can override file security checks. The test must exercise ordinary denied access even on an elevated runner. Missing token privileges are already disabled and need no grant; the helper only disables existing privileges. This is test infrastructure, adds no dependencies, and preserves cleanup under the restored original token.

Sources: [File security and access rights](https://learn.microsoft.com/windows/win32/fileio/file-security-and-access-rights), [AdjustTokenPrivileges](https://learn.microsoft.com/windows/win32/api/securitybaseapi/nf-securitybaseapi-adjusttokenprivileges).

Alternatives: Skip Windows denial coverage, accept a successful read as denial, or make the scanner report access-denied despite successful enumeration.

Task: T1.14

## D-0022 — 2026-10-31 — Filesystem integration execution

Question: How should platform-specific filesystem capabilities and the wide fixture be verified without hiding unsupported CI environments?

Choice: Run the wide 100,000-file fixture in the normal integration suite with a 300-second timeout for the test body; pytest fixture setup and teardown own creation and cleanup. Use the fixture oracle for aggregate totals, and explicit assertions for link policy, flags, and retained diagnostics. Linux mount tests create a tmpfs only beneath their pytest temporary directory and unmount it in a finally block. Missing mount tools or privileges fail in CI; local environments may report an explicit capability skip. Ordinary OS-specific tests run only on their applicable platforms.

Reasoning: The initial wide test passed its scan assertions but hit its 300-second timeout during Windows temporary-file unlink cleanup. Moving creation and cleanup into a yield fixture and using func_only keeps the timeout on the operation under test without interrupting cleanup. The full fixture and all assertions remain intact. Mount checks must not silently disappear from CI. Native file counts describe descendants, while the pure fixture oracle includes the file itself; directory aggregates can be compared directly. No dependencies were added.

Alternatives: Reduce the wide fixture, mark it slow and omit it from CI, or silently skip mount failures in CI.

The Windows sparse integration test also exposed a fixture bug: opening with wb after setting the sparse flag recreates the file and clears that flag. Reopen the existing sparse file with r+b, and assert both its sparse attribute and reduced allocation in regression coverage. The scanner allocation assertion remains unchanged.

Task: T1.14

## D-0021 — 2026-10-31 — Python scan facade and synthetic backend construction

Question: Where should shared Python scan values and mock construction live, and how should relative paths and blocking mock scans behave?

Choice: Define ScanRequest with other public values in api/types.py and re-export it from api/scan.py. Add api/testing.py as the typed constructor for the planned native test backend. Normalize paths lexically with abspath, preserving symlinks and native surrogate characters. Add an optional backend keyword to the blocking scan helper, matching start_scan, so deterministic tests use the same polling path. Wrap native trees with a shared TreeHandle and copy metadata under its reader lock. Native exceptions construct the public Python exception classes, with machine-readable scan codes and preserved paths or glob patterns.

Reasoning: Shared values avoid facade import cycles; a typed mock constructor keeps test configuration independent from private native types. Path.resolve would follow links before traversal policy applies. Both helpers need native-only backends to verify GIL release and injected failures without Python worker callbacks. The additional blocking-helper keyword is backward compatible. No dependencies were added.

Alternatives: Expose native types directly, duplicate ScanRequest, resolve links during input normalization, or implement Python filesystem callbacks.

Task: T1.13

## D-0020 — 2026-10-31 — Vendor header warning boundaries

Question: How should warnings-as-errors handle MSVC's intentional-alignment padding warning in the pinned robin-map template?

Choice: Mark the robin-map CMake target as `SYSTEM`, so its interface headers are treated as external by consumers. Retain all project warning flags and warnings-as-errors.

Reasoning: Windows CI reported C4324 in robin-map's aligned bucket storage, rather than in project code. CMake's system-target property applies the compiler's external-header handling without changing dependency sources, disabling tests, or disabling a warning throughout the project.

Alternatives: Disable warnings-as-errors, suppress C4324 for every project source, or patch the pinned vendor's intentional layout.

Task: T1.12

## D-0019 — 2026-10-31 — Link traversal and identity accounting

Question: How should the planned `backend.stat_follow` operation and directory-follow hints be represented, and which metadata should linked entries retain?

Choice: Add a safe-default `FsBackend::stat_follow` hook and an explicit `DirHint.follow_symlinks` field. Local backends use separate followed directory enumeration; default enumeration still rejects final directory links. POSIX metadata operations may resolve parent components while retaining no-follow semantics for the final entry. Extend mock inputs with alias targets for deterministic traversal tests. Track file and directory identities by `(dev, ino_hi, ino_lo)` using the already pinned MIT-licensed robin-map dependency, with its flat set at 0.9 load factor; release both identity tables before finalization. Additional hard links retain their logical file metadata and receive `kHardlinkDup` only in dedup mode, so aggregation excludes their byte contribution. Unfollowed symlinks contribute zero bytes as file entries; junctions remain directory entries without descent. Followed directory identities are visited globally, and mount boundaries are pruned unless explicitly crossed.

Reasoning: The walk pseudocode requires followed stats, although the earlier backend signature omitted that hook. Keeping follow behavior explicit preserves the default no-follow policy. Physical identities stop directory cycles even when different paths name the same directory. Unknown file identities are counted with a notice rather than collapsed together; a directory link without a stable identity is not followed. Explicitly selected mount roots establish their own filesystem boundary. Symlinks to files use target metadata when following is requested. Alias directories retain their original path in the visible tree, and cloud placeholders never enter the link-follow path.

Alternatives: Follow every reparse point, deduplicate by path text, zero the logical size of duplicate file nodes, or retain scan-only identity tables after completion.

Task: T1.12

## D-0018 — 2026-10-31 — Scanner types, ownership, and live snapshots

Question: How should the staged model metadata become complete without circular includes, and how should scan threads and snapshots behave on all supported standard libraries?

Choice: Put shared options, enums, issues, volume information, metadata, and progress records in `scan_types.hpp`, included by the model. Preserve `platform::VolumeInfo` as an alias. Grant the single builder engine private access for root metadata and snapshot copies, preserving the planned public tree-builder interface. Use `std::thread` with RAII cancellation and joining because the supported Apple libc++ lacks `std::jthread`. The builder alone mutates nodes; workers submit listings through a queue capped at four times their count. Snapshots are requested asynchronously, copied at most once per second, and held independently from the live builder. Retain the first 1,000 issues in metadata while bounding the independently drained live queue at 100,000.

Reasoning: The model retains complete scan options and diagnostics, while the platform and backend also need those shared types. A separate type header breaks the dependency cycle. Explicit thread ownership lets handle destruction safely join outstanding work, and immutable copies prevent readers from racing with appends. Root targets are normalized, deduplicated, and checked for nesting before I/O. Timestamps use zero when absent/nonpositive and saturate at the node's 32-bit maximum. Linux statx device identities use `makedev` to agree with the stat fallback and volume metadata. Explicit MFT mode remains unavailable until its planned milestone; auto mode currently walks. The whole-repository formatter check also normalized three initial scaffold C++ files without semantic changes.

Alternatives: Duplicate shared types, expose mutable builder storage publicly, let workers append nodes, return views of growing storage, or require a different macOS standard library.

Task: T1.11

## D-0017 — 2026-10-31 — Glob semantics and bounded matching

Question: Which unspecified gitignore-style details should exclusion globs support, and how should matching avoid recursive backtracking?

Choice: Match `*` and `?` within a path component, `**` across separators, and `**/` across zero or more directory prefixes. Support negated character classes and backslash escapes. Leading `/` anchors a glob to the scan root; trailing `/` limits it to directories. A trailing `/**` also prunes its directory prefix. Use Unicode code points with the existing BMP simple-fold table on Windows and macOS, preserve invalid native bytes, and leave POSIX byte names unnormalized. Compile patterns once and evaluate an iterative state machine with stack storage for ordinary patterns and linear heap storage for longer ones. Excluded absolute paths match complete subtrees by component boundaries.

Reasoning: These choices make zero-directory `**/` cases and directory pruning deterministic. Iterative matching bounds work by pattern length times input length instead of exponential backtracking and avoids per-entry allocations for ordinary patterns. `scan.hpp` introduces exclusion types before the engine task because the planned class needs them. The development-only fuzz target uses Clang/libFuzzer (Apache-2.0 WITH LLVM-exception), with address and undefined-behavior sanitizers; no runtime dependency is added.

Alternatives: Use platform-dependent filesystem glob APIs, recursively backtrack, compare UTF-8 one byte at a time, or keep excluded directory placeholders in the scan tree.

Task: T1.10

## D-0016 — 2026-10-31 — macOS thread-library availability

Question: How should concurrency tests run on the supported macOS runner when its Apple libc++ does not expose `std::jthread`?

Choice: Use `std::thread` and explicit joins in the backend counter test. Retain the same concurrent operations and assertions. Apply explicit RAII joining if the scanner needs a compatibility implementation on this standard library.

Reasoning: The CI compile logs show that the supported Apple toolchain accepts C++20 but lacks `std::jthread`. This test needs concurrent reads and completed workers, without stop-token behavior. Explicit joins provide those semantics on all three operating systems.

Alternatives: Disable the macOS test, require a different standard library, or omit concurrent coverage.

Task: T1.9

## D-0015 — 2026-10-31 — Mock filesystem shape and staged backend hooks

Question: What concrete shape should the unspecified `MockSpec` and `DirHint` types use, and what does a vanish-after-listing fault represent?

Choice: Represent mock entries as native paths plus `RawEntry` metadata. Index direct children once, assign deterministic file identities when omitted, and keep faults and owner names in explicit tables. A vanish fault omits the affected child with a `NotFound` issue during its parent's listing and makes later stats fail, modeling disappearance between OS enumeration and metadata lookup. Count every attempted directory read atomically and apply the configured delay to each operation. Keep `DirHint` empty until traversal hints are needed; forward-declare fast-scan types. The mock reports local semantics. Local Windows owner resolution returns no value until the SID implementation in T3.6.

Reasoning: The plan specifies behavior but not these type layouts. A precomputed child index avoids repeatedly searching the whole mock tree, and immutable metadata plus synchronized vanish state supports concurrent scanner workers. The staged hooks preserve the planned backend signatures without introducing later scan or MFT features.

Alternatives: Rebuild directory contents by scanning every mock path on each call, depend on real filesystem failures, or introduce later scan implementations early.

Task: T1.9

## D-0014 — 2026-10-31 — Windows metadata and serial lifetime

Question: How should Windows walk mode obtain reparse tags on the legacy listing fallback and retain volume identities without stale mount information?

Choice: Use extended directory records normally and legacy records when the filesystem rejects the extended class. Query legacy reparse tags with `FindFirstFileW` only for reparse entries. Inspect mount-point reparse data through a no-follow handle to distinguish volume mounts from junctions; cloud entries never take that path. Query the directory handle's volume serial once per listing and reuse it for every returned entry, rather than keeping a process-wide per-volume serial cache. Preserve UTF-16 names through explicit WTF-8 conversion, including lone surrogates.

Reasoning: Legacy records lack the extended reparse tag. The fallback reads metadata without opening ordinary files or cloud data. Scoping the serial to the live directory handle avoids stale identities after a volume is remounted and keeps the per-file loop free of serial queries. Native tests clean up their own temporary trees with verbatim Windows APIs because MinGW filesystem cleanup hangs on paths beyond MAX_PATH.

Alternatives: Open every file for metadata, follow reparse points to classify them, or retain serials across mount changes.

Task: T1.8

## D-0013 — 2026-10-31 — Platform metadata prerequisites

Question: Where should the platform enumeration types live before the backend and scan tasks introduce their consumers, and how should missing bulk metadata be handled?

Choice: Introduce `platform.hpp` with the planned entry, listing, issue, volume, and platform interfaces needed by T1.7. Add an `access_denied` marker to `RawEntry` for the specified per-entry permission failure. Linux uses `getdents64` and `statx`, with `fstatat` fallback on `ENOSYS`. macOS requests bulk metadata and falls back to `fstatat` for entries with unsupported attributes, or reopens the directory for `readdir` when bulk enumeration is unsupported.

Reasoning: Enumeration needs these shared types before `FsBackend` exists. Keeping one definition avoids incompatible duplicates in later tasks. Optional birth times remain absent when unsupported, and bulk fallback preserves metadata and raw names across filesystems.

Alternatives: Delay the types until T1.9, duplicate them privately, or reject filesystems that do not return every bulk attribute.

Task: T1.7

## D-0012 — 2026-10-30 — Fixture oracle paths and capability handling

Question: How should the testkit represent the fixture root, unreadable directory contents, links, and unavailable OS features in expected results?

Choice: Use an empty string for the root and POSIX-style relative keys for descendants. Count each file or hard-link directory entry as a file; in dedup mode only the first regular file contributes bytes and each extra hard link increments `hardlink_dups`. Treat unreadable directory contents as unseen. Keep links unfollowed by default. Create every fixture inside a test-owned temporary directory and expose observed feature support through `Caps.require`, which fails in CI when `DAFREE_REQUIRE_ALL_CAPS=1`.

Reasoning: The keys can be compared independent of the host OS. The totals reflect what a scanner can observe without access or link following. Explicit capability checks keep platform limitations visible, while cleanup restores directory permissions before removing the owned fixture. Linux long paths use directory-relative operations so the preset can exceed `PATH_MAX`. On an elevated Windows CI runner, `icacls` successfully applies the deny ACE but directory enumeration can still succeed; the Windows fixture test checks ACL setup and cleanup, while POSIX tests also assert that enumeration is denied.

Alternatives: Use absolute platform paths in the oracle, count hidden unreadable children, or silently skip unsupported features in CI; these would make cross-platform assertions or failure diagnosis unreliable.

Task: T1.6

## D-0011 — 2026-10-30 — Unit API and Python parity

Question: What are the unspecified C++ `UnitMode` and `UnitStyle` shapes, and how can the required Python JSON parity test exercise the C++ formatter?

Choice: Use `UnitMode` for auto, bytes, and fixed powers; `UnitSystem` for traditional binary labels, IEC, and SI; and `UnitStyle` for the system and caller-supplied decimal separator. Bind these types through nanobind and expose matching Python enums and a frozen style dataclass from `dafree.api`. Parse decimal values with checked integer arithmetic and at most nine fractional digits.

Reasoning: The style object makes locale behavior explicit and deterministic. The Python parity test calls the native formatter and parser through the typed facade, so its JSON table checks the same implementation that GUI delegates will use.

Alternatives: Depend on process locale, use floating-point conversion near `UINT64_MAX`, or keep a separate Python formatter whose output could diverge from C++.

Task: T1.5

## D-0010 — 2026-10-30 — Saturated totals during deletion

Question: How should incremental deletion update an ancestor whose size has saturated at `UINT64_MAX`?

Choice: Subtract and add the changed child contribution along ordinary ancestor paths. Recompute a saturated ancestor from its direct children before continuing upward. Use a direct segment-index fast path for the usual full-size `SegVector` segments, with binary-search fallback after `shrink_last` followed by an append.

Reasoning: Saturating addition cannot be reversed by subtraction; the recompute path preserves the result of a fresh aggregation. The segment lookup avoids repeated binary searches in the 10-million-node aggregation pass while preserving random access after shrinking.

Alternatives: Always reaggregate the whole tree after deletion, or subtract from saturated totals and risk incorrect values.

Task: T1.4

## D-0009 — 2026-10-30 — Staged tree metadata and aggregation

Question: How can `Tree` and `TreeBuilder` be introduced in T1.3 while scan metadata and aggregation are assigned to later tasks?

Choice: Keep `ScanMeta` empty until the scan API types are introduced, expose the planned tree and builder signatures, and defer aggregation, deletion, and subtree-replacement definitions to T1.4 and later. `MemoryReport` reports reserved storage by core category and estimates interner storage.

Reasoning: The plan stages these APIs across tasks. Defining scan options and issue types inside the model prematurely would duplicate scan ownership; implementing aggregation early would pull T1.4 into T1.3.

Alternatives: Move scan-owned types into the model now, or omit the corresponding tree API until later tasks, both of which would drift from the planned module boundaries and interfaces.

Task: T1.3

## D-0008 — 2026-10-30 — Unicode simple case folding data

Question: How should extension interning fold non-ASCII BMP letters without adding a runtime library dependency?

Choice: Generate a checked-in lookup table from Unicode 17.0.0 `CaseFolding.txt`, using common and simple one-code-point mappings whose source and target are in the BMP. Keep the source data, generator, and Unicode License V3 with the repository.

Reasoning: The plan requires UTF-8-aware BMP simple folding. A generated table gives deterministic behavior on every supported OS without locale-dependent system calls or a runtime Unicode dependency.

Alternatives: Fold ASCII only, which misses the specified BMP behavior, or add a Unicode runtime library, which adds a dependency outside the plan.

Task: T1.2

## D-0007 — 2026-10-30 — Owner key identity and display

Question: How should the owner table distinguish its UID, SID, and remote-string keys, and what should a duplicate key do when given a different display name?

Choice: Use a tagged key for POSIX UIDs, Windows SID bytes, and remote strings; return the existing ID and retain the first display name for duplicate keys.

Reasoning: The tag prevents identical byte sequences in different identity domains from colliding. Keeping the first display makes an already assigned owner ID stable during a scan.

Alternatives: Use untagged strings, which could merge unrelated identity domains, or replace display names on later calls, which makes display values depend on traversal order.

Task: T1.2

## D-0006 — 2026-10-30 — Babel in isolated builds

Question: How can the CMake translation-compilation step find Babel during an isolated wheel build, where development extras are not installed?

Choice: Declare Babel as a build-system requirement and compile each checked-in `.po` catalogue through Python during the CMake build.

Reasoning: The built wheel must contain `.mo` files without adding Babel to runtime dependencies; build-system requirements are installed in the isolated build environment.

Alternatives: Ship precompiled catalogues without a build step, or make Babel a runtime dependency. The former can leave generated translations stale and the latter unnecessarily expands runtime dependencies.

Task: T0.7

## D-0005 — 2026-10-30 — Code of Conduct contact placeholder

Question: Which contact should the code of conduct name before a project support address exists?

Choice: Use `conduct@Ahmed41022.invalid` as an explicit non-deliverable placeholder and direct security reports to GitHub private vulnerability reporting.

Reasoning: No verified conduct mailbox was provided; the reserved `.invalid` domain cannot accidentally route reports to an unrelated person.

Alternatives: Invent a real-looking email address, which could send private reports to an unrelated recipient, or omit the contact required by the plan.

Task: T0.6

## D-0004 — 2026-10-30 — NumPy license expression

Question: How should the runtime allowlist treat NumPy's compound license expression, which the planned exact allowlist does not include?

Choice: Add NumPy's exact expression `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0` to the exact allowlist.

Reasoning: NumPy is an explicitly required dependency and the listed identifiers are permissive; exact matching keeps mixed expressions from passing through a broad partial match.

Alternatives: Use partial matching, which could admit an expression containing a forbidden license, or remove NumPy contrary to the plan.

Task: T0.5

## D-0003 — 2026-10-30 — Staged CI rollout

Question: How can CI stay green while the plan's complete workflow refers to presets, tools, and feature tests that are scheduled for later tasks?

Choice: Start with a required `ci-success` check covering the current lint, C++ build, Python tests, and dependency audits; add the remaining workflow jobs when their planned prerequisites are implemented.

Reasoning: This lets every push be checked without pulling later milestone work forward or hiding missing checks behind skipped jobs.

Alternatives: Add the full workflow immediately, which would fail on files and test suites that do not exist yet; or mark those jobs skipped, which would not verify them.

Task: T0.5

## D-0002 — 2026-10-30 — CLI exit code names

Question: How should `exit_codes.py` expose values when the plan only specifies the missing-GUI exit status?

Choice: Provide an `ExitCode` integer enum with `SUCCESS = 0`, `ERROR = 1`, and `USAGE = 2`.

Reasoning: Named values make the scaffold's exit statuses clear while preserving Click's specified usage error code of 2.

Alternatives: Use bare integer constants; these provide no additional clarity over the enum.

Task: T0.4

## D-0001 — 2026-10-30 — Windows stable ABI loading

Question: How should local Windows venv tests load the stable ABI module with the available managed CPython and MinGW toolchain?

Choice: Add the interpreter base directory before loading the native module and statically link MinGW runtime libraries for MinGW builds.

Reasoning: This keeps local package tests runnable without changing the stable ABI module contract or adding runtime dependencies to MSVC builds.

Alternatives: Require a manually configured DLL search path, or bundle compiler runtime DLLs with the package. Both add setup or packaging burden.

Task: T0.1

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
