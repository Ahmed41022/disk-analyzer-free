# Desktop bootstrap

Install the optional GUI dependency and launch the desktop scaffold:

```console
python -m pip install ".[gui]"
dafree gui
```

The initial window uses Fusion and the shared `theme` and `locale` preferences.
The system theme is sampled at startup; live switching and the settings dialog
remain deferred. The selected locale configures gettext, Qt's standard-dialog
translator when available, and the initial layout direction. New custom strings
are marked for translation; full GUI translations and RTL refinement remain
T4.12 work.

Only one desktop instance owns each application data directory. A second launch
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
Showing Owner enables lazy native owner resolution for fetched pages. Hiding it
restores the caller's initial owner-resolution policy.

Use Up/Down, Page Up/Page Down, Home/End for row navigation. Right expands the
current directory or moves to its first child; Left collapses it or moves to its
parent. `*` expands immediate child directories. Enter requests properties and
Menu requests the row context menu; their application actions are connected in
later tasks. Clicking a chevron also toggles expansion, with mirrored controls
and hit regions in RTL. Accessible row descriptions include type, size, and
percentage without exposing internal numeric IDs.

The main window includes a Locations sidebar, the planned tab positions, and a
status bar with mode, file/folder counts, total size, elapsed time, and a clickable
issue count. Tree and Issues contents are created only when activated. Later
analysis tabs and deferred toolbar actions remain disabled. The sidebar discovers
native volumes in a worker, shows used/free capacity and network icons, and retains
recent targets and the snapshot directory. Snapshot opening belongs to M6.

`TreeTableView` uses compact 24-pixel rows and initial shared unit preferences.
The Tree tab prepares native views off-thread and pairs its table with a breadcrumb
and selection metadata; miniature charts remain M5 work. Issues retain the native
summary's first 1,000 entries and show its complete count; filtering/export are
T4.13 work. Windows displays an administrator badge only when elevation is known;
the real Windows privilege query remains paused T3.7 work.

Closing the window cancels its read-only scan and keeps processing GUI events until
background work delivers its result, then saves window geometry and disposes the
native-backed views. The detailed progress panel is the next task; file actions remain deferred.
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
Windows lists MFT as disabled until its fast engine is implemented. Administrator
relaunch is also disabled until the paused Windows privilege task supplies it.
