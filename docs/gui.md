# Desktop bootstrap

Install the optional GUI dependency and launch the desktop scaffold:

```console
python -m pip install ".[gui]"
dafree gui
```

The initial window uses Fusion and the shared `theme` and `locale` preferences.
Open **Settings** from the main window to choose a system, light, or dark theme,
language, units and labels, row density, scan defaults, and duplicate-analysis
defaults. Settings are staged in the dialog and saved atomically on **OK**;
**Cancel** leaves both the saved and live preferences unchanged. The system
theme follows operating-system color-scheme changes while selected. Language
changes take effect after restarting the application. Use the [Shortcuts page](guide/shortcuts.md) to customize keys and resolve conflicts.
Scheduled scans remain unavailable until scheduling is implemented. Duplicate defaults are stored for future analysis; duplicate analysis
is not available yet.

English, Arabic, and German translations are included. The selected locale configures
gettext, Qt standard-dialog buttons, localized dates and counts, and layout direction.
Arabic uses a right-to-left layout. Size display uses locale digits and decimal points
while retaining exact byte integers, selected unit labels, and explicit non-default
decimal separators. File paths and report data retain their original contents.
The editable size fields keep the existing ASCII size syntax.

One desktop instance owns each application data directory and Windows privilege level. A second launch at the same privilege level
passes its arguments through local IPC and exits after acknowledgment. The first
window is activated and opens a target-selection dialog for forwarded targets;
scanning requires explicit acceptance.

Background callables run through a four-worker `TaskRunner`. Results and failures
arrive on the GUI thread, so waiting for native work does not block GUI events.

`ScanController` snapshots a scan request and validates its roots in a worker.
It polls progress, issues, and notices every 250 ms, requests partial native trees
every fourth tick (at most once per second), and collects final results in a
worker. Pause, resume, and cancel can be requested while startup is pending.
Cancellation keeps polling until a partial result arrives. A controller owns one
scan at a time; an explicit `failed` signal reports asynchronous failures and
leaves it ready for another scan. Final progress and diagnostics arrive before
the `finished` signal. The main window owns this controller and connects Pause/Resume and Cancel.

Unhandled Python exceptions are logged and displayed in a dialog with **Copy
details**. Native surrogate characters appear as escaped diagnostic text, so Qt
does not silently truncate the error. Forwarded target arguments retain their
original values. Each launch selects a UTF-8 log at
`<data>/logs/dafree-YYYYMMDD.log`; a running session keeps that file. Bootstrap keeps
its launch-date log and the six newest other dated regular log files. Retention applies
only to generated application diagnostics. Links and unrelated files are left
alone, and a link at today's log path is rejected. Scan targets are never touched
by logging or instance housekeeping.

The tree table model reads native tuples in pages of 200, keeping at most 50
pages. Expansion/removal notifications bracket the actual native mutation; pure
native count previews supply Qt's required before-change ranges. Sorting and
filtering clear cached pages, preserve expanded paths, and restore registered
table selections by stable node ID. Hidden selections are dropped. The native
view retains its public source `tree` for individual path and parent lookups.
One-level child expansion also stays in C++; Python does not enumerate the tree.
Tooltips display the full path, and screen-reader text includes type, size, and
percentage of parent. Displayed surrogate characters use explicit escaped text,
while the row metadata and native source paths remain lossless.

The virtual table provides Name, Size, % of Parent, Allocated, Files, Folders,
Last Modified, Owner, and Extension columns. Owner and Extension start hidden.
Right-click a header to show/hide columns; drag headers to reorder and resize
them. Hidden columns keep their widths. Changes update shared preferences and,
when the table has application paths, save after a short debounce or on close.
Allocated values prefixed with **≈** carry unreliable allocation metadata.
Dates and percentages follow the current Qt locale. File category icons use
original geometric artwork; classification remains deferred to T2.5.

The table paints only cells intersecting Qt's visible geometry, retaining Qt's
scrolling, header, selection, and accessibility behavior. Delegates share native
pages and bounded prepared text layouts; they create no items for hidden rows.
A frame shares its owned font/metrics and current native tuple across delegates,
fetching metadata once per visible row and reusing row text setup. Standalone Qt
delegate calls retain independent painting and owned font-cache values.
Showing Owner enables lazy native owner resolution for fetched pages. Windows displays the account name associated with the file's SID when available. Hiding it
restores the caller's initial owner-resolution policy.

Use Up/Down, Page Up/Page Down, Home/End for row navigation. Right expands the
current directory or moves to its first child; Left collapses it or moves to its
parent. `*` expands immediate child directories. Enter requests properties and
Menu opens the row context menu. Enter and its Properties action open the
read-only properties dialog. Clicking a chevron also toggles expansion, with mirrored controls
and hit regions in RTL. Accessible row descriptions include type, size, and
percentage without exposing internal numeric IDs.

The main window includes a Locations sidebar, the planned tab positions, and a
status bar with mode, file/folder counts, total size, elapsed time, and a clickable
issue count. Tree and Issues contents are created only when activated. Later
analysis tabs and deferred toolbar actions remain disabled. The sidebar discovers
native volumes in a worker, shows used/free capacity and network icons, and retains
recent targets and the snapshot directory. Snapshot opening belongs to M6.

