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
window is activated. Opening/scanning those forwarded targets will be connected
with the later main-window actions; the bootstrap retains the arguments.

Background callables run through a four-worker `TaskRunner`. Results and failures
arrive on the GUI thread, so waiting for native work does not block GUI events.

`ScanController` snapshots a scan request and validates its roots in a worker.
It polls progress, issues, and notices every 250 ms, requests partial native trees
every fourth tick (at most once per second), and collects final results in a
worker. Pause, resume, and cancel can be requested while startup is pending.
Cancellation keeps polling until a partial result arrives. A controller owns one
scan at a time; an explicit `failed` signal reports asynchronous failures and
leaves it ready for another scan. Final progress and diagnostics arrive before
the `finished` signal. Main-window scan buttons are part of the next UI tasks.

Unhandled Python exceptions are logged and displayed in a dialog with **Copy
details**. Native surrogate characters appear as escaped diagnostic text, so Qt
does not silently truncate the error. Forwarded target arguments retain their
original values. Each launch selects a UTF-8 log at
`<data>/logs/dafree-YYYYMMDD.log`; a running session keeps that file. Bootstrap keeps
its launch-date log and the six newest other dated regular log files. Retention applies
only to generated application diagnostics. Links and unrelated files are left
alone, and a link at today's log path is rejected. Scan targets are never touched
by logging or instance housekeeping.

The full directory table, scan controls, and file actions are still being built.
Configuration storage paths are described in [configuration commands](cli.md).
