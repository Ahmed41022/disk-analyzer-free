# Command line interface

Use `dafree --help` for the available commands and options. Global options go
before the command name and apply to that invocation. Use `dafree scan --help`
for scan-specific options.

| Option | Meaning |
| --- | --- |
| `--format table\|json\|ndjson\|csv` | Select a report format. The default is table on a terminal and JSON when redirected. |
| `--units auto\|b\|kb\|mb\|gb\|tb` | Select automatic or fixed-size units. |
| `--si`, `--iec-labels` | Choose decimal SI units or IEC binary labels. Specify one at most. |
| `--no-color` | Disable table colors. A nonempty `NO_COLOR` also disables colors. |
| `--locale TAG` | Select a shipped locale. |
| `-q`, `-v` | Decrease or increase verbosity. Both can be repeated. |
| `--progress auto\|always\|never` | Select progress output policy for commands that report progress. |
| `--threads N` | Set the requested worker count. `0` selects it automatically. |
| `--config FILE` | Read global option defaults from TOML. Explicit command-line options take precedence. |
| `--portable` | Request portable mode. This currently reports a usage error until T10.2 supplies portable storage. |

The TOML file uses top-level long option names without the leading dashes.
For example, `threads = 4`, `format = "json"` and `no-color = true` set three
defaults. Unknown keys and malformed values report a usage error. The settings
commands below manage persistent preferences separately from this file.

See [exit codes](reference/exit-codes.md) for process status meanings.

## Scan

```console
dafree --format table scan . --depth 2 --files
dafree --format json scan source assets --depth 1 --files > report.json
dafree --format csv --progress never scan . --stats-json scan-stats.json > report.csv
```

Depth is measured from each target. The default depth is one, and zero shows
only target roots. Add `--files` to include file rows. The depth and file filter
affect the report while directory totals still describe the scanned contents.
Use `--sort size|alloc|files|dirs|name|mtime` and `--asc` to control table order.

Use `--exclude GLOB`, `--exclude-path PATH`, `--exclude-hidden`, and
`--exclude-system` to omit entries from the scan. Links and filesystem boundaries
are respected by default. `--follow-symlinks` and `--cross-fs` opt into traversal.
`--mode`, `--hardlinks`, `--owner`, and `--include-ads` select scanner policies.
Eager owner lookup includes available owner names in machine reports.

Reports go to stdout. `--progress auto` shows a live line on an interactive
stderr. `--progress always` also shows progress on redirected stderr, with up to
one line per five seconds. `--progress never` suppresses it. `--strict` returns
status 4 after reporting a scan with access errors. Interrupting an active scan
returns status 130 after printing the partial report. JSON sets
`meta.cancelled` to `true` in that case.

`--stats-json FILE` creates a separate JSON file with `wall_ms`,
`peak_rss_bytes`, `nodes`, and the scan mode actually used. The node count covers
the scanned tree and excludes the synthetic root.

See the [JSON and NDJSON format](reference/json-export.md) and
[CSV format](reference/csv-export.md) for the machine-readable fields.

## Analysis

```console
dafree --format table top . --kind dirs --leaf-only -n 10
dafree --format table types . --by count -n 15
dafree --format json age . --field modified --buckets 30d,90d,1y
```

`top` ranks files by logical size unless you select `--kind dirs`. Directory
ranking includes the scan root and nested directories using their full totals.
With `--leaf-only`, a directory qualifies if no direct subdirectory holds at
least 1% of its logical size.

`types` groups files by normalized extension. An empty extension denotes files
without one. Sort by size (default) or count, and limit rows with `-n`.

`age` groups files by modification time by default. Select `created` or
`accessed` with `--field`. The default cutoffs are 30, 90 and 180 days, then
one, two and five years. `--buckets` accepts increasing comma-separated day
(`d`) or year (`y`) cutoffs. A year is 365 days. The report has a final
unbounded interval and adds an Unknown row if any timestamps are unavailable.

All three commands accept the global `--format` option. Table output applies
the configured units. Machine-readable reports use byte counts. Excluded
subtrees and duplicate hardlinks do not contribute.

## Configuration commands

```console
dafree config path
dafree config get theme
dafree config set theme dark
dafree config set default_scan.threads 4
dafree config set default_scan.follow_symlinks false
dafree config set units auto
dafree config set unit_style.system iec
```

`get` prints a JSON value. `set` accepts JSON numbers, booleans, null, arrays,
and objects, or a bare string such as `dark`. Quote JSON for your shell:

```sh
dafree config set default_scan.exclude.globs '["*.tmp", "build/**"]'
dafree config set locale null
dafree config get default_scan.exclude.globs
```

Keys use dotted field names. Lists accept non-negative indices, for example
`columns.0.width`; dictionary keys such as `shortcuts.new_scan` can be added.
Optional objects such as `window` must be initialized as an object before
editing their individual fields. Unsupported keys or invalid types exit with
status 2 and leave the previous preferences unchanged. File access errors and
unsupported future schema versions exit with status 1. Schema `version` is
managed by migrations and cannot be changed with `config set`.

## Storage and recovery

CLI and GUI share `settings.json` in
`platformdirs.user_config_dir("disk-analyzer-free", appauthor=False)`.
`config path` prints the actual location without creating it. Saving validates
the complete document, flushes and fsyncs a sibling temporary file, and atomically
replaces the previous file. Failed saves retain the original.

Corrupt JSON, UTF-8, or schema data is preserved as
`settings.json.bad-<unix timestamp>`; a numeric suffix avoids replacing an earlier
backup from the same second. Defaults are then loaded. A future schema version
is left untouched and reported as unsupported. Unversioned/v0 preferences retain
known fields, receive v1 defaults, and are upgraded on the next explicit save.

Preferences include theme (`system`, `light`, `dark`), locale, unit mode/style,
column visibility/width/order, scan defaults, duplicate defaults, window geometry,
shortcuts, and treemap defaults. Recent targets retain at most ten entries, most
recent first. These preferences do not enable features from deferred tasks.
Portable detection is a stub until T10.2; explicit portable requests report an
error rather than silently use normal directories.

## Test isolation

`DAFREE_CONFIG_DIR` is a **test-only override**, not a supported portable-mode
interface. Set it to a directory created by the test: preferences use that root,
and data/log/snapshot directories are contained below it. Tests must never write
real user preferences. The override does not create directories until needed.

## Shell completion

Load the generated script in the current session. Add the same line to your
shell startup file to enable completion in future sessions.

| Shell | Load the script |
| --- | --- |
| Bash 4.4+ | `source <(dafree completion bash)` |
| Zsh | `autoload -Uz compinit && compinit; source <(dafree completion zsh)` |
| Fish | `dafree completion fish \| source` |
| PowerShell | `dafree completion powershell \| Out-String \| Invoke-Expression` |

After loading the script, type `dafree sc` and press Tab to complete `scan`.

## Command reference

::: mkdocs-click
    :module: dafree.cli.main
    :command: cli
    :prog_name: dafree
    :depth: 3