`TreeTableView` uses compact 24-pixel rows by default. Settings can switch to
comfortable 32-pixel rows and change shared unit preferences.

The tree tab's search field waits 250 ms after typing, then applies a trimmed,
case-insensitive literal substring to file and folder names. Glob characters
are treated literally. A NUL character is rejected; the last valid filter stays
active and the invalid character is marked with a red wavy underline and a
localized tooltip. The structured query grammar is deferred to T6.1. The units
selector (Automatic, Bytes, and kilo through exa) changes displayed size formatting
for the cached rows, selection details, and scan total; it does not fetch rows again or
rescan the filesystem.
The Tree tab prepares native views off-thread and pairs its table with a breadcrumb
and selection metadata; miniature charts remain M5 work. Issues retain the native
summary's first 1,000 entries and show its complete count; kind filtering applies
to copying and CSV export. Windows displays an administrator badge only when elevation is known.

Closing the window cancels its read-only scan and keeps processing GUI events until
background work delivers its result, then saves window geometry and disposes the
native-backed views. The progress panel shares toolbar actions; properties are available and file actions remain deferred.
Configuration storage paths are described in [configuration commands](cli.md).


Choose **New scan**, activate a volume/recent target, or launch with target
arguments to open the scan dialog. Select multiple volumes and choose **Add
selected volumes**, use **Add folder…** repeatedly, or type a directory and choose
**Add path**. Remove selected targets with **Remove targets**. Folder checks run
in the background; Start stays disabled while validation is pending. The native
engine checks roots again when scanning begins.

The dialog exposes thread count (0 means Auto), Auto/Walk modes, symbolic-link
and filesystem traversal, hidden/system exclusions, and Globs/Paths editors with
one entry per line. Existing unedited exclusions retain their raw native values.
**Start scan** (Enter) saves these defaults and starts scanning; Escape cancels
without saving. A failed preference write keeps the dialog open with its error.
Windows offers MFT mode for elevated local NTFS scans. **Restart as administrator** requests consent and opens the current targets in an elevated instance. Declining consent keeps the current dialog open. Auto can fall back to Walk when fast scanning is unavailable.


During a scan, the progress panel shows files, folders, logical bytes, elapsed
time, current path, and files/second smoothed with an EMA (alpha 0.3). Long paths
are middle-elided; their complete diagnostic text remains in the tooltip and
accessible name. Pause/Resume and Cancel share the toolbar actions, so either
location controls the same scan. Cancel is immediate and needs no confirmation
because scanning is read-only; partial results remain available on completion.

Walk scans show an indeterminate bar. A supplied native total enables bounded
percentage display from processed files/folders using the MFT record estimate. Start and terminal states issue accessible
alerts, while regular progress ticks update ordinary labels. A new scan clears
old rates, errors, and partial status.


Use Enter on a tree row or choose **Properties** from its context menu to inspect
its full path, type, logical/allocated sizes and ratio, descendant counts,
timestamps, human-readable flags, and matching volume information recorded by
the scan. Missing timestamps/volume metadata show **—**. Opening the dialog
resolves its owner in the background; unavailable owner data does not hide the
other properties. **Copy path** copies readable text, escaping undecodable
characters and retaining an additional native-string clipboard payload.

The Issues tab's **Issue kind** filter applies to **Copy all** and **Export CSV**.
Both use all matching retained rows; diagnostics beyond the scan's first-1,000
limit are counted but cannot be exported from this view. Clipboard text and
UTF-8 CSV include Kind, Path, and Message with normal comma/newline quoting;
clipboard data also retains raw issue strings. Choose a new CSV filename:
existing files and final symlinks are preserved. Export runs in a worker.
An interrupted write reports that its newly created report may be incomplete;
it does not remove or overwrite another file.


## Automated self-test

For an isolated, read-only GUI scan check, supply a directory and its expected logical
byte total (sum of file lengths, with hard links counted once):

```console
python -m dafree.gui.app --self-test /path/to/fixture --expect-size 1234
```

The hook forces offscreen Qt, uses disposable preferences/logs, and checks the first
rendered model row and raw total after asynchronous scanning completes. The normal
root row displays its full path; the check verifies that path and its directory name.
It prints one JSON object with `ok`, `name`, `size`, `expected_size`, and `error`, and
exits 0 on success or 1 on failure. It does not read or update your saved preferences.
Use a directory without permission errors or linked roots for a successful check.

Developers can build the same console-enabled GUI smoke bundle used in CI:

```console
python -m pip install --require-hashes -r requirements/freeze.txt
python -m pip install ".[gui]"
python tools/dist/build_frozen.py --out dist/selftest
```

Launch `dist/selftest/DiskAnalyzerFree/DiskAnalyzerFree` (add `.exe` on Windows) with
the same self-test flags. The output must be inside the checkout and must not already
contain a bundle. Build work and FetchContent caches remain inside the ignored repo
build/cache directories. Linux CI and the release verification workflow exercise
actual frozen executables; installers and the final release bundle remain M10 work.
